"""Separate server opt-in for approved public processing; legacy paid caps remain unchanged."""
import math
import threading
from .approved_policy import ApprovedPayloadPolicy
from .real import RealAdapter, RealBlocked, ReservedBudget, reservation_upper_bound


class ApprovedPublicBudget(ReservedBudget):
    def __init__(self, send, path, ceiling):
        super().__init__(send, path)
        self.ceiling = ceiling
        self._cost_lock = threading.Lock()

    def forward(self, body):
        with self._cost_lock:
            return self._bounded_forward(body)

    def _bounded_forward(self, body):
        reservations = [call.get('reserved_usd_upper_bound') for call in self.calls]
        if (any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in reservations) or
                sum(reservations)+reservation_upper_bound(body) > self.ceiling):
            self.failed = True
            self.persist()
            return 429, {'error': {'message': 'Approved public cost ceiling or unreconciled legacy reservation'}}
        return super().forward(body)


class ApprovedPublicAdapter(RealAdapter):
    def __init__(self, usage_path, *, approvals, public_processing_enabled=False, max_reserved_usd=0, response_models=None, **kwargs):
        super().__init__(usage_path, **kwargs)
        self.approvals = approvals
        self.public_processing_enabled = public_processing_enabled
        self.public_policy = None
        self.response_models = response_models
        if type(max_reserved_usd) not in (int, float) or not math.isfinite(max_reserved_usd) or max_reserved_usd < 0:
            raise ValueError('Invalid server cost ceiling')
        self.max_reserved_usd = max_reserved_usd

    def prepare(self, adapter):
        if self.public_processing_enabled is not True or not self.approvals.configured:
            raise RealBlocked('Separate administrator public-processing opt-in and grants required')
        self.public_policy = ApprovedPayloadPolicy(self.approvals, adapter, response_models=self.response_models)
        eligible = self.approvals.eligible_documents(adapter.context)
        if not eligible:
            raise RealBlocked('No current document processing approval for this user/project')
        for grant in eligible:
            self.public_policy._source(grant['subject']['item'])
        adapter.outbound_policy = self.public_policy
        return self.public_policy

    def preflight(self):
        if self.public_processing_enabled is not True or self.public_policy is None:
            raise RealBlocked('Approved-public processing not prepared by server')
        if not self.max_reserved_usd:
            raise RealBlocked('Separate administrator cost ceiling required; default zero, no paid activation')
        self.public_policy._fresh()
        super().preflight()

    def _payload_policy(self, corpus):
        if self.public_policy is None:
            raise RealBlocked('Missing approved-public policy')
        return self.public_policy

    def _make_budget(self, send):
        return ApprovedPublicBudget(send, self.path, self.max_reserved_usd)

    def summary(self):
        return {**super().summary(), 'execution_policy': 'approved_public',
                'max_reserved_usd': self.max_reserved_usd,
                'public_processing_audit': self.public_policy.audit if self.public_policy else []}
