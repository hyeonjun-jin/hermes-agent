"""Dedicated demo ledger using existing durable comparison accounting and OpenAI gateway."""
import json
import os
import fnmatch
from dataclasses import asdict
from pathlib import Path

from persona_prototype.mini_validation import ENDPOINT, MODEL, Budget
from persona_prototype.usage_lock import claim_usage_lock
from persona_prototype.web_backend import check_real_network
from .comparison_budget import ComparisonBudget, ComparisonPlan, MAX_REQUEST_RESERVED_USD, reserved_cost
from .paper_demo_policy import PaperDemoPolicy
from .real import RealAdapter, RealBlocked


def connection_readiness():
    if (not os.environ.get('PERSONA_API_KEY', '').strip() or not os.environ.get('OPENALEX_API_KEY', '').strip() or os.environ.get('PERSONA_BASE_URL') != ENDPOINT or
            os.environ.get('PERSONA_MODEL') != MODEL):
        raise RealBlocked('서버 PERSONA_API_KEY, OPENALEX_API_KEY, PERSONA_BASE_URL, PERSONA_MODEL 설정이 필요합니다.')
    runtime = check_real_network(os.environ)  # No policy files or network probes are created.
    if runtime == 'codex':
        policy = json.loads(Path('/etc/codex/network-policy.json').read_text())
        policy = policy.get('http_network_policy', policy)
        mode = policy.get('type', policy.get('mode'))
        if mode != 'unrestricted' and not any(fnmatch.fnmatchcase('api.openalex.org', rule['host'])
                                             for rule in policy.get('egress_rules', [])):
            raise RealBlocked('Codex 네트워크 정책에서 OpenAlex가 허용되지 않았습니다.')


def demo_plan(repository, approval):
    approval.require()
    root = Path(repository).resolve()/'.technical-paper-demo'
    if root.is_symlink():
        raise RealBlocked('시연 원장 경로가 다른 운영 상태를 가리킬 수 없습니다.')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    usage, manifest = root/'usage.json', root/'manifest.json'
    for path in (usage, manifest):
        if path.is_symlink() or (path.exists() and path.stat().st_nlink != 1):
            raise RealBlocked('시연 상태의 링크/별칭은 허용하지 않습니다.')
    with claim_usage_lock(usage):
        if not usage.exists() and not manifest.exists():
            if approval.record['max_reserved_usd'] < 6*MAX_REQUEST_RESERVED_USD:
                raise RealBlocked('6회 정상 경로의 보수적 비용 예약 한도가 부족합니다.')
            with usage.open('x', encoding='utf-8') as stream:
                json.dump({'calls': [], 'failed': False}, stream)
            usage.chmod(0o600)
            plan = ComparisonPlan.capture(usage, approval.record['approval_id'])
            with manifest.open('x', encoding='utf-8') as stream:
                json.dump({'approval_sha256': approval.bound, 'plan': asdict(plan)}, stream)
            manifest.chmod(0o600)
        if not manifest.is_file() or not usage.is_file():
            raise RealBlocked('시연 원장/Manifest 불일치. 초기화하지 말고 관리자에게 확인하세요.')
        saved = json.loads(manifest.read_text())
        plan = ComparisonPlan(**saved['plan'])
        if (saved['approval_sha256'] != approval.bound or plan.ledger_path != str(usage) or
                plan.baseline_count != 0 or plan.campaign_id != approval.record['approval_id']):
            raise RealBlocked('기존 시연 승인·원장과 다릅니다. 예산을 자동 생성/갱신하지 않습니다.')
    return root, plan


class PaperDemoBudget(ComparisonBudget):
    def __init__(self, send, path, plan, condition, approval):
        super().__init__(send, path, plan, condition, approval.record['max_reserved_usd'])
        self.approval = approval

    def _check_request(self, body, suffix):
        self.approval.require()
        super()._check_request(body, suffix)
        if (len(suffix) >= self.approval.record['max_new_calls'] or
                (self.request_role == 'analysis' and any(c['comparison_condition'] == self.condition and
                    c['comparison_role'] == 'analysis' for c in suffix))):
            raise RealBlocked('시연 전체/Analysis 호출 상한에 도달했습니다.')


class PaperDemoAdapter(RealAdapter):
    def __init__(self, path, plan, approval, profile):
        if profile not in ('A', 'B'):
            raise RealBlocked('검수된 시연 Profile A/B만 허용합니다.')
        super().__init__(path, enabled=True, exclusive_ledger_owner=True)
        self.plan, self.approval, self.profile_id = plan, approval, profile
        self.condition = 'v1' if profile == 'A' else 'v2'
        self.public_policy = None
        self.live_execution_approved = False

    def prepare(self, adapter):
        self.approval.require()
        if set(adapter.connectors) != {'openalex'} or adapter.connectors['openalex'].enabled is not True:
            raise RealBlocked('실제 OpenAlex Connector만 허용합니다.')
        self.public_policy = PaperDemoPolicy(adapter, self.approval, self.profile_id)
        adapter.corpus.clear()  # No SYNTHETIC corpus or fallback tools in this isolated demo.
        adapter.context.allowed_sources = {'openalex'}
        adapter.context.entity_topics = {}
        adapter.registry = {key: value for key, value in adapter.registry.items()
                            if key in {'openalex/search_works', 'openalex/read_work'}}
        adapter.outbound_policy = self.public_policy
        return self.public_policy

    def preflight(self):
        self.approval.require()
        connection_readiness()
        if self.public_policy is None:
            raise RealBlocked('시연 반출 경계가 준비되지 않았습니다.')
        self.public_policy._fresh()
        self.live_execution_approved = True
        super().preflight()

    def _check_saved_usage(self, saved):
        suffix = self.plan.suffix(saved)
        if (any(c['comparison_condition'] == self.condition for c in suffix) or
                len(suffix)+6 > self.approval.record['max_new_calls'] or
                reserved_cost(suffix)+6*MAX_REQUEST_RESERVED_USD > self.approval.record['max_reserved_usd']):
            raise RealBlocked('이 Profile이 이미 실행됐거나 6회 호출/비용 예약이 부족합니다. 원장을 초기화하지 않습니다.')

    def _budget_case(self):
        return self.plan.case(self.condition)

    def _make_budget(self, send):
        return PaperDemoBudget(send, self.path, self.plan, self.condition, self.approval)

    def _payload_policy(self, corpus):
        return self.public_policy

    def summary(self):
        view = Budget(None)
        view.calls = self.budget.calls[self.start_attempts:] if self.budget else []
        return {**super().summary(), 'execution_policy': 'public_paper_demo', 'profile_id': self.profile_id,
                'this_run_usage': view.totals(), 'approval_sha256': self.approval.bound,
                'limits': {'campaign': self.approval.record['max_new_calls'], 'profile': 6,
                           'research': 3, 'analysis': 1, 'verification': 2, 'max_tokens': 512, 'remote_retries': 0},
                'max_reserved_usd': self.approval.record['max_reserved_usd'],
                'public_processing_audit': self.public_policy.audit if self.public_policy else [],
                'limitation': 'Only reviewed demonstration Profiles and public OpenAlex metadata/abstracts; no PDF/full text.'}
