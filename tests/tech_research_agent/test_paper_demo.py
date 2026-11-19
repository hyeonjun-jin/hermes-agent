"""Exercise the real sender boundary through Stubs; never call OpenAI or an external source."""
import copy
import json
from pathlib import Path

import httpx
import pytest

from tech_research_agent import paper_demo as demo
from tech_research_agent.application import ResearchApplication, principal
from tech_research_agent.paper_demo_approval import PaperDemoApproval, PROFILES_PUBLIC, QUESTION
from tech_research_agent.paper_demo_real import PaperDemoAdapter
from tech_research_agent.real import RealAdapter, RealBlocked
from tests.tech_research_agent.paper_demo_fixtures import approval_record, connector, DemoStub


@pytest.fixture
def harness(tmp_path, monkeypatch):
    sender, sources = DemoStub(), []
    approval = tmp_path/'test-approval.json'; approval.write_text(json.dumps(approval_record()))
    monkeypatch.setattr(RealAdapter, '_network_send', lambda self, body: sender(body))
    monkeypatch.setattr(demo, 'OpenAlexConnector', lambda **kwargs: connector(sources))
    monkeypatch.setattr('tech_research_agent.real.check_real_network', lambda env: 'stub-runtime')
    monkeypatch.setattr('tech_research_agent.paper_demo_real.check_real_network', lambda env: 'stub-runtime')
    monkeypatch.setenv('PERSONA_API_KEY', 'fabricated-invalid-openai-key')
    monkeypatch.setenv('OPENALEX_API_KEY', 'fabricated-invalid-openalex-key')
    monkeypatch.setenv('PERSONA_BASE_URL', 'https://api.openai.com/v1')
    monkeypatch.setenv('PERSONA_MODEL', 'gpt-4o-mini')
    return approval, sender, sources


def run(root, approval, profile='A', **kwargs):
    return demo.run_demo(root, profile, QUESTION, enabled=True, consent=True, approval_path=approval, **kwargs)


@pytest.mark.parametrize('enabled,consent', [(False, True), (True, False), ('true', True), (True, 'yes')])
def test_default_or_no_consent_has_no_state_or_network(tmp_path, harness, enabled, consent):
    path, sender, sources = harness
    with pytest.raises(RealBlocked):
        demo.run_demo(tmp_path, 'A', QUESTION, enabled=enabled, consent=consent, approval_path=path)
    assert not sender.requests and not sources and not (tmp_path/'.technical-paper-demo').exists()


@pytest.mark.parametrize('field,value', [('actual_execution_approved', False), ('source_access_approved', False),
    ('public_processing_approved', False), ('model_identity_reviewed', False), ('scope_sha256', '0'*64),
    ('max_reserved_usd', 0), ('max_new_calls', 13), ('expires_at', '2020-01-02T00:00:00+00:00')])
def test_observed_model_does_not_approve_execution(tmp_path, harness, field, value):
    path, sender, sources = harness
    record = approval_record(); record[field] = value; path.write_text(json.dumps(record))
    with pytest.raises((RealBlocked, ValueError)):
        run(tmp_path, path)
    assert not sender.requests and not sources and not (tmp_path/'.technical-paper-demo').exists()


def test_hermes_three_roles_and_three_observed_papers_on_both_profiles(tmp_path, harness):
    path, sender, sources = harness
    ledger = tmp_path/'usage.json'; ledger.write_text('OPERATING_LEDGER_SENTINEL')
    database = tmp_path/'memory.sqlite'; database.write_bytes(b'PRIVATE_OPERATING_PERSONA')
    results = {}
    for profile in ('A', 'B'):
        sender.counts = dict.fromkeys(sender.counts, 0)
        results[profile] = run(tmp_path, path, profile)
        result = results[profile]
        assert result['complete'], result['real_audit']
        assert sender.counts == {'research': 3, 'analysis': 1, 'verification': 2}
        assert result['mode'] == 'public_paper_demo' and len(result['paper_recommendations']['items']) == 3
        assert all(item['synthetic'] is False and item['full_text_read'] is False for item in result['evidence'])
        assert 'SYNTHETIC fixtures / approved_public' not in result['answer']
        assert result['profile'] == PROFILES_PUBLIC[profile] and result['history_used'] == []
        assert result['real_audit']['this_run_usage']['estimated_usd'] == pytest.approx(0.000027)
    assert results['A']['paper_recommendations']['items'][0]['source_id'] == 'W123'
    assert results['B']['paper_recommendations']['items'][0]['source_id'] == 'W456'
    assert len(sender.requests) == 12 and len(sources) == 14
    # Full prepared first request: only the reviewed Profile interests differ.
    normalized = []
    for body in (sender.requests[0], sender.requests[6]):
        body = copy.deepcopy(body)
        prefix, tail = body['messages'][0]['content'].split('TECH_CONTEXT=', 1)
        ctx = json.JSONDecoder().raw_decode(tail)[0]
        ctx['profile']['interests'] = []
        body['messages'][0]['content'] = (prefix, ctx)
        normalized.append(body)
    assert normalized[0] == normalized[1]
    for body in sender.requests:
        ctx = json.JSONDecoder().raw_decode(body['messages'][0]['content'].split('TECH_CONTEXT=', 1)[1])[0]
        assert ctx['profile'] in PROFILES_PUBLIC.values()
        assert ctx['environment']['allowed_sources'] == ['openalex'] and not ctx['entity_catalog']
        assert not ctx['history'] and not ctx['approved_preferences']
        assert body['model'] == 'gpt-4o-mini' and body['max_tokens'] == 512 and not body['stream']
        assert all(t['function']['name'].startswith('openalex__') for t in body.get('tools', []))
        assert 'PRIVATE_OPERATING_PERSONA' not in json.dumps(body)
    actual = tmp_path/'.technical-paper-demo'/'usage.json'
    saved = json.loads(actual.read_text()); before = actual.read_bytes()
    assert len(saved['calls']) == 12 and saved['failed'] is False
    assert all(c['payload_sha256'] and c['transport_invoked'] for c in saved['calls'])
    with pytest.raises(RealBlocked): run(tmp_path, path)
    assert actual.read_bytes() == before and ledger.read_text() == 'OPERATING_LEDGER_SENTINEL'
    assert database.read_bytes() == b'PRIVATE_OPERATING_PERSONA'
    assert len(list(actual.parent.glob('report-*.json'))) == 2
    # A late Hermes log writer may recreate a scratch directory; investigation databases are removed.
    assert not list(actual.parent.glob('isolated-*/memory.sqlite'))


@pytest.mark.parametrize('failure', ['http', 'model', 'usage', 'source', 'revoked'])
def test_first_failure_stops_without_fallback_and_preserves_usage(tmp_path, harness, monkeypatch, failure):
    path, sender, sources = harness
    def send(adapter, body):
        status, data = sender(body)
        if failure == 'http': return 500, {}
        if failure == 'model': data['model'] = 'gpt-4o-mini-2099-01-01'
        if failure == 'usage': data.pop('usage')
        if failure == 'revoked':
            record = approval_record(); record['actual_execution_approved'] = False; path.write_text(json.dumps(record))
        return status, data
    monkeypatch.setattr(RealAdapter, '_network_send', send)
    if failure == 'source':
        monkeypatch.setattr(demo, 'OpenAlexConnector', lambda **kwargs: connector(sources, handler=lambda req: httpx.Response(503)))
    try:
        result = run(tmp_path, path)
        assert not result['complete']
    except RealBlocked:
        assert failure == 'revoked'
    assert len(sender.requests) == 1
    actual = tmp_path/'.technical-paper-demo'/'usage.json'; before = actual.read_bytes()
    with pytest.raises(RealBlocked): run(tmp_path, path)
    assert actual.read_bytes() == before and len(sender.requests) == 1
    if failure == 'model': assert json.loads(before)['calls'][0]['usage']['prompt_tokens'] == 10


def test_single_question_approval_and_cost_cannot_be_expanded_by_restart(tmp_path, harness):
    path, sender, _ = harness
    record = approval_record(); record['max_new_calls'] = 6; path.write_text(json.dumps(record))
    assert run(tmp_path, path)['complete']
    with pytest.raises(RealBlocked): run(tmp_path, path, 'B')
    record['max_new_calls'] = 12; path.write_text(json.dumps(record))
    with pytest.raises(RealBlocked): run(tmp_path, path, 'B')
    assert len(sender.requests) == 6


@pytest.mark.parametrize('key', ['PERSONA_API_KEY', 'OPENALEX_API_KEY', 'PERSONA_MODEL', 'PERSONA_BASE_URL'])
def test_missing_connection_settings_reserve_nothing(tmp_path, harness, monkeypatch, key):
    path, sender, sources = harness
    monkeypatch.delenv(key)
    with pytest.raises(RealBlocked): run(tmp_path, path)
    assert not sender.requests and not sources and not (tmp_path/'.technical-paper-demo').exists()


def test_inadequate_cost_does_not_create_ledger(tmp_path, harness):
    path, sender, _ = harness
    record = approval_record(); record['max_reserved_usd'] = 0.001; path.write_text(json.dumps(record))
    with pytest.raises(RealBlocked): run(tmp_path, path)
    assert not sender.requests and not (tmp_path/'.technical-paper-demo'/'usage.json').exists()


@pytest.mark.parametrize('kind', ['question', 'profile', 'memory'])
def test_nonreviewed_inputs_and_private_memory_never_sent(tmp_path, harness, monkeypatch, kind):
    path, sender, sources = harness
    if kind == 'memory':
        original = ResearchApplication.__init__
        def initialize(app, *args, **kwargs):
            original(app, *args, **kwargs)
            app.store.append(principal('researcher'), 'researcher', 'test', '[project=proj-H] '+QUESTION, 'PRIVATE_MEMORY')
        monkeypatch.setattr(ResearchApplication, '__init__', initialize)
    with pytest.raises(RealBlocked):
        demo.run_demo(tmp_path, 'PRIVATE' if kind == 'profile' else 'A', 'PRIVATE QUESTION' if kind == 'question' else QUESTION,
                      enabled=True, consent=True, approval_path=path)
    assert not sender.requests and not sources


def test_response_receipts_cannot_be_replaced_before_send(tmp_path, harness, monkeypatch):
    path, sender, _ = harness
    original = PaperDemoAdapter.prepare
    def prepare(adapter, source):
        policy = original(adapter, source)
        def tamper(body):
            for message in body['messages']:
                if message['role'] == 'tool':
                    # Mutate the live receipt set, not the observer's defensive request copy.
                    policy.receipts.clear()
        adapter.request_observer = tamper
        return policy
    monkeypatch.setattr(PaperDemoAdapter, 'prepare', prepare)
    assert not run(tmp_path, path)['complete']
    assert len(sender.requests) == 1


def test_known_empty_provider_annotations_only():
    from tech_research_agent.paper_demo_policy import PaperDemoPolicy
    message = {'role': 'assistant', 'content': '검증 데이터'}
    assert PaperDemoPolicy.assistant_signature({**message, 'annotations': []}) == PaperDemoPolicy.assistant_signature(message)
    with pytest.raises(RealBlocked):
        PaperDemoPolicy.assistant_signature({**message, 'annotations': [{'type': 'url_citation'}]})


def test_changed_public_fixture_does_not_inherit_previous_review(tmp_path, harness, monkeypatch):
    path, sender, sources = harness
    monkeypatch.setitem(PROFILES_PUBLIC, 'A', {**PROFILES_PUBLIC['A'], 'interests': ['PRIVATE_UNREVIEWED_TOPIC']})
    with pytest.raises(RealBlocked): run(tmp_path, path)
    assert not sender.requests and not sources


def test_streamlit_demo_is_disabled_without_server_approval(tmp_path, harness, monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    st.cache_resource.clear()
    original = ResearchApplication.__init__
    monkeypatch.setattr(ResearchApplication, '__init__', lambda self, root: original(self, tmp_path/'legacy-ui'))
    ui = AppTest.from_file(str(Path(__file__).resolve().parents[2]/'tech_research_agent/ui.py')).run()
    ui.sidebar.radio[0].set_value('실제 API 시연').run()
    assert not ui.exception and ui.chat_input[0].disabled
    ui.checkbox(key='demo-consent-A').check().run()
    assert ui.chat_input[0].disabled and not harness[1].requests and not harness[2]
    st.cache_resource.clear()


def test_streamlit_chat_runs_real_branch_and_keeps_a_b_results_separate(tmp_path, harness, monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    from tech_research_agent import paper_demo_ui
    st.cache_resource.clear()
    path, sender, sources = harness
    original = ResearchApplication.__init__
    def initialize(app, root, **kwargs):
        original(app, tmp_path/'legacy-ui' if Path(root).name == '.technical-research-state' else root, **kwargs)
    monkeypatch.setattr(ResearchApplication, '__init__', initialize)
    service = paper_demo_ui.run_demo
    monkeypatch.setattr(paper_demo_ui, 'run_demo', lambda repository, *args, **kwargs: service(tmp_path, *args, **kwargs))
    ui = AppTest.from_file(str(Path(__file__).resolve().parents[2]/'tech_research_agent/ui.py'))
    ui.secrets['technical_paper_demo'] = {'enabled': True, 'approval_path': str(path)}
    ui.run(); ui.sidebar.radio[0].set_value('실제 API 시연').run()
    assert not ui.exception and ui.chat_input[0].disabled
    for profile in ('A', 'B'):
        sender.counts = dict.fromkeys(sender.counts, 0)
        ui.sidebar.selectbox[0].select(profile).run()
        assert not ui.chat_message
        ui.checkbox(key='demo-consent-'+profile).check().run()
        assert not ui.chat_input[0].disabled
        ui.chat_input[0].set_value(QUESTION).run(timeout=60)
        assert not ui.exception, ui.exception
        assert any(s.value == '맞춤 논문 추천 TOP 3' for s in ui.subheader)
        assert any('실제 API 시연 결과' in s.value for s in ui.caption)
        assert any(s.label == '실제 Tool Calling · 검색어 · DOI · 초록' for s in ui.expander)
    assert len(sender.requests) == 12 and len(sources) == 14
    st.cache_resource.clear()
