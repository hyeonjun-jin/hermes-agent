"""Explicit paired-experiment adapters; existing Real/public adapters keep their original limits."""
import math

from .approved_real import ApprovedPublicAdapter
from .comparison_budget import ComparisonPlan, ComparisonBudget, ROLE_CAPS, MAX_REQUEST_RESERVED_USD, reserved_cost
from .real import RealAdapter, RealBlocked


class ComparisonControls:
    def __init__(self, *args, comparison_plan, condition, live_execution_approved=False, **kwargs):
        if not isinstance(comparison_plan, ComparisonPlan):
            raise TypeError('A pinned server comparison plan is required')
        self.comparison_plan, self.condition = comparison_plan, condition
        comparison_plan.case(condition)
        self.live_execution_approved = live_execution_approved
        super().__init__(*args, **kwargs)
        if str(self.path) != comparison_plan.ledger_path:
            raise ValueError('Plan belongs to a different canonical ledger')

    def _check_saved_usage(self, saved):
        if self.transport is None and self.live_execution_approved is not True:
            raise RealBlocked('Separate actual API execution approval required')
        suffix = self.comparison_plan.suffix(saved)
        used = sum(c['comparison_condition'] == self.condition for c in suffix)
        if used or len(suffix)+6 > 12:
            raise RealBlocked('Condition already attempted or full six-call envelope unavailable')
        if not self.max_reserved_usd:
            raise RealBlocked('Separate comparison cost ceiling required; default zero')
        unstarted = 2-len({c['comparison_condition'] for c in suffix})
        if reserved_cost(suffix)+unstarted*6*MAX_REQUEST_RESERVED_USD > self.max_reserved_usd:
            raise RealBlocked('Full paired comparison cost envelope unavailable')

    def _budget_case(self):
        return self.comparison_plan.case(self.condition)

    def _make_budget(self, send):
        return ComparisonBudget(send, self.path, self.comparison_plan, self.condition, self.max_reserved_usd)

    def summary(self):
        return {**super().summary(), 'comparison_campaign': self.comparison_plan.campaign_id,
                'condition': self.condition, 'new_call_cap': 12, 'condition_cap': 6, 'role_caps': ROLE_CAPS,
                'max_new_reserved_usd': self.max_reserved_usd,
                'comparison_totals': self.budget.comparison_totals() if self.budget else None,
                'limitation': 'Paired allowance only; live execution and public-data approvals are separate. Historical costs are not reset or assumed zero.'}


class ComparisonRealAdapter(ComparisonControls, RealAdapter):
    def __init__(self, *args, max_reserved_usd=0, **kwargs):
        if type(max_reserved_usd) not in (int, float) or not math.isfinite(max_reserved_usd) or max_reserved_usd < 0:
            raise ValueError('Invalid comparison cost ceiling')
        self.max_reserved_usd = max_reserved_usd
        super().__init__(*args, **kwargs)


class ComparisonPublicAdapter(ComparisonControls, ApprovedPublicAdapter):
    pass
