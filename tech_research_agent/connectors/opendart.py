"""Opt-in, single-request OpenDART operations over a verified server catalog."""
import json
import zipfile
import zlib
from datetime import UTC, datetime
from xml.etree import ElementTree as ET

import httpx

from .dart_catalog import CompanyCatalog
from .dart_documents import MAX_DOWNLOAD, extract_document
from .dart_financials import ACCOUNTS, financial_result
from .dart_records import api_error, base_item, receipt_date, result

BASE = 'https://opendart.fss.or.kr/api/'
REPORT_TYPES = {'material': {'pblntf_ty': 'B'}, 'annual': {'pblntf_detail_ty': 'A001'},
                'quarterly': {'pblntf_detail_ty': 'A003'}, 'all': {}}


class NoDTD(ET.TreeBuilder):
    def doctype(self, *args):
        raise ValueError('dtd_forbidden')


class OpenDARTConnector:
    def __init__(self, *, enabled=False, api_key=None, company_catalog=None, transport=None, clock=None):
        self.enabled = enabled
        self._api_key = api_key
        self.company_catalog = CompanyCatalog(company_catalog or {})
        self.clock = clock or (lambda: datetime.now(UTC).isoformat())
        self.client = httpx.Client(transport=transport, timeout=15, follow_redirects=False, trust_env=False)

    def close(self):
        self.client.close()

    def execute(self, api, params, cutoff):
        if not self.enabled or not isinstance(self._api_key, str) or len(self._api_key) != 40:
            return result('denied', reason='connector_disabled_or_key_missing', attempted=False)
        try:
            path, query, company = self._request(api, params)
        except (KeyError, ValueError, TypeError):
            return result('denied', reason='invalid_company_or_connector_parameters', attempted=False)
        data, error = self._download(path, query)
        if error:
            return error
        try:
            if api == 'read_disclosure':
                output = self._document(data, params, company, path)
            else:
                payload = json.loads(data)
                error = api_error(payload['status'], search=api != 'read_disclosure')
                if error:
                    return error
                rows = payload['list']
                if not isinstance(rows, list):
                    raise ValueError('invalid_rows')
                output = (self._list(rows, payload, params, cutoff, company, path) if api == 'list_disclosures' else
                          financial_result(rows, params, cutoff, company, self.clock(), BASE+path))
            # A server secret must not enter logs even if an upstream field unexpectedly echoes it.
            return json.loads(json.dumps(output, ensure_ascii=False).replace(self._api_key, '[REDACTED]'))
        except (LookupError, ValueError, TypeError, AttributeError, ET.ParseError, zipfile.BadZipFile,
                RuntimeError, OSError, NotImplementedError, zlib.error):
            return result('unavailable', reason='invalid_or_unsupported_source_payload')

    def _request(self, api, params):
        if api == 'read_disclosure':
            receipt_date(params['receipt_no'])
            known = params['_document']
            code = known['corp_code']
            if known['id'] != params['receipt_no']:
                raise ValueError('unconfirmed_receipt')
            return 'document.xml', {'rcept_no': params['receipt_no']}, self.company_catalog.entries[code]
        code = params['corp_code']
        company = self.company_catalog.entries[code]
        if api == 'list_disclosures':
            if params.get('cursor'):
                raise ValueError('cursor_not_supported')
            query = {'corp_code': code, 'bgn_de': params['from_date'].replace('-', ''),
                     'end_de': params['to_date'].replace('-', ''), 'sort': 'date', 'sort_mth': 'desc',
                     'page_no': 1, 'page_count': params.get('limit', 3),
                     **REPORT_TYPES[params.get('report_type', 'all')]}
            return 'list.json', query, company
        if api != 'read_financials' or not set(params.get('account_ids', ACCOUNTS)) <= ACCOUNTS.keys():
            raise ValueError('unsupported_financial_request')
        if int(params['bsns_year']) < 2015 or params.get('account_ids') == []:
            raise ValueError('unsupported_financial_year_or_accounts')
        return 'fnlttSinglAcntAll.json', {k: params[k] for k in ('corp_code', 'bsns_year', 'reprt_code', 'fs_div')}, company

    def _download(self, path, query):
        try:
            with self.client.stream('GET', BASE+path, params={**query, 'crtfc_key': self._api_key}) as response:
                if response.status_code in (401, 403):
                    return None, result('denied', reason='source_access_denied')
                if response.status_code != 200:
                    return None, result('unavailable', reason='source_http_'+str(response.status_code))
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    body.extend(chunk)
                    if len(body) > MAX_DOWNLOAD:
                        return None, result('unavailable', reason='source_download_limit')
                return bytes(body), None
        except httpx.HTTPError:
            return None, result('unavailable', reason='source_transport_error')

    def _list(self, rows, payload, params, cutoff, company, path):
        items, warnings = [], []
        for raw in rows[:params.get('limit', 3)]:
            try:
                item = base_item(raw['rcept_no'], company, params['corp_code'], self.clock(), BASE+path)
                published = datetime.strptime(raw['rcept_dt'], '%Y%m%d').date().isoformat()
                if raw['corp_code'] != params['corp_code'] or published != item['published_at']:
                    raise ValueError('disclosure_identity_mismatch')
                if not params['from_date'] <= published <= min(params['to_date'], cutoff):
                    raise ValueError('disclosure_period_mismatch')
                title = raw['report_nm']
                if not isinstance(title, str) or not title.strip():
                    raise ValueError('missing_title')
                if params.get('keyword') and not any(w in title.casefold() for w in params['keyword'].casefold().split()):
                    continue
                item.update(title=title, reported_company_name=raw.get('corp_name'),
                            stock_code=raw.get('stock_code'), corp_cls=raw.get('corp_cls'),
                            filer=raw.get('flr_nm'), remarks=raw.get('rm'), evidence_coverage='metadata_only',
                            spans=[{'id': 'metadata', 'kind': 'metadata', 'text': title}])
                items.append(item)
            except (KeyError, ValueError, TypeError):
                warnings.append('unusable_disclosure_record')
        if len(rows) > params.get('limit', 3):
            warnings.append('result_limit_reached')
        if int(payload.get('total_page', 1)) > 1:
            warnings.append('page_limit_reached')
        if params.get('keyword'):
            warnings.append('keyword_title_filter_on_first_page_only')
        return result('partial' if warnings else 'ok' if items else 'empty', items=items, warnings=warnings)

    def _document(self, data, params, company, path):
        if not data.startswith(b'PK'):
            if len(data) > 65536:
                raise ValueError('not_zip')
            payload = ET.fromstring(data, parser=ET.XMLParser(target=NoDTD()))
            return api_error(payload.findtext('status')) or result('unavailable', reason='missing_document_zip')
        spans, warnings = extract_document(data, params.get('section'))
        if not spans:
            return result('unavailable', reason='no_supported_document_text', warnings=warnings)
        known = params['_document']
        item = base_item(params['receipt_no'], company, known['corp_code'], self.clock(), BASE+path)
        item.update(title=known['title'], spans=spans, evidence_coverage='disclosure_body',
                    full_text_read=not warnings, original_verified=not warnings)
        return result('partial' if warnings else 'ok', items=[item], warnings=warnings)
