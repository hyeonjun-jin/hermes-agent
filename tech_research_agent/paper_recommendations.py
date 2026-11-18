"""Local reranking of observed, authorized OpenAlex search + read receipts. Never performs I/O."""
import re
from datetime import date
from urllib.parse import urlsplit

from .paper_ranking import rank_papers


def public_link(value, *, doi=False):
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
        return None
    if doi and (url.hostname.casefold() not in {'doi.org', 'dx.doi.org'} or not re.fullmatch(r'/10\.\d{4,9}/\S+', url.path)):
        return None
    return value


def paper_record(item, source):
    synthetic = item.get('synthetic') is True
    payload = source.get('payload', {}) if synthetic else item
    abstract = payload.get('abstract')
    checked = bool(abstract) and (synthetic or item.get('evidence_coverage') == 'abstract')
    return {'source_id': item['source_id'], 'title': item['title'], 'published_at': item['published_at'],
            'publication_year': payload.get('publication_year') or int(item['published_at'][:4]),
            'doi': None if synthetic else public_link(payload.get('doi'), doi=True),
            'openalex_link': None if synthetic else public_link(item.get('locator')),
            'source_link': None if synthetic else public_link(payload.get('full_text_url')),
            'abstract': abstract if checked else None, 'abstract_checked': checked,
            'evidence_coverage': 'synthetic_abstract' if synthetic and checked else 'abstract' if checked else 'metadata_only',
            'synthetic': synthetic, 'source_basis': 'SYNTHETIC fixture' if synthetic else 'OpenAlex metadata/abstract; DOI link not independently resolved'}


def recommend_from_trace(adapter, profile, approved, environment, question):
    searched, reads = set(), {}
    for event in adapter.trace:
        plan, result = event['plan'], event['result']
        if (plan['app'] != 'openalex' or not event['executed'] or result['status'] not in {'ok', 'partial'}
                or event.get('egress_policy', {}).get('status', 'approved') != 'approved'):
            continue
        if plan['api'] == 'search_works':
            searched.update(item['source_id'] for item in result.get('items', []))
        elif plan['api'] == 'read_work':
            for item in result.get('items', []):
                if item['source_id'] in searched:
                    reads[item['source_id']] = item
    candidates = []
    cutoff = min(date.fromisoformat(environment['cutoff']), date.fromisoformat(environment['as_of']))
    for identifier, item in reads.items():
        source = adapter.corpus.get(identifier)
        if (not source or not adapter.context.permits(source) or adapter.context.project_id not in adapter.context.allowed_projects
                or item.get('classification') != 'PUBLIC' or source.get('app') != 'openalex'
                or any(item.get(key) != source.get(key) for key in ('title', 'published_at', 'spans', 'synthetic'))
                or source.get('project_id') not in (None, environment['project_id'])
                or source.get('topic') not in (None, environment['topic']) or 'openalex' not in environment['allowed_sources']):
            continue
        try:
            if date.fromisoformat(item['published_at']) > cutoff:
                continue
        except (ValueError, TypeError):
            continue
        candidates.append(paper_record(item, source))
    ranked = rank_papers(candidates, profile, approved, environment, question)
    return {'method': 'deterministic_heuristic_v1', 'candidate_ids': sorted(p['source_id'] for p in candidates),
            'items': ranked, 'additional_model_calls': 0, 'additional_source_calls': 0,
            'limitation': 'Observed candidate set only; not an exhaustive paper search. No PDF/full text read or ML learning claim.'}
