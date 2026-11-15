"""Trusted local policy state. Construct on the server, never from model arguments."""
import json
from dataclasses import dataclass, field
from datetime import date
from threading import RLock
from jsonschema.exceptions import ValidationError
from .offline import call_check


@dataclass
class ServerContext:
    user_id: str
    project_id: str
    allowed_projects: set
    allowed_sources: set
    classification: str
    cutoff: str
    budget: int
    document_acl: dict
    entity_topics: dict
    observed_at: str = '2026-10-01T09:00:00+09:00'
    spent: int = 0
    seen: set = field(default_factory=set)
    revoked: set = field(default_factory=set)
    private_terms: set = field(default_factory=set)
    lock: object = field(default_factory=RLock, repr=False)

    def permits(self, source):
        levels = {'PUBLIC': 0, 'INTERNAL': 1, 'RESTRICTED': 2}
        if source['id'] in self.revoked or source['app'] not in self.allowed_sources:
            return False
        if source['published_at'] > self.cutoff:
            return False
        if levels[source['classification']] > levels[self.classification]:
            return False
        if source['classification'] == 'PUBLIC':
            return True
        return (source['project_id'] == self.project_id and self.project_id in self.allowed_projects
                and self.user_id in self.document_acl.get(source['id'], set()))

    def authorize_llm(self, destination, source_ids, corpus):
        """No transport exists here; this is the prerequisite for a future sender."""
        if destination != 'local' and self.classification == 'RESTRICTED':
            return False
        return all(sid in corpus and self.permits(corpus[sid]) and
                   (destination == 'local' or corpus[sid]['classification'] == 'PUBLIC') for sid in source_ids)


def validate(call, context, corpus, registry):
    if not isinstance(call, dict) or set(call) - {'id','app','api','rp','op','after'}:
        return 'invalid_schema'
    try:
        call_check(call, registry)
    except (ValidationError, KeyError, TypeError):
        return 'invalid_schema'
    if set(call['rp']) & set(call['op']):
        return 'invalid_schema'
    if not context.user_id or context.project_id not in context.allowed_projects:
        return 'access_denied'
    if call['app'] not in context.allowed_sources or (
            context.classification == 'RESTRICTED' and call['app'] != 'internal_mock'):
        return 'access_denied'
    params = {**call['rp'], **call['op']}
    if 'project_id' in params and params['project_id'] != context.project_id:
        return 'access_denied'
    if 'corp_code' in params and params['corp_code'] not in context.entity_topics:
        return 'access_denied'
    try:
        if any(date.fromisoformat(params[k]) > date.fromisoformat(context.cutoff)
               for k in ('from_date','to_date') if k in params):
            return 'future_date'
        if params.get('from_date','') > params.get('to_date',context.cutoff):
            return 'invalid_period'
        if int(params.get('bsns_year','0')) > int(context.cutoff[:4]):
            return 'future_date'
    except (ValueError, TypeError):
        return 'invalid_schema'
    if call['app'] != 'internal_mock':
        text = json.dumps(params, ensure_ascii=False).casefold()
        terms = context.private_terms | {context.project_id}
        terms |= {span['text'] for source in corpus.values() if source['classification'] != 'PUBLIC'
                  for span in source['spans']}
        if 'proj-' in text or any(term.casefold() in text for term in terms if term):
            return 'private_egress'
    for key in ('document_id','work_id','application_id','receipt_no','material_id'):
        if key in params:
            sid = params[key]
            if sid not in context.seen or sid not in corpus or not context.permits(corpus[sid]) or corpus[sid]['app'] != call['app']:
                return 'access_denied'
    if context.spent >= context.budget:
        return 'budget_exhausted'
    return None
