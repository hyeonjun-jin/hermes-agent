"""Owner edits, interest-only controls and private egress denial; external APIs forbidden."""
import copy
import json
from pathlib import Path

import pytest

from tech_research_agent.application import ResearchApplication, principal
from tech_research_agent.config import PROFILES, runtime
from tech_research_agent.interests import interest_score, interest_view
from tech_research_agent.profile_experiments import run_offline_comparison, live_preparation, QUESTION
from tech_research_agent.profiles import updated_profile


def test_profile_edits_are_owner_scoped_and_do_not_write_persona_or_memory(tmp_path):
    app = ResearchApplication(tmp_path)
    path = app.store.path
    before = path.read_bytes()
    original = copy.deepcopy(PROFILES)
    with pytest.raises(PermissionError): app.update_profile(principal('strategy'), 'researcher', {'interests': ['X']})
    with pytest.raises(PermissionError): app.profile(principal('strategy'), 'researcher')
    app.update_profile(principal('researcher'), 'researcher', {'interests': ['수소환원 반응 메커니즘']})
    assert app.profile(principal('strategy'), 'strategy') == PROFILES['strategy']
    profile = app.profile(principal('researcher'), 'researcher'); profile['interests'].append('MUTATION')
    assert 'MUTATION' not in app.profile(principal('researcher'), 'researcher')['interests']
    assert PROFILES == original and path.read_bytes() == before
    app.reset_profile(principal('researcher'), 'researcher')
    assert app.profile(principal('researcher'), 'researcher') == PROFILES['researcher']


@pytest.mark.parametrize('changes', [{'interests': 'not a list'}, {'interests': ['x']*11}, {'job': ''},
    {'business_unit': 'line\nbreak'}, {'allowed_sources': ['openalex']}, {'focus': 'finance'}, {'job': 123},
    {'expertise': 'x'*201}, {'interests': ['sk-proj-'+'x'*25]}])
def test_invalid_profile_values_cannot_change_security(changes):
    with pytest.raises(ValueError): updated_profile(PROFILES['researcher'], changes)


@pytest.mark.parametrize('mode,connector', [('real', False), ('approved_public', False), ('mock', True)])
def test_private_profile_never_reaches_model_or_source(tmp_path, mode, connector):
    class Forbidden:
        def execute(self, *args): pytest.fail('Private input must not be sent to source')
    app = ResearchApplication(tmp_path, source_connectors={'openalex': Forbidden()} if connector else {})
    app.update_profile(principal('researcher'), 'researcher', {'interests': ['PRIVATE_CUSTOM_TOPIC']})
    with pytest.raises(PermissionError, match='PRIVATE'):
        app.ask(principal('researcher'), 'researcher', QUESTION, execution_mode=mode)
    assert app.store.search(principal('researcher'), 'researcher', QUESTION) == []


@pytest.fixture(scope='module')
def comparison():
    return run_offline_comparison()


def test_job_comparison_keeps_common_candidates_and_environment(comparison):
    a, b = comparison['experiments']['job'].values()
    assert a['candidate_ids'] == b['candidate_ids'] and len(a['candidate_ids']) == 4
    assert a['fixed_inputs'] == b['fixed_inputs']
    assert a['recommendations'][0]['source_id'] == 'H-PAPER-EXP'
    assert b['recommendations'][0]['source_id'] == 'H-PAPER-BIZ'
    assert a['analysis'] != b['analysis']


def test_only_interests_change_rank_search_and_analysis_on_identical_evidence(comparison):
    a, b = comparison['experiments']['interests'].values()
    assert a['fixed_inputs'] == b['fixed_inputs']
    assert a['profile_except_interests_sha256'] == b['profile_except_interests_sha256']
    assert a['persona_sha256'] == b['persona_sha256']
    assert a['evidence_sha256'] == b['evidence_sha256'] and a['permissions_sha256'] == b['permissions_sha256']
    assert a['evidence_ids'] == b['evidence_ids'] == a['candidate_ids'] == b['candidate_ids']
    assert a['recommendations'][0]['source_id'] == 'H-PAPER-EXP'
    assert b['recommendations'][0]['source_id'] == 'H-PAPER-PILOT'
    assert a['tool_calls'][0]['rp']['query'] != b['tool_calls'][0]['rp']['query']
    assert '반응 메커니즘·환원 원리' in a['analysis']
    assert '공정 조건·최적화' in b['analysis']
    for arm in (a, b):
        assert arm['complete'] and arm['mock_model_calls'] == 6 and arm['initial_memory_empty']
        for item in arm['recommendations']:
            assert item['score'] == pytest.approx(sum(item['score_components'].values()))
            assert not item['learning_effect_established'] and item['doi'] is None
    assert comparison['paid_calls'] == comparison['external_source_calls'] == 0


def test_same_metadata_with_altered_ids_cannot_force_interest_ranking(comparison):
    from tech_research_agent.paper_ranking import score_paper
    arm = comparison['experiments']['interests']['mechanism']
    paper = arm['recommendations'][0]
    _, env, _ = runtime('researcher', 'H', 'quick')
    one = score_paper(paper, arm['profile'], {}, env, QUESTION)
    two = score_paper({**paper, 'source_id': 'ARBITRARY'}, arm['profile'], {}, env, QUESTION)
    assert one['score_components'] == two['score_components'] and one['score'] == two['score']


def test_request_environment_and_unrelated_topic_suppress_interest():
    profile, env, _ = runtime('researcher', 'H', 'quick')
    profile['interests'] = ['수소환원 반응 메커니즘', 'NCM LFP 양극재']
    question = '수소환원 공정 최적화만 중심으로 논문을 추천해주세요.'
    view = interest_view(profile, env, question)
    assert not view['facets'] and len(view['suppressed']) == 2
    assert interest_score('Hydrogen reaction mechanism kinetics', profile, env, question)[0] == 0
    assert not interest_view(profile, {**env, 'purpose': '공정 최적화 검토'}, QUESTION)['facets']
    assert not interest_view(profile, env, '공정 최적화 논문 추천')['facets']


def test_business_unit_never_filters_cross_unit_shared_interests(comparison):
    from tech_research_agent.paper_ranking import rank_papers
    arm = comparison['experiments']['interests']['mechanism']
    _, env, _ = runtime('researcher', 'H', 'quick')
    changed = {**arm['profile'], 'business_unit': '이차전지소재'}
    ranked = rank_papers(arm['recommendations'], changed, {}, env, QUESTION)
    assert ranked[0]['source_id'] == arm['recommendations'][0]['source_id']
    assert ranked[0]['score_components']['personal_interests'] > 0


def test_legacy_profiles_and_keyword_fallback_remain_supported(comparison):
    from tech_research_agent.paper_ranking import score_paper
    arm = comparison['experiments']['interests']['mechanism']
    _, env, _ = runtime('researcher', 'H', 'quick')
    legacy = {k: v for k, v in arm['profile'].items() if k != 'business_unit'}
    item = score_paper(arm['recommendations'][0], legacy, {}, env, QUESTION)
    assert item['score_components']['profile_business_unit'] == 0
    assert item['score_components']['personal_interests'] == 8
    profile = {**legacy, 'interests': ['catalyst', 'catalyst']}
    assert interest_score('Hydrogen catalyst experiment', profile, env, QUESTION)[0] == 2


def test_explicit_question_focus_precedes_conflicting_profile_interest(comparison):
    from tech_research_agent.paper_ranking import rank_papers
    arm = comparison['experiments']['interests']['mechanism']
    _, env, _ = runtime('researcher', 'H', 'quick')
    ranked = rank_papers(arm['recommendations'], arm['profile'], {}, env, '공정 최적화 논문 추천')
    assert ranked[0]['source_id'] == 'H-PAPER-PILOT'
    assert all(p['score_components']['personal_interests'] == 0 for p in ranked)


def test_live_preparation_is_hash_only_read_only_and_not_execution_approval(tmp_path):
    app = ResearchApplication(tmp_path)
    app.update_profile(principal('researcher'), 'researcher', {'interests': ['CONFIDENTIAL_PROFILE_TOPIC']})
    before = app.store.path.read_bytes()
    prepared = live_preparation(app, principal('researcher'), QUESTION)
    assert prepared['status'] == 'NO-GO' and not prepared['live_execution_enabled']
    assert not prepared['persona_exists'] and 'CONFIDENTIAL_PROFILE_TOPIC' not in json.dumps(prepared)
    assert app.store.path.read_bytes() == before and not list(tmp_path.glob('**/usage.json'))


def test_persona_replay_restores_fixed_explicit_profile_without_changing_operating_persona(tmp_path):
    from tech_research_agent.persona_replay import TechnicalMockReplay
    app = ResearchApplication(tmp_path)
    actor = principal('researcher')
    app.update_profile(actor, actor.user_id, {'interests': ['수소환원 반응 메커니즘']})
    turn = app.ask(actor, actor.user_id, QUESTION)
    baseline = app.personas.current(actor, 'proj-H')
    before = app.store.path.read_bytes()
    result = TechnicalMockReplay().compare(actor.user_id, baseline, {'criteria': ['experimental_conditions']}, turn, {})
    assert result['functional_check']
    assert result['before']['input']['profile'] == result['after']['input']['profile'] == turn['input_snapshot']['profile']
    assert app.store.path.read_bytes() == before


def test_profile_ui_edits_switches_and_resets_without_cross_user_changes(tmp_path, monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    st.cache_resource.clear()
    original = ResearchApplication.__init__
    monkeypatch.setattr(ResearchApplication, '__init__', lambda self, root: original(self, tmp_path))
    ui = AppTest.from_file(str(Path(__file__).resolve().parents[2]/'tech_research_agent/ui.py')).run()
    ui.text_area(key='profile-researcher-interests').set_value('수소환원 반응 메커니즘')
    next(b for b in ui.button if b.label == '이 사용자 Profile 적용').click().run()
    assert not ui.exception and ui.text_area(key='profile-researcher-interests').value == '수소환원 반응 메커니즘'
    ui.sidebar.selectbox[0].select('strategy').run()
    assert ui.text_area(key='profile-strategy-interests').value == '\n'.join(PROFILES['strategy']['interests'])
    ui.sidebar.selectbox[0].select('researcher').run()
    ui.button(key='profile-reset-researcher').click().run()
    assert not ui.exception and ui.text_area(key='profile-researcher-interests').value == '\n'.join(PROFILES['researcher']['interests'])
    ui.button(key='profile-offline-comparison').click().run(timeout=60)
    assert not ui.exception
    assert len([t for t in ui.table if '관심사 점수' in t.value.columns]) == 2
    st.cache_resource.clear()
