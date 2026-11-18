"""Deterministic paper relevance, same candidate pool, permission boundaries and real-shaped metadata; no network."""
import copy
import json
import socket

import httpx
import pytest

from tech_research_agent.application import ResearchApplication, principal
from tech_research_agent.config import runtime
from tech_research_agent.connectors.openalex import OpenAlexConnector
from tech_research_agent.paper_fixtures import fixture_adapter
from tech_research_agent.paper_recommendations import recommend_from_trace, public_link
from tech_research_agent.real import RealAdapter

QUESTION = '수소환원제철 관련 논문 추천과 근거를 알려주세요.'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original = socket.socket.connect
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in {'127.0.0.1', '::1'}:
            pytest.fail('Remote APIs forbidden')
        return original(sock, address)
    def blocked(*args, **kwargs): pytest.fail('OpenAI transport forbidden')
    monkeypatch.setattr(socket.socket, 'connect', connect)
    monkeypatch.setattr(RealAdapter, '_network_send', blocked)


def collected(user='researcher', topic='H'):
    profile, env, base = runtime(user, topic, 'quick')
    adapter = fixture_adapter(base, env)
    found = adapter.execute({'id': 'research-search', 'app': 'openalex', 'api': 'search_works',
        'rp': {'query': 'hydrogen' if topic == 'H' else 'NCM'}, 'op': {'limit': 4}, 'after': []})
    for item in found['items']:
        adapter.execute({'id': 'research-read', 'app': 'openalex', 'api': 'read_work',
            'rp': {'work_id': item['source_id']}, 'op': {'include_abstract': True}, 'after': []})
    return profile, env, adapter


def test_same_question_and_pool_reorder_from_profile_features_not_user_id():
    researcher, env, adapter = collected()
    strategy, _, _ = runtime('strategy', 'H', 'quick')
    a = recommend_from_trace(adapter, researcher, {}, env, QUESTION)
    b = recommend_from_trace(adapter, strategy, {}, env, QUESTION)
    assert a['candidate_ids'] == b['candidate_ids'] and len(a['candidate_ids']) == 4
    assert a['items'][0]['source_id'] == 'H-PAPER-EXP'
    assert b['items'][0]['source_id'] == 'H-PAPER-BIZ'
    assert '재현성' in a['items'][0]['matched_profile_concepts']
    assert '사업화' in b['items'][0]['matched_profile_concepts']
    assert a == recommend_from_trace(adapter, copy.deepcopy(researcher), {}, env, QUESTION)
    for item in a['items']+b['items']:
        assert item['score'] == pytest.approx(sum(item['score_components'].values()))
        assert not item['learning_effect_established'] and not item['full_text_read']
        assert item['doi'] is None and item['openalex_link'] is None and item['source_link'] is None


def test_only_approved_persona_changes_ranking_and_does_not_mutate_original():
    profile, env, adapter = collected()
    persona = {'explicitly_approved': True, 'data_policy': 'PRIVATE', 'research_persona': {'version': 3,
        'preferences': {'criteria': ['financial_risk', 'commercialization'], 'depth': 'detailed', 'preferred_apps': ['openalex']}}}
    original = copy.deepcopy(persona)
    before = recommend_from_trace(adapter, profile, {}, env, QUESTION)
    after = recommend_from_trace(adapter, profile, persona, env, QUESTION)
    assert before['items'][0]['source_id'] == 'H-PAPER-EXP'
    assert after['items'][0]['source_id'] == 'H-PAPER-BIZ'
    assert after['items'][0]['matched_persona_criteria'] == ['financial_risk', 'commercialization']
    assert persona == original
    assert recommend_from_trace(adapter, profile, {**persona, 'explicitly_approved': False}, env, QUESTION) == before


def test_environment_deadline_purpose_and_cutoff_have_explainable_effects():
    profile, env, adapter = collected()
    baseline = recommend_from_trace(adapter, profile, {}, env, QUESTION)
    changed = {**env, 'purpose': '사업화 시장 위험 검토', 'deadline': '2026-10-20T12:00:00+09:00', 'depth': 'deep'}
    result = recommend_from_trace(adapter, profile, {}, changed, QUESTION)
    assert baseline['items'][0]['score_components'] != result['items'][0]['score_components']
    assert all(not item['environment_basis']['urgent_deadline'] for item in result['items'])
    earlier = recommend_from_trace(adapter, profile, {}, {**env, 'cutoff': '2026-03-31'}, QUESTION)
    assert all(item['published_at'] <= '2026-03-31' for item in earlier['items'])


@pytest.mark.parametrize('change', ['revoked', 'project', 'source_acl', 'future', 'unobserved', 'tampered'])
def test_permissions_project_and_receipts_precede_ranking(change):
    profile, env, adapter = collected()
    target = 'H-PAPER-EXP'
    edits = {
        'revoked': lambda: adapter.context.revoked.add(target),
        'project': lambda: adapter.corpus[target].update(project_id='proj-B'),
        'source_acl': lambda: adapter.context.allowed_sources.discard('openalex'),
        'future': lambda: adapter.corpus[target].update(published_at='2099-01-01'),
        'unobserved': lambda: adapter.trace.pop(0),
        'tampered': lambda: next(e for e in adapter.trace if e['plan']['api'] == 'read_work' and
            e['result']['items'][0]['source_id'] == target)['result']['items'][0].update(title='unobserved replacement'),
    }
    edits[change]()
    result = recommend_from_trace(adapter, profile, {}, env, QUESTION)
    assert target not in {item['source_id'] for item in result['items']}


def test_default_mock_agent_loop_common_pool_and_local_private_persona_are_not_exported(tmp_path):
    outputs = {}
    for user in ('researcher', 'strategy'):
        app = ResearchApplication(tmp_path/user)
        outputs[user] = app.ask(principal(user), user, QUESTION)
        assert outputs[user]['complete']
        assert [s['role'] for s in outputs[user]['stages']] == ['research', 'analysis', 'verification']
        assert outputs[user]['model_calls'] == 6 and outputs[user]['tool_cost'] == 9
        assert all(e['plan']['app'] == 'openalex' for e in outputs[user]['trace'])
        assert outputs[user]['paper_recommendations']['additional_model_calls'] == 0
    a, b = (outputs[u]['paper_recommendations'] for u in ('researcher', 'strategy'))
    assert a['candidate_ids'] == b['candidate_ids']
    assert a['items'][0]['source_id'] == 'H-PAPER-EXP' and b['items'][0]['source_id'] == 'H-PAPER-BIZ'


def test_restricted_environment_and_user_isolation(tmp_path):
    app = ResearchApplication(tmp_path)
    result = app.ask(principal('researcher'), 'researcher', QUESTION, mode='restricted')
    assert not result['paper_recommendations']['items']
    assert not any(e['plan']['app'] == 'openalex' for e in result['trace'])
    with pytest.raises(PermissionError): app.ask(principal('strategy'), 'researcher', QUESTION)


@pytest.mark.parametrize('with_abstract', [True, False])
def test_real_shaped_connector_search_and_read_keep_doi_abstract_provenance(with_abstract):
    raw = {'id': 'https://openalex.org/W999', 'title': 'FABRICATED hydrogen experiment', 'publication_date': '2026-05-01',
           'publication_year': 2026, 'doi': 'https://doi.org/10.9999/fabricated-test-only',
           'abstract_inverted_index': {'Hydrogen': [0], 'experiment': [1]}}
    if not with_abstract:
        raw.pop('abstract_inverted_index')
    requests = []
    def send(request):
        requests.append(request)
        return httpx.Response(200, json={'results': [raw]} if request.url.path == '/works' else raw)
    connector = OpenAlexConnector(enabled=True, transport=httpx.MockTransport(send))
    profile, env, adapter = runtime('researcher', 'H', 'quick', connectors={'openalex': connector})
    search = adapter.execute({'id': 'research-search', 'app': 'openalex', 'api': 'search_works', 'rp': {'query': 'hydrogen'}, 'op': {}, 'after': []})
    adapter.execute({'id': 'research-read', 'app': 'openalex', 'api': 'read_work', 'rp': {'work_id': search['items'][0]['source_id']}, 'op': {}, 'after': []})
    result = recommend_from_trace(adapter, profile, {}, env, QUESTION)
    paper = result['items'][0]
    assert paper['doi'] == raw['doi'] and paper['abstract_checked'] is with_abstract and not paper['full_text_read']
    assert len(requests) == 2 and result['additional_source_calls'] == 0
    connector.close()


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'https://host/?api_key=secret', 'https://user:secret@host/paper', 'https://[', '10.guessed/invalid'])
def test_untrusted_links_are_not_invented_or_displayed(url):
    assert public_link(url, doi=True) is None


def test_metadata_only_read_does_not_claim_abstract_or_full_text():
    profile, env, adapter = collected()
    adapter.context.revoked.update({'H-PAPER-EXP', 'H-PAPER-BIZ', 'H-PAPER-PILOT'})
    paper = recommend_from_trace(adapter, profile, {}, env, QUESTION)['items'][0]
    assert paper['source_id'] == 'H-PAPER-META'
    assert paper['evidence_coverage'] == 'metadata_only' and not paper['abstract_checked']
    assert not paper['full_text_read'] and paper['doi'] is None


def test_streamlit_top_three_and_original_report_survive_user_switch(tmp_path, monkeypatch):
    from pathlib import Path
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    st.cache_resource.clear()
    original = ResearchApplication.__init__
    def initialize(self, root, **kwargs): original(self, tmp_path, **kwargs)
    monkeypatch.setattr(ResearchApplication, '__init__', initialize)
    ui = AppTest.from_file(str(Path(__file__).resolve().parents[2]/'tech_research_agent/ui.py')).run()
    button = next(b for b in ui.button if b.label == '맞춤 논문 추천 요청 (Mock)')
    button.click().run(timeout=60)
    assert not ui.exception
    assert any(s.value == '맞춤 논문 추천 TOP 3' for s in ui.subheader)
    assert any('1. SYNTHETIC 수소환원제철 실험 조건과 재현성' in row.value for row in ui.text)
    assert any('기술조사 보고서' in row.value for row in ui.markdown)
    ui.sidebar.selectbox[0].select('strategy').run()
    assert not ui.chat_message
    next(b for b in ui.button if b.label == '맞춤 논문 추천 요청 (Mock)').click().run(timeout=60)
    assert not ui.exception
    assert any('1. SYNTHETIC 수소환원제철 상용화와 시장 전환' in row.value for row in ui.text)
    st.cache_resource.clear()


def test_recommendation_private_inputs_stay_local_to_the_postprocessor():
    from tech_research_agent.paired_comparison import PairedPublicComparison
    from tests.tech_research_agent.paired_fixtures import PairFixture, QUESTION as PUBLIC_QUESTION
    outputs = {}
    def capture(apps):
        for label, app in apps.items():
            original = app.ask
            def ask(*args, saved=original, condition=label, **kwargs):
                result = saved(*args, **kwargs)
                outputs[condition] = result
                return result
            app.ask = ask
    fixture = PairFixture(mutate=capture)
    result = PairedPublicComparison(fixture).run(principal('researcher'), PUBLIC_QUESTION, enabled=True)
    assert result['status'] == 'completed'
    for label, sender in fixture.senders.items():
        assert outputs[label]['paper_recommendations']['items']
        wire = json.dumps(sender.requests)
        assert 'paper_recommendations' not in wire and 'persona_basis' not in wire and 'financial_detail' not in wire
