"""Server-owned, exact-scope live approval. Reading this record never grants or activates execution."""
import copy
import json
import math
import os
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from persona_prototype.mini_validation import MODEL, ENDPOINT
from persona_prototype.validation import real_settings
from .approvals import digest
from .comparison_real import ComparisonPublicAdapter
from .real import RealBlocked
from .response_models import ResponseModels


class LiveExecutionApproval:
    def __init__(self, record, *, clock=None):
        self.record = copy.deepcopy(record)
        self.clock = clock or (lambda: datetime.now(UTC))
        self._revoked = False
        value = self.record
        if (not value.get('approval_id') or not value.get('approved_by')
                or value.get('actual_execution_approved') is not True or value.get('model') != MODEL
                or value.get('endpoint') != ENDPOINT or type(value.get('max_new_calls')) is not int or value.get('max_new_calls') != 12
                or type(value.get('max_reserved_usd')) not in (int, float)
                or not math.isfinite(value['max_reserved_usd']) or value['max_reserved_usd'] <= 0):
            raise ValueError('Invalid server live execution approval')
        self.response_models = ResponseModels(tuple(value['response_model_ids']), value['approved_by'],
                                              value['response_model_evidence_sha256'])
        options = value['wire_options_sha256']
        if set(options) != {'research', 'analysis', 'verification'} or any(not re.fullmatch(r'[a-f0-9]{64}', v) for v in options.values()):
            raise ValueError('Exact per-role wire generation-option hashes are required')
        self.check_time()

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def check_time(self):
        start = datetime.fromisoformat(self.record['approved_at'])
        end = datetime.fromisoformat(self.record['expires_at'])
        if self._revoked or start.tzinfo is None or end.tzinfo is None or not start <= self.clock() < end:
            raise RealBlocked('Live execution approval expired or not yet valid')

    def revoke(self):
        self._revoked = True

    def check_request(self, actor, question, topic, mode):
        self.check_time()
        if (actor.user_id != self.record['user_id'] or 'proj-'+topic != self.record['project_id']
                or digest(question) != self.record['question_sha256'] or mode != 'quick'):
            raise RealBlocked('Live request is outside administrator scope')
        endpoint, _, model = real_settings(os.environ)
        if endpoint.rstrip('/') != ENDPOINT or model != MODEL:
            raise RealBlocked('Live endpoint/model configuration is not approved')

    def check_adapter(self, adapter):
        self.check_time()
        if (not isinstance(adapter, ComparisonPublicAdapter) or adapter.transport is not None
                or adapter.live_execution_approved is not True or adapter.enabled is not True or adapter.exclusive is not True
                or adapter.public_processing_enabled is not True or not 0 < adapter.max_reserved_usd <= self.record['max_reserved_usd']
                or asdict(adapter.comparison_plan) != self.record['comparison_plan']
                or str(adapter.path) != self.record['comparison_plan']['ledger_path']):
            raise RealBlocked('Live adapter, cost ceiling or pinned plan is outside approval')
        effective = adapter.response_models.identifiers if adapter.response_models is not None else (MODEL,)
        if set(effective) != set(self.response_models.identifiers):
            raise RealBlocked('Response-model configuration differs from administrator approval')
        if adapter.response_models is not None and adapter.response_models != self.response_models:
            raise RealBlocked('Response-model verification evidence differs from approval')

    def check_inputs(self, snapshots):
        self.check_time()
        for label, (fixed, persona) in snapshots.items():
            if (digest(fixed) != self.record['initial_inputs_sha256']
                    or digest(persona) != self.record['personas_sha256'][label]):
                raise RealBlocked('Initial Context/Memory or Persona differs from administrator-approved snapshot')

    def check_dispatch(self, adapter, body):
        self.check_adapter(adapter)
        options = {k: v for k, v in body.items() if k not in {'messages', 'tools'}}
        if digest(options) != self.record['wire_options_sha256'].get(adapter.role):
            raise RealBlocked('Final model/generation options differ from administrator approval')


def validate_live_arms(apps, root, approval):
    if set(apps) != {'v1', 'v2'} or apps['v1'].store.path.resolve() == apps['v2'].store.path.resolve():
        raise RealBlocked('Two isolated live condition stores are required')
    for label, app in apps.items():
        if not app.root.resolve().is_relative_to(root) or not app.store.path.resolve().is_relative_to(root):
            raise RealBlocked('Live research state must use isolated prepared copies')
        if app.public_real_adapter.condition != label or not app.source_connectors:
            raise RealBlocked('A configured approved-public condition is required')
        approval.check_adapter(app.public_real_adapter)
