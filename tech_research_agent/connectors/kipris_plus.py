"""Domestic patent connector. Exact documented operation spelling; HTTPS only, no downloads."""
import json
import re
from datetime import UTC, date, datetime
from xml.etree import ElementTree as ET

import httpx

from .kipris_records import IPC, application_id, detail_item, search_item
from .kipris_xml import MAX_RESPONSE, parse, text
from .kipris_transport import CredentialTransport

BASE = 'https://plus.kipris.or.kr/kipo-api/kipi/patUtiModInfoSearchSevice/'
OPERATIONS = {'search_patents': 'getAdvancedSearch', 'read_patent': 'getBibliographyDetailInfoSearch'}


def result(status, *, items=(), warnings=(), reason=None, attempted=True):
    return {'status': status, 'items': list(items), 'warnings': list(warnings), 'reason': reason, 'next_cursor': None,
            'cost': {'mock_units': 0, 'source_requests': int(attempted), 'usd': None,
                     'billing_verified': False, 'quota_units': None, 'quota_verified': False}}


class KIPRISPlusConnector:
    def __init__(self, *, enabled=False, service_approved=False, api_key=None, transport=None, clock=None):
        self.enabled = enabled
        self.service_approved = service_approved
        self._api_key = api_key
        self.clock = clock or (lambda: datetime.now(UTC).isoformat())
        self.client = httpx.Client(transport=CredentialTransport(api_key, transport), timeout=15, follow_redirects=False, trust_env=False)

    def close(self):
        self.client.close()

    def execute(self, api, params, cutoff):
        if self.enabled is not True or self.service_approved is not True or not isinstance(self._api_key, str) or not self._api_key.strip():
            return result('denied', reason='connector_key_or_service_not_enabled', attempted=False)
        try:
            operation = OPERATIONS[api]
            query = self._query(api, params, cutoff)
        except (LookupError, ValueError, TypeError):
            return result('denied', reason='unsupported_kipris_parameters', attempted=False)
        data, error = self._download(operation, query)
        if error:
            return error
        try:
            root = parse(data)
            code = text(root, 'header/resultCode')
            if code != '00' or text(root, 'header/successYN') == 'N':
                return self._error(code)
            safe_url = str(httpx.URL(BASE+operation, params=query))
            if api == 'search_patents':
                output = self._search(root, params, cutoff, safe_url)
            else:
                nodes = root.findall('body/item')
                if len(nodes) != 1:
                    raise ValueError('missing_or_ambiguous_detail')
                item, warnings = detail_item(nodes[0], params, self.clock(), safe_url, cutoff)
                output = result('partial' if warnings else 'ok', items=[item], warnings=warnings)
            # No raw XML, request headers or error messages enter the audit trail.
            return json.loads(json.dumps(output, ensure_ascii=False).replace(json.dumps(self._api_key)[1:-1], '[REDACTED]'))
        except (ET.ParseError, LookupError, ValueError, TypeError, AttributeError):
            return result('unavailable', reason='invalid_or_unsupported_kipris_xml')

    def _query(self, api, params, cutoff):
        if api == 'read_patent':
            identifier = application_id(params['application_id'])
            if params['_patent']['id'] != identifier:
                raise ValueError('unconfirmed_patent')
            return {'applicationNumber': identifier}
        if params['jurisdiction'] != 'KR' or params.get('cursor') or params.get('sort', 'date_desc') != 'date_desc':
            raise ValueError('unsupported_jurisdiction_paging_or_sort')
        ipcs = params.get('ipc', [])
        if 'ipc' in params and (len(ipcs) != 1 or not IPC.fullmatch(ipcs[0])):
            raise ValueError('unsupported_ipc_filter')
        start = params.get('from_date', '1900-01-01')
        end = params.get('to_date', cutoff)
        if not start <= end <= cutoff or date.fromisoformat(end) > date.today():
            raise ValueError('invalid_period')
        query = {'word': params['query'], 'patent': 'true', 'utility': 'false',
                 'openDate': start.replace('-', '')+'~'+end.replace('-', ''),
                 'pageNo': 1, 'numOfRows': params.get('limit', 3), 'sortSpec': 'OPD', 'descSort': 'true'}
        if 'applicant' in params:
            if not params['applicant'].strip():
                raise ValueError('empty_applicant')
            query['applicant'] = params['applicant']
        if ipcs:
            query['ipcNumber'] = ipcs[0]
        return query

    def _download(self, operation, query):
        try:
            with self.client.stream('GET', BASE+operation, params=query) as response:
                if response.status_code in (401, 403):
                    return None, result('denied', reason='source_access_denied')
                if response.status_code != 200:
                    return None, result('unavailable', reason='source_http_'+str(response.status_code))
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE:
                        return None, result('unavailable', reason='source_response_limit')
                return bytes(body), None
        except httpx.HTTPError:
            return None, result('unavailable', reason='source_transport_error')

    def _search(self, root, params, cutoff, url):
        container = root.find('body/items')
        total = text(root, 'count/totalCount')
        if container is None or total is None or not total.isdigit() or text(root, 'count/pageNo') != '1':
            raise ValueError('missing_search_envelope')
        nodes = container.findall('item')
        items, warnings = [], []
        for node in nodes[:params.get('limit', 3)]:
            try:
                item = search_item(node, self.clock(), url, cutoff)
                if not params.get('from_date', '1900-01-01') <= item['open_date'] <= params.get('to_date', cutoff):
                    raise ValueError('publication_out_of_period')
                if params.get('applicant') and not params['applicant'].isdigit() and not any(params['applicant'].casefold() in name.casefold() for name in item['applicants']):
                    raise ValueError('applicant_filter_mismatch')
                if params.get('applicant', '').isdigit():
                    warnings.append('applicant_code_not_verifiable_from_names')
                if params.get('ipc') and not any(code.replace(' ', '').startswith(params['ipc'][0].replace(' ', '')) for code in item['ipc']):
                    raise ValueError('ipc_filter_mismatch')
                items.append(item)
            except (LookupError, ValueError, TypeError):
                warnings.append('unusable_patent_metadata')
        if len(nodes) > params.get('limit', 3) or int(total) > len(nodes):
            warnings.append('first_page_only')
        if int(total) != 0 and not nodes:
            warnings.append('inconsistent_search_count')
        return result('partial' if warnings else 'ok' if items else 'empty', items=items, warnings=warnings)

    @staticmethod
    def _error(code):
        if code is None or not re.fullmatch(r'[0-9]{2}', code):
            return result('unavailable', reason='invalid_source_status')
        # Only known access/expiry codes get denial semantics; other codes stay explicit errors.
        return result('denied' if code in {'20', '31'} else 'unavailable', reason='source_result_code_'+code)
