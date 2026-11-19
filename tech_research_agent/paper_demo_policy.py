"""Public-demo-only source scope. Production per-document approvals remain unchanged."""
import copy
import json
import os

from .approved_policy import ApprovedPayloadPolicy
from .approvals import ApprovalRegistry, digest, document_subject
from .config import PROFILES, runtime
from .connectors.openalex import work_id
from .paper_demo_approval import PROFILES_PUBLIC, QUESTION, INSTRUCTIONS, public_environment, review_scope
from .real import RealBlocked


class PaperDemoPolicy(ApprovedPayloadPolicy):
    def __init__(self, adapter, approval, profile):
        super().__init__(ApprovalRegistry(), adapter, response_models=approval.require())
        self.approval, self.profile_id = approval, profile

    def _fresh(self):
        self.approval.require()
        ctx = self.adapter.context
        if (self.failed or ctx.user_id != 'researcher' or ctx.project_id != 'proj-H' or
                ctx.classification != 'PUBLIC' or ctx.allowed_projects != {'proj-H'} or
                ctx.allowed_sources != {'openalex'} or set(self.adapter.connectors) != {'openalex'} or
                ctx.budget != 12 or self.adapter.registry != review_scope()['tool_schemas'] or self.memories or self.entities):
            raise RealBlocked('시연 PUBLIC 범위·권한이 변경됐거나 실행이 중단됐습니다.')
        if self.memory_access is not None:
            self.memory_access()
        for item in list(self.documents.values()):
            self.document(item)

    def document(self, item):
        self._source(item)
        if (item['origin_app'] != 'openalex' or item['locator'] != 'https://openalex.org/'+work_id(item['source_id']) or
                item.get('full_text_read') is not False):
            raise RealBlocked('시연은 OpenAlex 메타데이터/초록만 허용합니다.')
        self.documents[digest(document_subject(item))] = copy.deepcopy(item)

    def register_memory(self, subject, reader=None):
        raise RealBlocked('시연은 기존 Persona·Memory를 전송하지 않습니다.')

    @staticmethod
    def assistant_signature(message):
        value = copy.deepcopy(message)
        if value.pop('annotations', None) not in (None, []):
            raise RealBlocked('검토되지 않은 모델 annotation은 허용하지 않습니다.')
        return ApprovedPayloadPolicy.assistant_signature(value)

    def _sensitive(self, value):
        text = super()._sensitive(value)
        for variable in ('OPENALEX_API_KEY', 'OPENAI_API_KEY'):
            key = os.environ.get(variable, '').strip()
            if key and key in text:
                raise RealBlocked('반환 자료에 인증 정보가 포함되어 차단했습니다.')
        return text

    def _inspect(self, value):
        if isinstance(value, dict) and value.get('synthetic') is True:
            raise RealBlocked('실제 시연에 SYNTHETIC 문서를 섞을 수 없습니다.')
        super()._inspect(value)

    def context(self, value):
        if (value['question'] != QUESTION or value['profile'] != PROFILES['researcher'] or
                value['environment'] != runtime('researcher', 'H', 'quick')[1] or
                value['history'] or value['approved_preferences'] or value['persona_revision'] != 1 or value['entity_catalog']):
            raise RealBlocked('시연용 고정 입력 외의 Profile·Persona·Memory·Environment는 차단합니다.')
        output = copy.deepcopy(value)
        output.update(profile=copy.deepcopy(PROFILES_PUBLIC[self.profile_id]), environment=public_environment(),
                      data_label='PUBLIC OpenAlex — 실제 API 시연', execution_mode='public_paper_demo',
                      demo_instructions=INSTRUCTIONS)
        self.expected_context = copy.deepcopy(output)
        return output

    def observe(self, call, result):
        try:
            self._fresh()
            if (set(result)-{'status', 'items', 'warnings', 'reason', 'next_cursor', 'cost'} or
                    result.get('status') in {'denied', 'unavailable'}):
                raise RealBlocked('정보원 오류 또는 승인 범위 밖 결과')
            for item in result.get('items', []):
                self.document(item)
                self.observed_items.add(digest(item))
            self._sensitive(result)
            self._inspect(result)
            self.receipts.add(digest(result))
            receipt = {'status': 'approved', 'result_sha256': digest(result), 'scope': 'public_paper_demo',
                       'approval_sha256': self.approval.bound}
            self.audit.append(receipt)
            self.adapter.trace[-1]['egress_policy'] = receipt
            return result
        except (RealBlocked, ValueError, TypeError, KeyError, OSError):
            self.failed = True
            self.adapter.trace[-1]['egress_policy'] = {'status': 'denied'}
            return {'status': 'denied', 'reason': 'public_demo_source_or_egress_denied'}

    def remember_response(self, payload):
        if payload['usage']['completion_tokens'] > 512:
            raise RealBlocked('응답 토큰 상한을 초과한 모델 응답입니다.')
        super().remember_response(payload)
        message = payload['choices'][0]['message']
        self.audit[-1]['raw_response'] = copy.deepcopy(message)
        # Raw data is PUBLIC only and headers are never recorded.
        self.audit[-1]['response_bytes'] = len(json.dumps(message, ensure_ascii=False).encode())

    def check(self, payload):
        result = super().check(payload)
        if 'model' in payload:
            system = next(m['content'] for m in payload['messages'] if m['role'] == 'system')
            if (system.split('TECH_CONTEXT=', 1)[0] != review_scope()['system_instructions'] or
                    payload.get('max_tokens') != 512 or payload.get('stream') is not False):
                raise RealBlocked('승인된 시연 시스템 지침/생성 상한과 다릅니다.')
        return result
