"""Server-pinned two-condition call allowance. Never rebase or erase an operating ledger."""
import json
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from persona_prototype.mini_validation import Budget, RATES
from .approvals import digest
from .real import RealBlocked, ReservedBudget, reservation_upper_bound

ROLE_CAPS = {'research': 3, 'analysis': 2, 'verification': 2}
CONDITIONS = ('v1', 'v2')
MAX_REQUEST_RESERVED_USD = (64_000*RATES['input_usd_per_million']+512*RATES['output_usd_per_million'])/1_000_000


def reserved_cost(suffix):
    values = [c.get('reserved_usd_upper_bound') for c in suffix]
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
        raise RealBlocked('Unresolved campaign reservation')
    return sum(values)


@dataclass(frozen=True)
class ComparisonPlan:
    ledger_path: str
    campaign_id: str
    baseline_count: int
    baseline_sha256: str

    def __post_init__(self):
        if (not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', self.campaign_id)
                or type(self.baseline_count) is not int or self.baseline_count < 0
                or not re.fullmatch(r'[a-f0-9]{64}', self.baseline_sha256)
                or Path(self.ledger_path).resolve().name != 'usage.json'):
            raise ValueError('Invalid server comparison plan')

    @classmethod
    def capture(cls, path, campaign_id):
        """Read-only plan preparation; pin ONCE in server configuration for both conditions/restarts."""
        path = Path(path).resolve()
        saved = json.loads(path.read_text())
        if set(saved) != {'calls', 'failed'} or saved.get('failed') is not False or not isinstance(saved.get('calls'), list):
            raise RealBlocked('Cannot approve a failed or malformed ledger')
        if any(call.get('status') == 'pending' for call in saved['calls']):
            raise RealBlocked('Pending attempt requires reconciliation')
        if any('comparison_campaign' in call for call in saved['calls']):
            raise RealBlocked('Reload the original pinned plan; comparison allowance cannot be recaptured')
        return cls(str(path), campaign_id, len(saved['calls']), digest(saved['calls']))

    def case(self, condition):
        if condition not in CONDITIONS:
            raise ValueError('Comparison condition must be v1 or v2')
        return 'comparison-'+self.campaign_id+'-'+condition

    def suffix(self, saved):
        calls = saved.get('calls')
        if (saved.get('failed') is not False or not isinstance(calls, list)
                or digest(calls[:self.baseline_count]) != self.baseline_sha256):
            raise RealBlocked('Failed ledger or original history changed; no automatic reset')
        suffix = calls[self.baseline_count:]
        counts = {condition: 0 for condition in CONDITIONS}
        roles = {}
        for call in suffix:
            condition = call.get('comparison_condition')
            role = call.get('comparison_role')
            if (condition not in CONDITIONS or role not in ROLE_CAPS
                    or call.get('actor') != self.case(condition)+':'+role
                    or call.get('comparison_campaign') != self.campaign_id
                    or call.get('status') == 'pending'):
                raise RealBlocked('Foreign or pending attempt in comparison ledger')
            counts[condition] += 1
            roles[condition, role] = roles.get((condition, role), 0)+1
        if (len(suffix) > 12 or any(value > 6 for value in counts.values())
                or any(value > ROLE_CAPS[role] for (_, role), value in roles.items())):
            raise RealBlocked('Comparison allowance exceeded')
        return suffix


class ComparisonBudget(ReservedBudget):
    def __init__(self, send, path, plan, condition, ceiling):
        super().__init__(send, path)
        if type(ceiling) not in (int, float) or not math.isfinite(ceiling) or ceiling < 0:
            raise ValueError('Invalid comparison cost ceiling')
        self.plan, self.condition, self.ceiling = plan, condition, ceiling
        self.limit = plan.baseline_count+12
        self._comparison_lock = threading.Lock()

    def forward(self, body):
        with self._comparison_lock:
            try:
                suffix = self._verified_suffix()
            except RealBlocked as exc:
                self.failed = True
                return 429, {'error': {'message': str(exc)}}  # Never overwrite a changed/foreign ledger.
            try:
                self._check_request(body, suffix)
            except RealBlocked as exc:
                self.failed = True
                self.persist()
                return 429, {'error': {'message': str(exc)}}
            result = Budget.forward(self, body)
            self.persist()
            return result

    def _verified_suffix(self):
        saved = json.loads(self.path.read_text())
        if saved != {'calls': self.calls, 'failed': self.failed}:
            raise RealBlocked('Ledger changed outside the active comparison; stopped without writing')
        return self.plan.suffix(saved)

    def _check_request(self, body, suffix):
        first = next((m for m in body['messages'] if m['role'] == 'user'), {})
        match = re.match(r'\[PERSONA_ROLE=(research|analysis|verification)\]\n', str(first.get('content', '')))
        if match is None or self.case != self.plan.case(self.condition):
            raise RealBlocked('Missing server role or comparison condition')
        self.request_role = match[1]
        selected = [c for c in suffix if c['comparison_condition'] == self.condition]
        if (len(suffix) >= 12 or len(selected) >= 6 or
                sum(c['comparison_role'] == self.request_role for c in selected) >= ROLE_CAPS[self.request_role]):
            raise RealBlocked('Comparison total/condition/role call cap reached')
        if reserved_cost(suffix)+reservation_upper_bound(body) > self.ceiling:
            raise RealBlocked('Comparison cost ceiling or unresolved campaign reservation')

    def _send(self, body):
        # Stable identity is durable even if the process dies during the upstream request.
        self.calls[-1].update(actor=self.case+':'+self.request_role, comparison_campaign=self.plan.campaign_id,
                              comparison_condition=self.condition, comparison_role=self.request_role)
        return super()._send(body)

    def comparison_totals(self):
        # Reuse the existing token accounting; only the approved suffix belongs to this experiment.
        view = Budget(None)
        view.calls = self.calls[self.plan.baseline_count:]
        return {**view.totals(), 'reserved_usd_upper_bound': reserved_cost(view.calls)}
