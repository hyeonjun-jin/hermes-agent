"""Fabricated company/filing fixtures only. Every source request uses MockTransport."""
import copy
import io
import json
import stat
import zipfile

import httpx
import pytest

from tech_research_agent.application import ResearchApplication, principal
from tech_research_agent.config import entity_catalog, runtime
from tech_research_agent.connectors.dart_catalog import CompanyCatalog
from tech_research_agent.connectors.opendart import OpenDARTConnector
from tech_research_agent.provider import ResearchProvider
from tech_research_agent.real import PayloadPolicy, RealBlocked

CODE = '12345678'  # Fictitious test identity, not a verified real company.
RECEIPT = '20260301000001'
KEY = 'fixture-key-'.ljust(40, 'x')


@pytest.fixture
def catalog():
    return {CODE: {'name': '합성 테스트 법인', 'verified': True, 'verified_at': '2026-01-01',
                   'verification_source': 'https://opendart.fss.or.kr/guide/main.do',
                   'allowed_users': ['researcher', 'strategy', 'finance'], 'allowed_projects': ['proj-H']}}


def archive(entries=None, compression=zipfile.ZIP_DEFLATED):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', compression=compression) as z:
        for name, body in (entries or {'report.xml': '<DOCUMENT><TITLE>합성 계획</TITLE><P>수소 기술 투자는 검토 중이다.</P></DOCUMENT>'}).items():
            z.writestr(name, body)
    return out.getvalue()


def listing():
    return {'status': '000', 'total_page': 1, 'list': [
        {'corp_code': CODE, 'corp_name': '합성 테스트 법인', 'stock_code': '999999',
         'report_nm': '수소환원제철 주요사항보고서', 'rcept_no': RECEIPT, 'rcept_dt': '20260301', 'corp_cls': 'Y'}]}


def financial(params):
    shared = {'rcept_no': RECEIPT, 'corp_code': CODE, 'bsns_year': params.get('bsns_year', '2025'),
              'reprt_code': params.get('reprt_code', '11011'), 'fs_div': params.get('fs_div', 'CFS'),
              'thstrm_nm': '합성 회계기간', 'currency': 'KRW'}
    return {'status': '000', 'list': [
        {**shared, 'account_id': 'dart_OperatingIncomeLoss', 'account_nm': '영업이익', 'sj_div': 'IS',
         'thstrm_amount': '1,234', 'thstrm_add_amount': '2,345'},
        {**shared, 'account_id': 'ifrs-full_CashFlowsFromUsedInInvestingActivities', 'account_nm': '투자활동현금흐름',
         'sj_div': 'CF', 'thstrm_amount': '-3,000', 'thstrm_add_amount': ''}]}


def setup(catalog, handler=None, enabled=True, key=KEY):
    requests = []
    def send(req):
        requests.append(req)
        if handler:
            return handler(req)
        if req.url.path.endswith('document.xml'):
            return httpx.Response(200, content=archive())
        payload = listing() if req.url.path.endswith('list.json') else financial(req.url.params)
        return httpx.Response(200, json=payload)
    connector = OpenDARTConnector(enabled=enabled, api_key=key, company_catalog=catalog,
                                  transport=httpx.MockTransport(send), clock=lambda: '2026-11-16T00:00:00+00:00')
    _, _, adapter = runtime('strategy', 'H', 'quick', connectors={'opendart': connector})
    return connector, adapter, requests


def call(api='list_disclosures', rp=None, op=None):
    defaults = {'list_disclosures': {'corp_code': CODE, 'from_date': '2025-10-01', 'to_date': '2026-09-30'},
                'read_disclosure': {'receipt_no': RECEIPT},
                'read_financials': {'corp_code': CODE, 'bsns_year': '2025', 'reprt_code': '11011', 'fs_div': 'CFS'}}
    return {'id': 'dart-test', 'app': 'opendart', 'api': api, 'rp': rp if rp is not None else defaults[api],
            'op': op or {}, 'after': []}


def test_search_read_and_provenance(catalog):
    _, adapter, requests = setup(catalog)
    searched = adapter.execute(call(op={'report_type': 'material', 'limit': 2}))
    assert searched['status'] == 'ok' and searched['items'][0]['source_id'] == RECEIPT
    query = requests[0].url.params
    assert dict(query) == {'corp_code': CODE, 'bgn_de': '20251001', 'end_de': '20260930',
                           'sort': 'date', 'sort_mth': 'desc', 'page_no': '1', 'page_count': '2', 'pblntf_ty': 'B', 'crtfc_key': KEY}
    assert not searched['items'][0]['original_verified']
    read = adapter.execute(call('read_disclosure'))
    item = read['items'][0]
    assert read['status'] == 'ok' and item['original_verified'] and item['full_text_read']
    assert '수소 기술 투자는 검토 중이다.' in item['spans'][0]['text']
    assert item['company'] == catalog[CODE]['name'] and item['corp_code'] == CODE
    assert item['published_at'] == '2026-03-01' and item['retrieved_at'] == '2026-11-16T00:00:00+00:00'
    assert not item['synthetic'] and item['content_trust'] == 'untrusted_external_data'
    assert 'crtfc_key' not in json.dumps(adapter.trace) and KEY not in json.dumps(adapter.trace)
    assert adapter.context.spent == 2
    assert read['cost']['source_requests'] == 1 and read['cost']['quota_units'] is None
    assert not read['cost']['quota_verified'] and read['cost']['usd'] is None


@pytest.mark.parametrize('kind,expected', [('annual', {'pblntf_detail_ty': 'A001'}),
                                         ('quarterly', {'pblntf_detail_ty': 'A003'}), ('all', {})])
def test_report_types(catalog, kind, expected):
    _, adapter, requests = setup(catalog)
    adapter.execute(call(op={'report_type': kind}))
    assert {k: v for k, v in requests[0].url.params.items() if k.startswith('pblntf')} == expected


def test_keyword_filter_and_page_limit_are_not_global_absence(catalog):
    payload = listing(); payload['total_page'] = 20
    _, adapter, requests = setup(catalog, lambda r: httpx.Response(200, json=payload))
    result = adapter.execute(call(op={'keyword': 'NEVER_MATCH_FIXTURE', 'limit': 1}))
    assert result['status'] == 'partial' and not result['items']
    assert 'page_limit_reached' in result['warnings'] and len(requests) == 1
    assert 'keyword' not in requests[0].url.params


@pytest.mark.parametrize('basis,report', [('CFS', '11011'), ('OFS', '11012'), ('CFS', '11013'), ('OFS', '11014')])
def test_financial_account_mapping_and_period_basis(catalog, basis, report):
    _, adapter, requests = setup(catalog)
    request = call('read_financials'); request['rp'].update(fs_div=basis, reprt_code=report)
    result = adapter.execute(request)
    assert result['status'] == 'ok'
    rows = {row['account_id']: row for row in result['rows']}
    profit = rows['operating_profit']; cash = rows['cash_flow_investing']
    assert profit['official_account_id'] == 'dart_OperatingIncomeLoss' and profit['amount'] == '1234'
    assert profit['amount_raw'] == '1,234' and profit['cumulative_amount'] == '2345'
    assert cash['amount'] == '-3000' and cash['cumulative_amount'] is None
    assert profit['fs_div'] == basis and profit['reprt_code'] == report and profit['currency'] == 'KRW'
    assert profit['current_amount_scope'] == ('as_reported' if report == '11011' else 'three_months')
    assert profit['period_start'] is None and not profit['period_dates_verified']
    assert profit['technology_profitability'] == 'not_established'
    assert result['items'][0]['source_id'].startswith('dart-fin:'+CODE+':2025:'+report+':'+basis)
    assert result['items'][0]['original_verified'] and not result['items'][0]['full_text_read']
    assert requests[0].url.path.endswith('fnlttSinglAcntAll.json')
    assert requests[0].url.params['fs_div'] == basis
    assert RECEIPT not in adapter.context.seen  # Financial rows do not authorize arbitrary document download.


@pytest.mark.parametrize('field,value', [('corp_code', '87654321'), ('bsns_year', '2024'),
                                       ('reprt_code', '11012'), ('fs_div', 'OFS'), ('rcept_no', '20990101000001'),
                                       ('currency', None), ('thstrm_amount', 'invented')])
def test_invalid_financial_rows_not_verified(catalog, field, value):
    payload = financial({}); payload['list'][0][field] = value
    _, adapter, _ = setup(catalog, lambda r: httpx.Response(200, json=payload))
    result = adapter.execute(call('read_financials'))
    assert result['status'] == 'partial' and not any(row['account_id'] == 'operating_profit' for row in result['rows'])
    assert not result['items'][0]['original_verified']


def test_unknown_custom_ids_and_missing_amount_are_not_guessed(catalog):
    payload = financial({}); payload['list'][0]['account_id'] = '-표준계정코드 미사용-'
    payload['list'][1]['thstrm_amount'] = '-'
    _, adapter, _ = setup(catalog, lambda r: httpx.Response(200, json=payload))
    result = adapter.execute(call('read_financials'))
    assert result['status'] == 'partial' and result['rows'][0]['amount'] is None
    assert 'requested_accounts_incomplete' in result['warnings']


@pytest.mark.parametrize('api,rp,op', [
    ('list_disclosures', {'corp_code': '00000001', 'from_date': '2025-10-01', 'to_date': '2026-09-30'}, {}),
    ('list_disclosures', {'corp_code': '00000002', 'from_date': '2025-10-01', 'to_date': '2026-09-30'}, {}),
    ('list_disclosures', {'corp_code': '87654321', 'from_date': '2025-10-01', 'to_date': '2026-09-30'}, {}),
    ('list_disclosures', None, {'cursor': '2'}), ('list_disclosures', None, {'limit': 11}),
    ('read_disclosure', {'receipt_no': RECEIPT}, {}),
    ('read_disclosure', {'receipt_no': 'https://private.invalid/file'}, {}),
    ('read_financials', None, {'account_ids': ['fake_roi']}),
])
def test_unapproved_parameters_never_send(catalog, api, rp, op):
    _, adapter, requests = setup(catalog)
    result = adapter.execute(call(api, rp, op))
    assert result['status'] == 'denied' and not requests and adapter.context.spent == 0


@pytest.mark.parametrize('code,expected', [('013', 'empty'), ('010', 'denied'), ('011', 'denied'),
                                         ('012', 'denied'), ('020', 'unavailable'), ('800', 'unavailable')])
def test_api_statuses_are_not_conflated(catalog, code, expected):
    _, adapter, requests = setup(catalog, lambda r: httpx.Response(200, json={'status': code, 'message': KEY}))
    result = adapter.execute(call())
    assert result['status'] == expected and len(requests) == 1 and adapter.context.spent == 1
    assert KEY not in json.dumps(adapter.trace)


@pytest.mark.parametrize('status', [302, 404, 429, 500])
def test_http_failures_do_not_redirect_or_retry(catalog, status):
    _, adapter, requests = setup(catalog, lambda r: httpx.Response(status, text=KEY, headers={'location': 'http://127.0.0.1/private'}))
    assert adapter.execute(call())['status'] == 'unavailable' and len(requests) == 1
    assert KEY not in json.dumps(adapter.trace)


def test_auth_xml_and_transport_failures(catalog):
    _, adapter, requests = setup(catalog)
    adapter.execute(call())
    def fail(req):
        return httpx.Response(200, content=b'<result><status>020</status></result>')
    adapter.connectors['opendart'].client.close()
    adapter.connectors['opendart'].client = httpx.Client(transport=httpx.MockTransport(fail))
    assert adapter.execute(call('read_disclosure'))['reason'] == 'source_quota_exceeded'
    def timeout(req):
        raise httpx.ReadTimeout(KEY, request=req)
    adapter.connectors['opendart'].client = httpx.Client(transport=httpx.MockTransport(timeout))
    assert adapter.execute(call())['status'] == 'unavailable'
    assert KEY not in json.dumps(adapter.trace) and len(requests) == 1


@pytest.mark.parametrize('condition', ['project', 'user', 'source', 'private', 'restricted', 'budget', 'catalog_user'])
def test_policy_and_catalog_permissions(catalog, condition):
    _, adapter, requests = setup(catalog)
    ctx = adapter.context
    values = {'project': ('allowed_projects', set()), 'user': ('user_id', ''),
              'source': ('allowed_sources', {'openalex'}), 'private': ('private_terms', {'secret-keyword'}),
              'restricted': ('classification', 'RESTRICTED'), 'budget': ('spent', ctx.budget),
              'catalog_user': ('user_id', 'other-user')}
    key, value = values[condition]; setattr(ctx, key, value)
    request = call(op={'keyword': 'secret-keyword'} if condition == 'private' else {})
    result = adapter.execute(request)
    assert result['status'] == 'denied' and not requests and not result.get('items')


def test_search_then_company_permission_revocation(catalog):
    connector, adapter, requests = setup(catalog)
    adapter.execute(call())
    connector.company_catalog.entries[CODE]['allowed_users'] = []
    result = adapter.execute(call('read_disclosure'))
    assert result['status'] == 'denied' and not result.get('items') and len(requests) == 1


def test_catalog_and_entity_context_are_server_owned(catalog):
    _, adapter, _ = setup(catalog)
    assert adapter.context.entity_topics == {CODE: None}
    assert entity_catalog(adapter)[0]['company_name'] == '합성 테스트 법인'
    assert not entity_catalog(adapter)[0]['synthetic']
    for code in ('00000001', '00000002'):
        with pytest.raises(ValueError):
            CompanyCatalog({code: catalog[CODE]})
    bad = copy.deepcopy(catalog); bad[CODE]['verified'] = False
    with pytest.raises(ValueError):
        CompanyCatalog(bad)


def test_unverified_or_partial_body_never_completes(catalog, tmp_path):
    def send(req):
        return httpx.Response(200, content=archive({'body.xml': '<DOCUMENT><P>공개 합성 계획</P></DOCUMENT>',
                                                   'attachment.pdf': b'not parsed'})) if req.url.path.endswith('document.xml') else httpx.Response(200, json=listing())
    connector, _, _ = setup(catalog, send)
    app = ResearchApplication(tmp_path, source_connectors={'opendart': connector})
    result = app.ask(principal('strategy'), 'strategy', '수소환원제철 비교 조사')
    assert result['checks']['unverified_original_ids'] == [RECEIPT] and not result['complete']


def test_hermes_strategy_workflow_and_real_egress_gate(catalog, tmp_path):
    connector, _, requests = setup(catalog)
    app = ResearchApplication(tmp_path, source_connectors={'opendart': connector})
    output = app.ask(principal('strategy'), 'strategy', '수소환원제철 비교 조사')
    assert [s['role'] for s in output['stages']] == ['research', 'analysis', 'verification']
    assert len([r for r in requests if r.url.path.endswith('document.xml')]) == 2
    assert all(r.url.params.get('corp_code') != '00000001' for r in requests)
    assert '수소 기술 투자는 검토 중이다.' in output['stages'][1]['raw_answer']
    assert 'PUBLIC OpenDART' in output['answer'] and output['checks']['verification_read']
    policy = PayloadPolicy(runtime('strategy', 'H', 'quick')[2].corpus)
    with pytest.raises(RealBlocked):
        policy.check({'messages': [{'role': 'tool', 'content': json.dumps({'items': output['evidence']})}]})
    with pytest.raises(PermissionError):
        app.ask(principal('strategy'), 'strategy', '수소환원제철 비교 조사', execution_mode='real')
    denied = json.loads(ResearchProvider('analysis', runtime('strategy', 'H', 'quick')[2], {}).handle_tool_call('opendart__read_financials', {'rp': {}, 'op': {}}))
    assert denied['status'] == 'denied'


def test_hermes_finance_requeries_same_financial_basis(catalog, tmp_path):
    connector, _, requests = setup(catalog)
    app = ResearchApplication(tmp_path, source_connectors={'opendart': connector})
    result = app.ask(principal('finance'), 'finance', '수소환원제철 재무 중심 조사')
    financial_requests = [r for r in requests if r.url.path.endswith('fnlttSinglAcntAll.json')]
    assert len(financial_requests) == 2
    assert all(r.url.params['fs_div'] == 'CFS' and r.url.params['corp_code'] == CODE for r in financial_requests)
    assert any(row['scope'] == 'company_consolidated' for item in result['evidence'] for row in item.get('rows', []))


@pytest.mark.parametrize('body', [b'PKbroken',
    archive({'../secret.xml': '<DOCUMENT/>'}), archive({'/tmp/secret.xml': '<DOCUMENT/>'}),
    archive({'folder\\secret.xml': '<DOCUMENT/>'}), archive({'x.xml': '<DOCUMENT>broken'}),
    archive({'x.xml': '<!DOCTYPE DOCUMENT [<!ENTITY x "boom">]><DOCUMENT>&x;</DOCUMENT>'}),
    archive({'x.xml': '<!DOCTYPE DOCUMENT SYSTEM "file:///etc/passwd"><DOCUMENT/>'}),
    archive({'x.xml': ('<!DOCTYPE DOCUMENT [<!ENTITY x "boom">]><DOCUMENT>&x;</DOCUMENT>').encode('utf-16')}),
    archive({'report.pdf': b'no parser'}), archive({'a.xml': '<DOCUMENT>'+'a'*100000+'</DOCUMENT>'})])
def test_unsafe_zip_and_xml_cannot_be_verified(catalog, body):
    _, adapter, _ = setup(catalog, lambda req: httpx.Response(200, json=listing()) if req.url.path.endswith('list.json') else httpx.Response(200, content=body))
    adapter.execute(call())
    result = adapter.execute(call('read_disclosure'))
    assert result['status'] in {'partial', 'unavailable'} and not result.get('items')


@pytest.mark.parametrize('limit,value', [('MAX_FILES', 1), ('MAX_FILE', 10), ('MAX_EXPANDED', 20), ('MAX_RATIO', 1)])
def test_zip_expansion_limits(catalog, monkeypatch, limit, value):
    from tech_research_agent.connectors import dart_documents
    monkeypatch.setattr(dart_documents, limit, value)
    body = archive({'a.xml': '<DOCUMENT>first body contents</DOCUMENT>', 'b.xml': '<DOCUMENT>second body contents</DOCUMENT>'})
    _, adapter, _ = setup(catalog, lambda req: httpx.Response(200, json=listing()) if req.url.path.endswith('list.json') else httpx.Response(200, content=body))
    adapter.execute(call())
    assert adapter.execute(call('read_disclosure'))['status'] == 'unavailable'


def test_symlink_and_download_limit(catalog, monkeypatch):
    info = zipfile.ZipInfo('link.xml'); info.create_system = 3; info.external_attr = (stat.S_IFLNK | 0o777) << 16
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr(info, '/etc/passwd')
    _, adapter, _ = setup(catalog, lambda req: httpx.Response(200, json=listing()) if req.url.path.endswith('list.json') else httpx.Response(200, content=out.getvalue()))
    adapter.execute(call())
    assert adapter.execute(call('read_disclosure'))['status'] == 'unavailable'
    from tech_research_agent.connectors import opendart
    monkeypatch.setattr(opendart, 'MAX_DOWNLOAD', 10)
    assert adapter.execute(call())['reason'] == 'source_download_limit'


def test_missing_key_and_disabled_never_send(catalog):
    for enabled, key in [(False, KEY), (True, None)]:
        _, adapter, requests = setup(catalog, enabled=enabled, key=key)
        result = adapter.execute(call())
        assert result['status'] == 'denied' and not requests


def test_partial_section_and_unsupported_attachment(catalog):
    body = archive({'body.xml': '<DOCUMENT><P>계획 내용</P></DOCUMENT>', 'extra.pdf': b'unread'})
    _, adapter, _ = setup(catalog, lambda req: httpx.Response(200, json=listing()) if req.url.path.endswith('list.json') else httpx.Response(200, content=body))
    adapter.execute(call())
    result = adapter.execute(call('read_disclosure', op={'section': '계획'}))
    assert result['status'] == 'partial' and result['items'][0]['spans']
    assert not result['items'][0]['original_verified'] and not result['items'][0]['full_text_read']
    unknown_encoding = b'<?xml version="1.0" encoding="invalid-encoding"?><DOCUMENT/>'
    _, broken, _ = setup(catalog, lambda req: httpx.Response(200, json=listing()) if req.url.path.endswith('list.json') else
                         httpx.Response(200, content=archive({'bad.xml': unknown_encoding})))
    broken.execute(call())
    assert broken.execute(call('read_disclosure'))['status'] == 'unavailable'


def test_revocation_during_financial_io_clears_rows(catalog):
    connector, adapter, _ = setup(catalog)
    def revoke(req):
        connector.company_catalog.entries[CODE]['allowed_users'] = []
        return httpx.Response(200, json=financial(req.url.params))
    connector.client.close()
    connector.client = httpx.Client(transport=httpx.MockTransport(revoke))
    result = adapter.execute(call('read_financials'))
    assert result['status'] == 'denied' and result['items'] == [] and result['rows'] == []
    assert adapter.context.spent == 1


def test_empty_financials_and_ambiguous_filings(catalog):
    for payload in ({'status': '013'}, {'status': '000', 'list': []}):
        _, adapter, _ = setup(catalog, lambda r: httpx.Response(200, json=payload))
        result = adapter.execute(call('read_financials'))
        assert result['status'] == 'empty' and not result['items']
    payload = financial({}); extra = copy.deepcopy(payload['list'][0]); extra['rcept_no'] = '20260401000001'
    payload['list'].append(extra)
    _, adapter, _ = setup(catalog, lambda r: httpx.Response(200, json=payload))
    result = adapter.execute(call('read_financials'))
    assert result['status'] == 'partial' and len(result['items']) == 2
    assert 'multiple_financial_filings' in result['warnings']


def test_bad_json_wrong_company_and_secret_echo_are_safe(catalog):
    payload = listing(); payload['list'][0]['corp_code'] = '87654321'
    _, adapter, _ = setup(catalog, lambda r: httpx.Response(200, json=payload))
    assert adapter.execute(call())['items'] == []
    for content in (b'not json', b'[]', json.dumps({'status': KEY}).encode()):
        _, adapter, _ = setup(catalog, lambda r: httpx.Response(200, content=content))
        assert adapter.execute(call())['status'] == 'unavailable'
        assert KEY not in json.dumps(adapter.trace)


def test_financial_account_subsets_keep_distinct_evidence(catalog):
    _, adapter, _ = setup(catalog)
    first = adapter.execute(call('read_financials', op={'account_ids': ['operating_profit']}))
    second = adapter.execute(call('read_financials', op={'account_ids': ['cash_flow_investing']}))
    assert first['items'][0]['source_id'] != second['items'][0]['source_id']
    assert first['items'][0]['source_id'] in adapter.corpus and second['items'][0]['source_id'] in adapter.corpus


def test_failed_disclosure_read_is_incomplete_even_with_other_evidence(catalog, tmp_path):
    def send(req):
        return (httpx.Response(500) if req.url.path.endswith('document.xml') else
                httpx.Response(200, json=listing()))
    connector, _, _ = setup(catalog, send)
    app = ResearchApplication(tmp_path, source_connectors={'opendart': connector})
    result = app.ask(principal('strategy'), 'strategy', '수소환원제철 비교 조사')
    assert result['evidence']  # Existing offline IR evidence is still available.
    assert not result['complete'] and result['checks']['source_failures'][0]['api'] == 'read_disclosure'
    assert result['checks']['source_failures'][0]['status'] == 'unavailable'
    assert '조회 범위·실행 제한' in result['answer'] and '조회 실패' in result['answer']
