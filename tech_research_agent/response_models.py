"""Exact server-reviewed response identities; no prefix matching or provider auto-discovery."""
import re
from dataclasses import dataclass
from datetime import date

from persona_prototype.mini_validation import MODEL


@dataclass(frozen=True)
class ResponseModels:
    identifiers: tuple
    verified_by: str
    evidence_sha256: str

    def __post_init__(self):
        ids = self.identifiers
        if not isinstance(ids, (tuple, list)) or not 1 <= len(ids) <= 8 or len(set(ids)) != len(ids):
            raise ValueError('An exact finite response-model list is required')
        for identifier in ids:
            if identifier == MODEL:
                continue
            match = re.fullmatch(r'gpt-4o-mini-(\d{4}-\d{2}-\d{2})', identifier)
            if not match:
                raise ValueError('Response model must be the exact alias or a reviewed exact dated snapshot')
            date.fromisoformat(match[1])
        object.__setattr__(self, 'identifiers', tuple(ids))
        if not self.verified_by or not re.fullmatch(r'[a-f0-9]{64}', self.evidence_sha256):
            raise ValueError('Administrator-reviewed response identity evidence is required')
