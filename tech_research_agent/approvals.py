"""Server-owned, exact-content processing grants. No grant creation from model/UI input."""
import copy
import hashlib
import json
from datetime import UTC, datetime
from threading import RLock

from persona_prototype.mini_validation import MODEL
from .real import RealBlocked

PURPOSE = 'technical_research'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def document_subject(item):
    # Acquisition time changes on a fresh Read; all content, identity and verification fields remain bound.
    return {'kind': 'document', 'item': {key: copy.deepcopy(value) for key, value in item.items() if key != 'retrieved_at'}}


class ApprovalRegistry:
    def __init__(self, records=(), *, clock=None):
        self.clock = clock or (lambda: datetime.now(UTC))
        self._records = {}
        self._revoked = set()
        self._lock = RLock()
        for record in records:
            value = copy.deepcopy(record)
            if not isinstance(value.get('subject'), dict):
                raise ValueError('Invalid processing subject')
            if (not value.get('approval_id') or value['approval_id'] in self._records or
                    value.get('content_sha256') != digest(value.get('subject')) or
                    value.get('classification') != 'PUBLIC' or
                    value.get('external_processing_approved') is not True or value.get('terms_approved') is not True or
                    not value.get('approved_by') or value.get('verification_status') not in
                    {'metadata_reviewed', 'text_reviewed', 'rows_reviewed', 'memory_reviewed'} or
                    value.get('model') != MODEL or value.get('purpose') != PURPOSE or
                    value.get('subject', {}).get('kind') not in {'document', 'history', 'preference', 'company_catalog'} or
                    not isinstance(value.get('users'), list) or not isinstance(value.get('projects'), list)):
                raise ValueError('Invalid server processing grant')
            memory = value['subject']['kind'] in {'history', 'preference'}
            if (value['verification_status'] == 'memory_reviewed') != memory:
                raise ValueError('Review type does not match processing subject')
            start, end = self._dates(value)
            if start >= end:
                raise ValueError('Invalid grant validity')
            self._records[value['approval_id']] = value

    def eligible_documents(self, context):
        with self._lock:
            identifiers = [key for key, row in self._records.items() if row['subject']['kind'] == 'document']
        result = []
        for identifier in identifiers:
            try:
                result.append(self.require_id(identifier, context))
            except RealBlocked:
                continue
        return result

    def eligible_persona_projections(self, context):
        """Server-configured grants only; this does not create or classify a Persona."""
        with self._lock:
            identifiers = [key for key, row in self._records.items()
                           if row['subject']['kind'] == 'preference' and 'persona_binding' in row['subject']]
        result = []
        for identifier in identifiers:
            try:
                result.append(self.require_id(identifier, context))
            except RealBlocked:
                continue
        return result

    @staticmethod
    def _dates(record):
        start = datetime.fromisoformat(record['approved_at'])
        end = datetime.fromisoformat(record['expires_at'])
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError('Grant timestamps require timezone')
        return start, end

    def revoke(self, approval_id):
        with self._lock:
            self._revoked.add(approval_id)

    def require_id(self, approval_id, context):
        with self._lock:
            record = copy.deepcopy(self._records.get(approval_id))
            if record is None or approval_id in self._revoked:
                raise RealBlocked('Processing approval missing or withdrawn')
        start, end = self._dates(record)
        if (not start <= self.clock() < end or context.classification != 'PUBLIC' or
                context.user_id not in record['users'] or context.project_id not in record['projects'] or
                context.project_id not in context.allowed_projects):
            raise RealBlocked('Processing approval scope or validity denied')
        return record

    def authorize(self, subject, context):
        content_hash = digest(subject)
        with self._lock:
            identifiers = [key for key, row in self._records.items() if row['content_sha256'] == content_hash]
        for identifier in identifiers:
            try:
                return self.require_id(identifier, context)
            except RealBlocked:
                continue
        raise RealBlocked('No current exact-content processing approval')

    @property
    def configured(self):
        return bool(self._records)
