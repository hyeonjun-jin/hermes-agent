"""Fail-closed approved-public egress boundary over live server state and exact receipts."""
import copy
import json
import os
import hashlib
import sqlite3
from urllib.parse import urlsplit

from .approvals import digest, document_subject
from .real import PayloadPolicy, RealBlocked, PUBLIC_QUESTIONS, inspect_labels


class ApprovedPayloadPolicy:
    def __init__(self, registry, adapter):
        self.registry, self.adapter = registry, adapter
        self.legacy = PayloadPolicy(adapter.corpus)
        self.documents = {}
        self.observed_items = set()
        self.entities = {}
        self.memories = []
        self.memory_access = None
        self.receipts = set()
        self.responses = set()
        self.response_tool_ids = set()
        self.audit = []
        self.expected_context = None
        self.expected_tools = None
        self.failed = False

    def _source(self, item):
        if (item.get('classification') != 'PUBLIC' or item.get('synthetic') is not False or
                item.get('origin_app') not in self.adapter.connectors or
                urlsplit(item.get('locator', '')).scheme != 'https' or not item.get('spans')):
            raise RealBlocked('Unverified or unclassified public source')
        source = self.adapter._source(item)
        ctx = self.adapter.context
        if (ctx.classification != 'PUBLIC' or ctx.project_id not in ctx.allowed_projects or
                not ctx.permits(source) or not self.adapter._source_company_permitted(source)):
            raise RealBlocked('Current source permission or version denied')
        if item['origin_app'] == 'posco_ir':
            connector = self.adapter.connectors['posco_ir']
            entry = connector.catalog.get(item['source_id'])
            if entry.get('local_path'):
                from .connectors.ir_pdf import local_pdf, PDFRejected
                try:
                    actual = hashlib.sha256(local_pdf(connector.local_root, entry['local_path'])).hexdigest()
                except (PDFRejected, OSError) as exc:
                    raise RealBlocked('IR approved bytes unavailable') from exc
                if actual != entry['sha256']:
                    raise RealBlocked('IR approved bytes changed')

    def document(self, item):
        self._source(item)
        subject = document_subject(item)
        grant = self.registry.authorize(subject, self.adapter.context)
        self.documents[digest(subject)] = copy.deepcopy(item)
        return grant

    def register_memory(self, subject, reader=None):
        grant = self.registry.authorize(subject, self.adapter.context)
        if subject['kind'] == 'history' and not grant.get('document_approvals'):
            raise RealBlocked('Research history requires explicit source approval dependencies')
        self.memories.append((copy.deepcopy(subject), reader))
        self._dependencies(grant)
        self.audit.append({'status': 'memory_approved', 'kind': subject['kind'],
                           'approval_id': grant['approval_id'], 'content_sha256': grant['content_sha256']})
        return grant

    def _dependencies(self, grant):
        for identifier in grant.get('document_approvals', []):
            dependency = self.registry.require_id(identifier, self.adapter.context)
            if dependency['subject'].get('kind') != 'document':
                raise RealBlocked('Invalid Memory source dependency')
            self._source(dependency['subject']['item'])

    def observe(self, call, result):
        """Called on server adapter results before any tool response reaches Hermes/model."""
        try:
            if set(result)-{'status', 'items', 'rows', 'warnings', 'reason', 'next_cursor', 'cost'}:
                raise RealBlocked('Unknown tool response fields')
            approved_rows = []
            for item in result.get('items', []):
                if item.get('synthetic') is True:
                    inspect_labels(item, self.legacy.public)
                    approved_rows.extend(self.adapter.corpus[item['source_id']].get('payload', {}).get('rows', []))
                else:
                    grant = self.document(item)
                    self.observed_items.add(digest(item))
                    self.audit.append({'status': 'document_approved', 'source_id': item['source_id'],
                                       'approval_id': grant['approval_id'], 'content_sha256': grant['content_sha256'],
                                       'hash_kind': 'normalized_document_sha256', 'source_url': item['locator'],
                                       'origin_app': item['origin_app'], 'original_sha256': item.get('sha256'),
                                       'verification_status': grant['verification_status']})
                    approved_rows.extend(item.get('rows', []))
            if any(row not in approved_rows for row in result.get('rows', [])):
                raise RealBlocked('Unapproved financial rows')
            self._sensitive(result)
            self._inspect(result)
            self.receipts.add(digest(result))
            self.adapter.trace[-1]['egress_policy'] = {'status': 'approved', 'result_sha256': digest(result)}
            return result
        except (RealBlocked, ValueError, KeyError, TypeError):
            self.failed = True
            self.audit.append({'status': 'tool_result_denied'})
            self.adapter.trace[-1]['egress_policy'] = {'status': 'denied'}
            return {'status': 'denied', 'reason': 'external_processing_not_approved'}

    def context(self, value):
        if value['question'] not in PUBLIC_QUESTIONS or value['environment']['classification'] != 'PUBLIC':
            raise RealBlocked('Existing PUBLIC question/environment restriction remains active')
        output = copy.deepcopy(value)
        for company in output['entity_catalog']:
            if company.get('synthetic') is False:
                self.entity(company)
        output['environment'].pop('project_id', None)
        output['environment']['public_project'] = output['environment']['topic']
        for row in output['history']:
            row.pop('memory_id', None)
        output['execution_mode'] = 'approved_public'
        self.expected_context = copy.deepcopy(output)
        return output

    def entity(self, value):
        from .config import entity_catalog
        if value.get('classification') != 'PUBLIC' or value not in entity_catalog(self.adapter):
            raise RealBlocked('Current verified company catalog denied')
        subject = {'kind': 'company_catalog', 'item': copy.deepcopy(value)}
        self.registry.authorize(subject, self.adapter.context)
        self.entities[digest(value)] = copy.deepcopy(value)

    def _sensitive(self, value):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        lowered = text.casefold()
        forbidden = self.legacy.private | self.adapter.context.private_terms | {self.adapter.context.project_id}
        if 'proj-' in lowered or any(term and term.casefold() in lowered for term in forbidden):
            raise RealBlocked('Non-public content in complete payload')
        secret = os.environ.get('PERSONA_API_KEY', '')
        if (secret and secret in text) or any(marker in text for marker in ('/workspace/', '/home/', 'sk-proj-', 'sk-test-secret', 'PRIVATE_MEMORY')):
            raise RealBlocked('Credential, private path or Memory denied')
        return text

    def _inspect(self, value):
        if isinstance(value, dict):
            level = value.get('classification')
            memory_level = value.get('data_policy')
            if (('classification' in value and not isinstance(level, dict) and level != 'PUBLIC') or
                    ('data_policy' in value and not isinstance(memory_level, dict) and
                     memory_level not in {'PUBLIC', 'PUBLIC_SYNTHETIC', 'PUBLIC_APPROVED'})):
                raise RealBlocked('Non-public labels denied')
            if 'source_id' in value:
                if value.get('synthetic') is True:
                    inspect_labels(value, self.legacy.public)
                else:
                    if digest(document_subject(value)) not in self.documents or digest(value) not in self.observed_items:
                        raise RealBlocked('Unobserved or modified source/span')
                    self.document(value)
            elif value.get('synthetic') is False:
                if digest(value) not in self.entities:
                    raise RealBlocked('Unidentified non-synthetic material')
                self.entity(value)
            for child in value.values():
                self._inspect(child)
        elif isinstance(value, list):
            for child in value:
                self._inspect(child)
        elif isinstance(value, str) and value.lstrip().startswith(('{', '[')):
            try:
                child = json.loads(value)
            except ValueError:
                return
            self._inspect(child)

    def _fresh(self):
        ctx = self.adapter.context
        if self.failed or ctx.classification != 'PUBLIC' or ctx.project_id not in ctx.allowed_projects:
            raise RealBlocked('Approved-public run stopped or current project denied')
        if not self.registry.eligible_documents(ctx):
            raise RealBlocked('No current document processing approval')
        for item in list(self.documents.values()):
            self.document(item)
        for company in list(self.entities.values()):
            self.entity(company)
        try:
            if self.memory_access is not None:
                self.memory_access()
            for subject, reader in self.memories:
                if reader is not None and digest(reader()) != digest(subject):
                    raise RealBlocked('Memory changed after approval snapshot')
                self._dependencies(self.registry.authorize(subject, ctx))
        except (PermissionError, sqlite3.Error, OSError) as exc:
            raise RealBlocked('Current Memory access revoked or unavailable') from exc

    @staticmethod
    def assistant_signature(message):
        if set(message)-{'role', 'content', 'tool_calls', 'refusal'}:
            raise RealBlocked('Unsupported assistant message fields')
        value = {key: copy.deepcopy(child) for key, child in message.items() if child is not None and child != [] and child != ''}
        for call in value.get('tool_calls', []):
            # Hermes canonically serializes argument JSON. Bind its parsed value, while retaining raw calls in the audit.
            call['function']['arguments'] = json.loads(call['function']['arguments'], object_pairs_hook=unique_pairs)
        return digest(value)

    def remember_response(self, payload):
        if payload.get('model') != 'gpt-4o-mini':
            raise RealBlocked('Unapproved response model')
        message = payload['choices'][0]['message']
        self.responses.add(self.assistant_signature(message))
        self.response_tool_ids.update(call['id'] for call in message.get('tool_calls', []))
        self.audit.append({'status': 'response_approved', 'response_sha256': digest(payload)})

    def _wire_messages(self, payload):
        if self.expected_context is None:
            raise RealBlocked('Missing server context')
        if set(payload)-{'model', 'messages', 'tools', 'tool_choice', 'temperature', 'top_p', 'frequency_penalty',
                         'presence_penalty', 'max_tokens', 'stream', 'parallel_tool_calls', 'seed', 'reasoning_effort', 'service_tier'}:
            raise RealBlocked('Unsupported outbound request fields')
        messages = payload['messages']
        users = [m for m in messages if m['role'] == 'user']
        expected = '[PERSONA_ROLE='+self.expected_context['role']+']\n'+self.expected_context['question']
        if len(users) != 1 or users[0].get('content') != expected:
            raise RealBlocked('Unclassified or changed user message')
        if sum(m['role'] == 'system' for m in messages) != 1:
            raise RealBlocked('Missing server system prompt')
        for message in messages:
            if message['role'] in {'system', 'user'} and set(message)-{'role', 'content'}:
                raise RealBlocked('Unclassified message attachment')
            if message['role'] == 'tool' and set(message)-{'role', 'content', 'tool_call_id', 'name'}:
                raise RealBlocked('Unclassified tool attachment')
            if message['role'] == 'assistant' and self.assistant_signature(message) not in self.responses:
                raise RealBlocked('Unobserved assistant history')
            if message['role'] == 'tool' and message.get('tool_call_id') not in self.response_tool_ids:
                raise RealBlocked('Unobserved tool response ID')
            if message['role'] not in {'system', 'user', 'assistant', 'tool'}:
                raise RealBlocked('Unsupported message role')

    def check(self, payload):
        self._fresh()
        if payload.get('model', 'gpt-4o-mini') != 'gpt-4o-mini':
            raise RealBlocked('Unapproved processing model')
        text = self._sensitive(payload)
        if len(text.encode()) > 64000:
            raise RealBlocked('Payload size limit exceeded')
        self._inspect(payload)
        if 'model' in payload:
            self._wire_messages(payload)
        for message in payload.get('messages', []):
            content = message.get('content', '')
            if isinstance(content, str) and 'TECH_CONTEXT=' in content:
                context = json.JSONDecoder().raw_decode(content.split('TECH_CONTEXT=', 1)[1])[0]
                if context != self.expected_context:
                    raise RealBlocked('Unapproved Profile/Environment/Memory context')
                self._inspect(context)
            if message.get('role') == 'tool':
                if digest(json.loads(content)) not in self.receipts:
                    raise RealBlocked('Unobserved or changed complete tool result')
        if 'tools' in payload and payload['tools'] != self.expected_tools:
            raise RealBlocked('Unapproved tool schema/role change')
        self.audit.append({'status': 'payload_approved', 'payload_sha256': digest(payload)})
        return digest(payload)

    def before_send(self, payload):
        # Recheck after durable cost reservation, immediately before the actual transport.
        self.check(payload)


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RealBlocked('Ambiguous duplicate JSON argument keys')
        result[key] = value
    return result
