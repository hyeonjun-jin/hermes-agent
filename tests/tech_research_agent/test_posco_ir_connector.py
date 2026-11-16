"""Reviewed-catalog mechanics and real PDF parser against generated PDFs, never POSCO files."""
import copy
import hashlib
import io
import json

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, NumberObject

from tech_research_agent.application import ResearchApplication, principal
from tech_research_agent.config import runtime
from tech_research_agent.connectors.ir_catalog import IRCatalog
from tech_research_agent.connectors.ir_pdf import PDFParser, PDFRejected
from tech_research_agent.connectors.posco_ir import POSCOIRConnector
from tech_research_agent.real import PayloadPolicy, RealBlocked

SOURCE = 'https://www.posco-inc.com/hs91a1-front/app/ir/ir-material.html'
PDF_URL = 'https://www.posco-inc.com/approved-fixture.pdf'  # Never fetched outside MockTransport.


def pdf_bytes(pages=('text',), *, phrase='Synthetic hydrogen strategy plan. Not actual results.', encrypted=False):
    writer = PdfWriter()
    for mode in pages:
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        resources = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        content = b''
        if mode in {'text', 'visual'}:
            content = ('BT /F1 12 Tf 20 150 Td ('+phrase+') Tj ET').encode('ascii')
        if mode in {'image', 'visual'}:
            image = DecodedStreamObject(); image.set_data(b'\xff\x00\x00')
            image.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
                          NameObject('/Width'): NumberObject(1), NameObject('/Height'): NumberObject(1),
                          NameObject('/ColorSpace'): NameObject('/DeviceRGB'), NameObject('/BitsPerComponent'): NumberObject(8)})
            resources[NameObject('/XObject')] = DictionaryObject({NameObject('/Im0'): writer._add_object(image)})
            content += b' q 20 0 0 20 10 10 cm /Im0 Do Q'
        if mode == 'visual':
            content += b' 10 10 m 200 100 l S'
        stream = DecodedStreamObject(); stream.set_data(content)
        page[NameObject('/Resources')] = resources
        page[NameObject('/Contents')] = writer._add_object(stream)
    if encrypted:
        writer.encrypt('synthetic-password')
    output = io.BytesIO(); writer.write(output)
    return output.getvalue()


def entry(data, **updates):
    row = {'id': 'ir-dev-strategy', 'title': 'Synthetic hydrogen 수소환원제철 strategy',
           'published_at': '2026-02-01', 'material_type': 'strategy_presentation', 'language': 'ko',
           'source_url': SOURCE, 'local_path': 'sample.pdf', 'registered_at': '2026-10-01T00:00:00+00:00',
           'verified_at': '2026-10-02T00:00:00+00:00', 'version': 'v1', 'sha256': hashlib.sha256(data).hexdigest(),
           'classification': 'PUBLIC', 'approved': True,
           'allowed_users': ['researcher', 'strategy', 'finance'], 'allowed_projects': ['proj-H'],
           'keywords': ['hydrogen', '수소환원제철'], 'reporting_period': 'Synthetic FY label; dates not validated',
           'related_disclosures': ['20260301000001']}
    row.update(updates)
    return row


def setup(tmp_path, data=None, *, row=None, transport=None, enabled=True, downloads=False):
    data = data if data is not None else pdf_bytes()
    (tmp_path/'sample.pdf').write_bytes(data)
    connector = POSCOIRConnector(enabled=enabled, catalog=[row or entry(data)], local_root=tmp_path,
                                 allow_downloads=downloads, transport=transport, clock=lambda: '2026-11-16T00:00:00+00:00')
    _, _, adapter = runtime('strategy', 'H', 'quick', connectors={'posco_ir': connector})
    return connector, adapter


def call(api='search_materials', rp=None, op=None):
    return {'id': 'ir-test', 'app': 'posco_ir', 'api': api,
            'rp': rp if rp is not None else {'query': 'hydrogen'} if api == 'search_materials' else {'material_id': 'ir-dev-strategy'},
            'op': op or {}, 'after': []}


def test_search_real_pdf_pages_hash_and_cost(tmp_path):
    connector, adapter = setup(tmp_path, pdf_bytes(('text', 'text')))
    found = adapter.execute(call(op={'kind': 'strategy', 'language': 'ko', 'from_date': '2025-01-01',
                                    'to_date': '2026-09-30', 'sort': 'date_desc', 'limit': 2}))
    assert found['status'] == 'ok' and not found['items'][0]['hash_verified']
    assert found['cost']['source_requests'] == 0 and found['cost']['tool_units'] == 1
    assert adapter.context.seen == {'ir-dev-strategy'}
    read = adapter.execute(call('read_material'))
    item = read['items'][0]
    assert read['status'] == 'ok' and item['full_text_read'] and item['original_verified'] and item['hash_verified']
    assert item['read_pages'] == [1, 2] and item['unread_pages'] == []
    assert item['sha256'] == connector.catalog.get('ir-dev-strategy')['sha256']
    assert {span['page'] for span in item['spans']} == {1, 2}
    assert all(span['document_sha256'] == item['sha256'] and span['source_url'] == SOURCE for span in item['spans'])
    assert item['parser'] == 'pypdf' and len(item['extraction_sha256']) == 64
    assert read['cost']['local_reads'] == 1 and read['cost']['source_requests'] == 0
    assert adapter.context.spent == 2 and adapter.trace[-1]['executed']
    assert 'local_path' not in json.dumps(read) and str(tmp_path) not in json.dumps(read)


def test_catalog_search_language_type_relevance_and_limits(tmp_path):
    connector, adapter = setup(tmp_path)
    data = (tmp_path/'sample.pdf').read_bytes()
    connector.register_material(entry(data, id='ir-dev-earnings', material_type='earnings_release', language='en',
                                      title='Synthetic hydrogen hydrogen earnings', published_at='2026-03-01'))
    assert adapter.execute(call(op={'language': 'en', 'kind': 'earnings'}))['items'][0]['source_id'] == 'ir-dev-earnings'
    assert adapter.execute(call(op={'language': 'ko', 'kind': 'earnings'}))['status'] == 'empty'
    assert adapter.execute(call(op={'from_date': '2026-04-01'}))['status'] == 'empty'
    assert adapter.execute(call(rp={'query': 'NEVER_MATCH'}))['status'] == 'empty'
    connector.register_material(entry(data, id='ir-dev-more', published_at='2026-04-01'))
    result = adapter.execute(call(op={'limit': 1, 'sort': 'relevance'}))
    assert result['status'] == 'partial' and result['items'][0]['source_id'] == 'ir-dev-more'


@pytest.mark.parametrize('op', [{'sort': 'citations_desc'}, {'sort': 'unknown'}, {'language': 'ja'}, {'kind': 'market'},
                              {'limit': 11}, {'cursor': 'unissued'}, {'from_date': '2099-01-01'}, {'unknown': True}])
def test_unsupported_search_conditions_not_ignored(tmp_path, op):
    _, adapter = setup(tmp_path)
    result = adapter.execute(call(op=op))
    assert result['status'] == 'denied' and adapter.context.spent == 0


@pytest.mark.parametrize('field,value', [('source_url', 'https://evil.invalid/x'), ('source_url', 'http://www.posco-inc.com/x'),
    ('source_url', 'https://www.posco-inc.com.evil.invalid/x'), ('source_url', 'https://user:pass@www.posco-inc.com/x'),
    ('source_url', 'https://www.posco-inc.com:444/x'), ('sha256', 'bad'), ('approved', False),
    ('classification', 'INTERNAL'), ('language', 'ja'), ('material_type', 'unknown'),
    ('verified_at', '2099-01-01T00:00:00+00:00'), ('registered_at', '2026-10-04T00:00:00+00:00'),
    ('version', ''), ('id', 'H-IF01'), ('local_path', '../secret.pdf'), ('local_path', '/etc/secret.pdf')])
def test_catalog_registration_rejects_invalid_fields(field, value):
    data = pdf_bytes()
    with pytest.raises(ValueError):
        IRCatalog([entry(data, **{field: value})])


def test_duplicate_and_unversioned_hash_changes_rejected():
    row = entry(pdf_bytes())
    with pytest.raises(ValueError):
        IRCatalog([row, row])
    catalog = IRCatalog([row])
    with pytest.raises(ValueError):
        catalog.register({**row, 'sha256': '0'*64})


@pytest.mark.parametrize('modes,expected', [(('image',), 'image_or_graphic_only'), (('blank',), 'no_extractable_text'),
                                           (('visual',), 'partial_visual'), (('text', 'image'), 'image_or_graphic_only')])
def test_image_and_visual_pages_not_claimed_as_fully_read(tmp_path, modes, expected):
    _, adapter = setup(tmp_path, pdf_bytes(modes))
    adapter.execute(call())
    result = adapter.execute(call('read_material'))
    assert result['status'] == 'partial'
    item = result['items'][0]
    assert not item['full_text_read'] and not item['original_verified'] and not item['tables_charts_parsed']
    assert any(row['status'] == expected for row in item['page_statuses'])
    assert item['unread_pages']
    assert all(span['kind'] == 'ir_pdf_text' for span in item['spans'])


def test_explicit_page_subset_and_invalid_pages(tmp_path):
    _, adapter = setup(tmp_path, pdf_bytes(('text', 'text')))
    adapter.execute(call())
    result = adapter.execute(call('read_material', op={'pages': [2]}))
    assert result['status'] == 'partial' and result['items'][0]['read_pages'] == [2]
    assert result['items'][0]['not_requested_pages'] == [1]
    assert all(span['page'] == 2 for span in result['items'][0]['spans'])
    for pages in ([], [0], [-1], [1, 1], [True]):
        assert adapter.execute(call('read_material', op={'pages': pages}))['status'] == 'denied'
    assert adapter.execute(call('read_material', op={'pages': [3]}))['status'] == 'unavailable'


@pytest.mark.parametrize('body', [b'not pdf', b'%PDF-1.7\nbroken', pdf_bytes(encrypted=True), pdf_bytes(('blank',)*101)])
def test_bad_encrypted_and_excessive_page_pdfs_not_verified(tmp_path, body):
    _, adapter = setup(tmp_path, body)
    adapter.execute(call())
    result = adapter.execute(call('read_material'))
    assert result['status'] == 'unavailable' and not result['items']


def test_cache_rehashes_bytes_and_cannot_serve_changed_or_withdrawn_material(tmp_path):
    connector, adapter = setup(tmp_path)
    adapter.execute(call()); adapter.execute(call('read_material'))
    cached = adapter.execute(call('read_material'))
    assert cached['cost']['cache_hit'] and cached['cost']['local_reads'] == 1 and cached['cost']['parser_runs'] == 0
    (tmp_path/'sample.pdf').write_bytes(pdf_bytes(phrase='Changed content not approved.'))
    assert adapter.execute(call('read_material'))['status'] == 'unavailable' and not connector._cache
    connector.withdraw_material('ir-dev-strategy')
    denied = adapter.execute(call('read_material'))
    assert denied['status'] == 'denied' and not denied['items'] and not connector._cache
    assert adapter.execute(call())['status'] == 'empty'


def test_new_catalog_version_requires_fresh_search(tmp_path):
    connector, adapter = setup(tmp_path)
    adapter.execute(call()); adapter.execute(call('read_material'))
    data = pdf_bytes(phrase='New reviewed strategy plan.'); (tmp_path/'sample.pdf').write_bytes(data)
    connector.register_material(entry(data, version='v2'))
    assert not connector._cache and adapter.execute(call('read_material'))['status'] == 'denied'
    adapter.execute(call())
    result = adapter.execute(call('read_material'))
    assert result['status'] == 'ok' and result['items'][0]['version'] == 'v2'
    assert 'New reviewed strategy plan.' in result['items'][0]['spans'][0]['text']


def test_remote_exact_url_hash_and_redirect_protection(tmp_path):
    data = pdf_bytes(); seen = []
    def send(req):
        seen.append(req)
        return httpx.Response(200, content=data, headers={'content-type': 'application/pdf'})
    row = entry(data); del row['local_path']; row['pdf_url'] = PDF_URL
    connector, adapter = setup(tmp_path, data, row=row, transport=httpx.MockTransport(send), downloads=True)
    adapter.execute(call()); result = adapter.execute(call('read_material'))
    assert result['status'] == 'ok' and len(seen) == 1 and str(seen[0].url) == PDF_URL
    assert result['cost']['source_requests'] == 1 and result['cost']['local_reads'] == 0
    connector.client.close()
    connector.client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})))
    assert adapter.execute(call('read_material'))['status'] == 'unavailable'
    connector.allow_downloads = False
    assert adapter.execute(call('read_material'))['status'] == 'denied'


def test_pdf_url_and_location_registration():
    row = entry(pdf_bytes())
    with pytest.raises(ValueError):
        IRCatalog([{**row, 'pdf_url': PDF_URL}])
    del row['local_path']
    for url in ('https://evil.invalid/x.pdf', 'file:///etc/secrets.pdf', 'https://www.posco-inc.com/private.json',
                'https://www.posco-inc.com/x/../secret.pdf'):
        with pytest.raises(ValueError):
            IRCatalog([{**row, 'pdf_url': url}])


def test_confined_local_path_rejects_symlink(tmp_path):
    _, adapter = setup(tmp_path)
    original = (tmp_path/'sample.pdf').read_bytes()
    (tmp_path/'outside.pdf').write_bytes(original)
    (tmp_path/'sample.pdf').unlink(); (tmp_path/'sample.pdf').symlink_to(tmp_path/'outside.pdf')
    adapter.execute(call())
    assert adapter.execute(call('read_material'))['status'] == 'unavailable'


def test_local_file_size_limit_before_parser(tmp_path, monkeypatch):
    from tech_research_agent.connectors.ir_pdf_worker import MAX_PDF_BYTES
    connector, adapter = setup(tmp_path)
    adapter.execute(call())
    with (tmp_path/'sample.pdf').open('wb') as stream:
        stream.truncate(MAX_PDF_BYTES+1)
    def unexpected_parse(*args):
        pytest.fail('oversized file reached parser')
    monkeypatch.setattr(connector.parser, 'parse', unexpected_parse)
    result = adapter.execute(call('read_material'))
    assert result['status'] == 'unavailable' and not result['items']
    assert result['cost']['parser_runs'] == 0


@pytest.mark.parametrize('status,mime,body,expected', [
    (401, 'application/pdf', b'', 'denied'),
    (429, 'application/pdf', b'', 'unavailable'),
    (200, 'text/html', b'<html>not a PDF</html>', 'unavailable'),
    (200, 'application/pdf', b'changed unapproved bytes', 'unavailable'),
])
def test_remote_errors_never_become_empty_or_verified(tmp_path, status, mime, body, expected):
    data = pdf_bytes(); row = entry(data)
    del row['local_path']; row['pdf_url'] = PDF_URL
    connector, adapter = setup(tmp_path, data, row=row, downloads=True,
        transport=httpx.MockTransport(lambda request: httpx.Response(status, content=body, headers={'content-type': mime})))
    adapter.execute(call())
    result = adapter.execute(call('read_material'))
    assert result['status'] == expected and not result['items']
    assert result['cost']['source_requests'] == 1 and result['cost']['parser_runs'] == 0
    connector.close()


def test_disabled_connector_does_not_read_or_spend_budget(tmp_path):
    _, adapter = setup(tmp_path, enabled=False)
    result = adapter.execute(call())
    assert result['status'] == 'denied' and not result['items']
    assert result['cost']['source_requests'] == 0 and adapter.context.spent == 0


@pytest.mark.parametrize('condition', ['user', 'project', 'source', 'restricted', 'budget'])
def test_server_and_catalog_permissions(tmp_path, condition):
    _, adapter = setup(tmp_path)
    changes = {'user': ('user_id', 'other-user'), 'project': ('project_id', 'other-project'),
               'source': ('allowed_sources', {'openalex'}), 'restricted': ('classification', 'RESTRICTED'),
               'budget': ('spent', adapter.context.budget)}
    name, value = changes[condition]; setattr(adapter.context, name, value)
    result = adapter.execute(call())
    assert not result.get('items') and result['status'] in {'empty', 'denied'}


def test_unseen_id_private_terms_and_revocation(tmp_path):
    connector, adapter = setup(tmp_path)
    assert adapter.execute(call('read_material'))['status'] == 'denied'
    assert adapter.execute(call(rp={'query': 'proj-H'}))['status'] == 'denied'
    adapter.execute(call())
    row = connector.catalog.get('ir-dev-strategy'); row['allowed_users'] = []
    connector.register_material(row)
    assert adapter.execute(call('read_material'))['status'] == 'denied'


def test_revocation_during_pdf_parse_denies_and_invalidates(tmp_path, monkeypatch):
    connector, adapter = setup(tmp_path)
    adapter.execute(call())
    original = connector.parser.parse
    def parse(data, pages):
        parsed = original(data, pages)
        connector.withdraw_material('ir-dev-strategy')
        return parsed
    monkeypatch.setattr(connector.parser, 'parse', parse)
    result = adapter.execute(call('read_material'))
    assert result['status'] == 'denied' and not result['items'] and not connector._cache


def test_parser_timeout_missing_runtime_and_output_hash_fail_closed(tmp_path, monkeypatch):
    from tech_research_agent.connectors import ir_pdf
    import subprocess
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('pdf-worker', 12)
    monkeypatch.setattr(ir_pdf.subprocess, 'run', timeout)
    with pytest.raises(PDFRejected):
        PDFParser().parse(pdf_bytes(), None)
    monkeypatch.undo()
    connector, adapter = setup(tmp_path)
    adapter.execute(call())
    monkeypatch.setattr(connector.parser, 'parse', lambda *args: {'source_sha256': '0'*64, 'pages': []})
    assert adapter.execute(call('read_material'))['status'] == 'unavailable'


def test_hermes_ir_and_dart_evidence_are_separate(tmp_path):
    connector, _ = setup(tmp_path)
    app = ResearchApplication(tmp_path/'app', source_connectors={'posco_ir': connector})
    output = app.ask(principal('strategy'), 'strategy', '수소환원제철 비교 조사')
    assert [s['role'] for s in output['stages']] == ['research', 'analysis', 'verification']
    ir = [i for i in output['evidence'] if i['origin_app'] == 'posco_ir']
    dart = [i for i in output['evidence'] if i['origin_app'] == 'opendart']
    assert ir and dart and not ir[0]['synthetic'] and dart[0]['synthetic']
    assert ir[0]['disclosure_consistency'] == 'not_checked' and not ir[0]['reporting_period_verified']
    assert 'Synthetic hydrogen strategy plan.' in output['stages'][1]['raw_answer']
    assert 'IR의 계획' in output['answer'] and 'PUBLIC POSCO IR' in output['answer']
    assert any(e['plan']['id'].startswith('verification-') and e['plan']['api'] == 'read_material' for e in output['trace'])
    assert output['complete']
    with pytest.raises(PermissionError):
        app.ask(principal('strategy'), 'strategy', '수소환원제철 비교 조사', execution_mode='real')
    with pytest.raises(RealBlocked):
        PayloadPolicy(runtime('strategy', 'H', 'quick')[2].corpus).check({'messages': [{'role': 'tool', 'content': json.dumps({'items': ir})}]})


def test_no_text_ir_is_not_analysis_evidence_or_success(tmp_path):
    connector, _ = setup(tmp_path, pdf_bytes(('image',)))
    app = ResearchApplication(tmp_path/'app', source_connectors={'posco_ir': connector})
    result = app.ask(principal('strategy'), 'strategy', '수소환원제철 비교 조사')
    assert not result['complete'] and result['checks']['incomplete_reads']
    assert not any(i['origin_app'] == 'posco_ir' for i in result['evidence'])
