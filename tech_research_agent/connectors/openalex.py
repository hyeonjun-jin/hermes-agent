"""Bounded OpenAlex metadata/abstract client. Never downloads publisher pages or PDFs."""
import re
from datetime import UTC, date, datetime

import httpx

WORK_ID = re.compile(r'(?:https://openalex.org/)?(W[0-9]+)\Z')
TYPE = re.compile(r'[a-z]+(?:-[a-z]+)*\Z')
SORTS = {'date_desc': 'publication_date:desc', 'citations_desc': 'cited_by_count:desc',
         'relevance': 'relevance_score:desc'}


def work_id(value):
    match = WORK_ID.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ValueError('invalid_openalex_id')
    return match[1]


def abstract_text(index):
    """Reject ambiguous/gapped indexes rather than fabricate missing words."""
    if not index:
        return None
    if not isinstance(index, dict):
        raise ValueError('invalid_abstract_index')
    words = {}
    for word, positions in index.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            raise ValueError('invalid_abstract_index')
        for pos in positions:
            if type(pos) is not int or not 0 <= pos < 100000 or pos in words:
                raise ValueError('invalid_abstract_index')
            words[pos] = word
    if not words or sorted(words) != list(range(len(words))):
        raise ValueError('invalid_abstract_index')
    return ' '.join(words[pos] for pos in range(len(words)))


def normalize(raw, retrieved_at, request_url, include_abstract=True):
    if not isinstance(raw, dict):
        raise ValueError('invalid_work')
    identifier = work_id(raw['id'])
    published = date.fromisoformat(raw['publication_date']).isoformat()
    title = raw.get('title') or raw.get('display_name')
    if not isinstance(title, str) or not title.strip():
        raise ValueError('missing_title')
    abstract = abstract_text(raw.get('abstract_inverted_index')) if include_abstract else None
    location = raw.get('primary_location') or {}
    source = location.get('source') or {}
    oa = raw.get('open_access') or {}
    spans = [{'id': 'metadata', 'text': title, 'kind': 'metadata'}]
    if abstract:
        spans.append({'id': 'abstract', 'text': abstract, 'kind': 'abstract'})
    return {'source_id': identifier, 'title': title, 'origin_app': 'openalex',
            'published_at': published, 'publication_year': raw.get('publication_year'),
            'doi': raw.get('doi'), 'authors': [a['author'] for a in raw.get('authorships', [])],
            'source': {'id': source.get('id'), 'title': source.get('display_name')},
            'type': raw.get('type'), 'language': raw.get('language'),
            'locator': 'https://openalex.org/'+identifier, 'request_url': request_url,
            'retrieved_at': retrieved_at, 'classification': 'PUBLIC', 'synthetic': False,
            'data_origin': 'openalex_public', 'content_trust': 'untrusted_external_data',
            'abstract': abstract, 'abstract_available': bool(raw.get('abstract_inverted_index')),
            'evidence_coverage': 'abstract' if abstract else 'metadata_only',
            'full_text_available': oa.get('is_oa'), 'full_text_availability_basis': 'open_access.is_oa',
            'full_text_url': oa.get('oa_url'),
            'full_text_read': False, 'spans': spans}


class OpenAlexConnector:
    def __init__(self, *, enabled=False, api_key=None, transport=None, clock=None, api_key_parameter=False):
        self.enabled = enabled
        self._query_key = api_key if api_key_parameter else None
        if api_key_parameter:
            from .openalex_logging import protect_query_logging
            protect_query_logging()
        self.clock = clock or (lambda: datetime.now(UTC).isoformat())
        # No ambient proxy credentials; no redirects to arbitrary publisher URLs.
        self.client = httpx.Client(transport=transport, timeout=15, follow_redirects=False,
                                   trust_env=False, headers={'Authorization': 'Bearer '+api_key} if api_key and not api_key_parameter else {})

    def close(self):
        self.client.close()

    def execute(self, api, params, cutoff):
        if not self.enabled:
            return self._result('denied', reason='connector_disabled', attempted=False)
        try:
            path, query = self._request(api, params, cutoff)
        except (ValueError, KeyError, TypeError):
            return self._result('denied', reason='unsupported_connector_parameters', attempted=False)
        url = 'https://api.openalex.org'+path
        if self._query_key:
            query['api_key'] = self._query_key
        try:
            response = self.client.get(url, params=query)
            if response.status_code in (401, 403):
                return self._result('denied', reason='source_access_denied')
            if response.status_code != 200:
                return self._result('unavailable', reason='source_http_'+str(response.status_code))
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError('invalid_payload')
            rows = payload['results'] if api == 'search_works' else [payload]
            if not isinstance(rows, list):
                raise ValueError('invalid_results')
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return self._result('unavailable', reason='source_transport_or_payload_error')
        return self._convert(rows, api, params, cutoff, str(response.request.url.copy_remove_param('api_key')))

    def _request(self, api, params, cutoff):
        if api == 'read_work':
            return '/works/'+work_id(params['work_id']), {}
        if api != 'search_works' or params.get('cursor'):
            raise ValueError('unsupported_api_or_cursor')
        kinds = params.get('types', [])
        if (not kinds and 'types' in params) or any(not TYPE.fullmatch(k) for k in kinds):
            raise ValueError('invalid_types')
        filters = ['to_publication_date:'+params.get('to_date', cutoff)]
        if 'from_date' in params:
            filters.append('from_publication_date:'+params['from_date'])
        if kinds:
            filters.append('type:'+'|'.join(kinds))
        if 'language' in params:
            filters.append('language:'+params['language'])
        if 'open_access' in params:
            filters.append('open_access.is_oa:'+str(params['open_access']).lower())
        return '/works', {'search': params['query'], 'filter': ','.join(filters),
                           'per_page': params.get('limit', 3), 'sort': SORTS[params.get('sort', 'relevance')]}

    def _convert(self, rows, api, params, cutoff, request_url):
        items, warnings = [], []
        retrieved_at = self.clock()
        for raw in rows[:params.get('limit', 3) if api == 'search_works' else 1]:
            try:
                item = normalize(raw, retrieved_at, request_url, params.get('include_abstract', True))
                if not params.get('from_date', '') <= item['published_at'] <= params.get('to_date', cutoff):
                    raise ValueError('out_of_period')
                if api == 'read_work' and item['source_id'] != work_id(params['work_id']):
                    raise ValueError('mismatched_id')
                if params.get('types') and item['type'] not in params['types']:
                    raise ValueError('mismatched_type')
                if 'language' in params and item['language'] != params['language']:
                    raise ValueError('mismatched_language')
                if 'open_access' in params and item['full_text_available'] is not params['open_access']:
                    raise ValueError('mismatched_open_access')
                if not item['abstract']:
                    warnings.append('abstract_not_returned:'+item['source_id'])
                items.append(item)
            except (ValueError, KeyError, TypeError, AttributeError):
                warnings.append('unusable_source_record')
        status = 'partial' if warnings else 'ok' if items else 'empty'
        return self._result(status, items=items, warnings=warnings)

    @staticmethod
    def _result(status, *, items=(), warnings=(), reason=None, attempted=True):
        return {'status': status, 'items': list(items), 'warnings': list(warnings), 'reason': reason,
                'next_cursor': None, 'cost': {'mock_units': 0, 'source_requests': int(attempted),
                                             'usd': None, 'billing_verified': False}}
