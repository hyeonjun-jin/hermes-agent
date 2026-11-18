"""FABRICATED Stub approvals and source bytes for tests only; never imported by application code."""
import copy
import json
from datetime import UTC, datetime

import httpx

from tech_research_agent.application import ResearchApplication, principal
from tech_research_agent.approvals import ApprovalRegistry, digest, document_subject
from tech_research_agent.approved_memory import memory_subject
from tech_research_agent.comparison_budget import ComparisonPlan
from tech_research_agent.comparison_real import ComparisonPublicAdapter
from tech_research_agent.config import runtime
from tech_research_agent.connectors.openalex import OpenAlexConnector
from tech_research_agent.persona_preferences import memory_record
from tech_research_agent.persona_projection import public_persona_subject
from tech_research_agent.stub_workflow import WorkflowStub

QUESTION = '수소환원제철을 비교 조사해주세요.'
NOW = datetime(2026, 11, 18, tzinfo=UTC)
PRIVATE = 'CONFIDENTIAL_UNPUBLISHED_PERSONA_REASON'
V1 = {'preferred_apps': ['openalex'], 'criteria': ['experimental_conditions'], 'result_limit': 3,
      'technical_detail': 'brief', 'report_format': 'bullets', 'financial_detail': 'brief'}
V2 = {'preferred_apps': ['openalex', 'kipris_plus'], 'criteria': ['financial_risk'], 'result_limit': 2,
      'technical_detail': 'detailed', 'report_format': 'table', 'financial_detail': 'detailed'}


def fake_grant(subject, identifier, **updates):
    return {'approval_id': identifier, 'subject': copy.deepcopy(subject), 'content_sha256': digest(subject),
            'classification': 'PUBLIC', 'external_processing_approved': True, 'terms_approved': True,
            'approved_by': 'FABRICATED TEST ONLY - NOT AN ADMINISTRATOR AUTHORIZATION',
            'verification_status': 'text_reviewed' if subject['kind'] == 'document' else 'memory_reviewed',
            'model': 'gpt-4o-mini', 'purpose': 'technical_research', 'users': ['researcher'], 'projects': ['proj-H'],
            'approved_at': '2026-11-16T00:00:00+00:00', 'expires_at': '2026-12-01T00:00:00+00:00', **updates}


def selected(preferences):
    risk = 'financial_risk' in preferences['criteria']
    return ('W456' if risk else 'W123', 'hydrogen risk' if risk else 'hydrogen experiment')


class PreferenceStub(WorkflowStub):
    def __init__(self, response_model='gpt-4o-mini'):
        super().__init__()
        self.response_model = response_model

    def __call__(self, body):
        self.requests.append(copy.deepcopy(body))
        ctx = json.JSONDecoder().raw_decode(body['messages'][0]['content'].split('TECH_CONTEXT=', 1)[1])[0]
        role = ctx['role']; self.counts[role] += 1
        prefs = ctx['persona_guidance']['preferences']
        identifier, query = selected(prefs)
        action = None
        if role == 'research' and self.counts[role] == 1:
            action = ('openalex__search_works', {'rp': {'query': query}, 'op': {'limit': prefs['result_limit']}})
        if (role == 'research' and self.counts[role] == 2) or (role == 'verification' and self.counts[role] == 1):
            action = ('openalex__read_work', {'rp': {'work_id': identifier}, 'op': {}})
        text = 'STUB_RAW_RESPONSE_ONLY ['+identifier+'] 실험 조건 또는 재무 위험은 원문 범위에서 검토합니다.'
        if prefs['report_format'] == 'table':
            text = '| 근거 | 내용 |\n|---|---|\n| '+identifier+' | '+text+' |'
        message = {'role': 'assistant', 'content': text}
        if action:
            name, args = action
            message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': role+str(self.counts[role]),
                'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}
        return 200, {'id': 'fabricated', 'created': 1, 'model': self.response_model,
                     'choices': [{'message': message, 'finish_reason': 'tool_calls' if action else 'stop'}],
                     'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}


class PairFixture:
    def __init__(self, *, mutate=None, response_model='gpt-4o-mini', omit_projection=False):
        self.mutate, self.response_model, self.omit_projection = mutate, response_model, omit_projection
        self.senders = {}

    @staticmethod
    def connector():
        works = {identifier: {'id': 'https://openalex.org/'+identifier, 'title': 'FABRICATED hydrogen '+identifier,
                 'publication_date': '2026-02-01', 'publication_year': 2026,
                 'abstract_inverted_index': {'Fabricated': [0], 'hydrogen': [1], 'only.': [2]}}
                 for identifier in ('W123', 'W456')}
        def send(request):
            if request.url.path == '/works':
                key = 'W456' if 'risk' in request.url.params.get('search', '') else 'W123'
                return httpx.Response(200, json={'results': [works[key]]})
            return httpx.Response(200, json=works[request.url.path.rsplit('/', 1)[-1]])
        return OpenAlexConnector(enabled=True, transport=httpx.MockTransport(send), clock=lambda: NOW.isoformat())

    def __call__(self, root):
        ledger = root/'usage.json'
        ledger.write_text(json.dumps({'calls': [], 'failed': False}))  # Disposable FABRICATED state only.
        plan = ComparisonPlan.capture(ledger, 'fabricated-persona-pair')
        apps = {}
        for label, prefs, revision in (('v1', V1, 2), ('v2', V2, 3)):
            connector = self.connector()
            app = ResearchApplication(root/label, source_connectors={'openalex': connector})
            self.seed(app, prefs, revision)
            records = self.grants(app)
            sender = PreferenceStub(self.response_model); self.senders[label] = sender
            app.public_real_adapter = ComparisonPublicAdapter(ledger, comparison_plan=plan, condition=label,
                approvals=ApprovalRegistry(records, clock=lambda: NOW), public_processing_enabled=True,
                enabled=True, exclusive_ledger_owner=True, transport=sender, max_reserved_usd=1,
                live_execution_approved=False)
            apps[label] = app
        if self.mutate:
            self.mutate(apps)
        return apps

    @staticmethod
    def seed(app, prefs, revision):
        actor = principal('researcher')
        # These are fabricated approved-shaped versions, never copied into an operating store.
        version = {'revision': revision, 'preferences': prefs, 'data_policy': 'PRIVATE', 'reason': PRIVATE,
                   'created_at': '2026-09-01T00:00:00+00:00'}
        with app.store.connect() as db:
            db.execute('INSERT INTO tr_personas VALUES (?,?,?,?)', ('researcher', 'proj-H', revision, json.dumps(version)))
            db.execute('INSERT INTO tr_active VALUES (?,?,?)', ('researcher', 'proj-H', revision))
            db.execute('INSERT INTO episodes VALUES (NULL,?,?,?,?,?,?)', ('researcher', 'fixed-initial-session',
                '[project=proj-H] '+QUESTION, 'FABRICATED 수소환원제철 이전 관찰 기록', 1, '2026-09-01T00:00:00+00:00'))
        app.store.save_semantic(actor, actor.user_id, {'source_focus': 'science', 'explicitly_approved': True, 'data_policy': 'PUBLIC_SYNTHETIC'})

    def grants(self, app):
        actor = principal('researcher')
        _, _, adapter = runtime(actor.user_id, 'H', 'quick', connectors=app.source_connectors)
        records = []
        for prefs in (V1, V2):
            identifier, query = selected(prefs)
            for api, rp, op in (('search_works', {'query': query}, {'limit': prefs['result_limit']}),
                                ('read_work', {'work_id': identifier}, {})):
                item = adapter.execute({'id': 'fixture', 'app': 'openalex', 'api': api, 'rp': rp, 'op': op, 'after': []})['items'][0]
                records.append(fake_grant(document_subject(item), api+identifier))
        source = memory_record(app.personas.current(actor, 'proj-H'))
        if not self.omit_projection:
            subject = public_persona_subject(actor.user_id, 'proj-H', source, [k for k in source['research_persona']['preferences'] if k != 'financial_detail'])
            records.append(fake_grant(subject, 'persona-expression'))
        semantic = app.store.semantic(actor, actor.user_id)
        records.append(fake_grant(memory_subject('preference', actor.user_id, 'proj-H', semantic), 'legacy'))
        row = app.store.search(actor, actor.user_id, QUESTION, project_id='proj-H')[0]
        records.append(fake_grant(memory_subject('history', actor.user_id, 'proj-H', row), 'history',
                                  document_approvals=['read_workW123', 'read_workW456']))
        return records
