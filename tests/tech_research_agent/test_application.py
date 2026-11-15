"""Functional Mock tests, not a personalization benchmark or model evaluation."""
import pytest
from tech_research_agent.application import ResearchApplication, principal


@pytest.mark.parametrize('user,expected',[('researcher',{'openalex','kipris_plus'}),('strategy',{'opendart','posco_ir'}),('finance',{'opendart','posco_ir'})])
def test_same_question_different_sources(tmp_path,user,expected):
    app=ResearchApplication(tmp_path)
    result=app.ask(principal(user),user,'수소환원제철을 비교 조사해주세요.')
    assert [s['role'] for s in result['stages']]==['research','analysis','verification']
    assert {e['plan']['app'] for e in result['trace']}==expected
    assert result['evidence'] and result['complete']
    assert result['mode']=='mock' and result['checks']['human_review_required']
    if user=='finance':
        assert any(e['plan']['api']=='read_material' and e['plan']['id'].startswith('research-') for e in result['trace'])
        assert any(e['plan']['api']=='read_material' and e['plan']['id'].startswith('verification-') for e in result['trace'])


def test_identity_memory_and_environment_priority(tmp_path):
    app=ResearchApplication(tmp_path)
    with pytest.raises(PermissionError):app.ask(principal('finance'),'researcher','조사')
    app.approve(principal('finance'),'science')
    result=app.ask(principal('finance'),'finance','수소환원제철을 재무 중심으로 조사',mode='restricted')
    assert all(e['plan']['app']=='internal_mock' for e in result['trace'])
    assert result['trace'][0]['plan']['op']['evidence_kind']=='financial'
    assert app.store.semantic(principal('researcher'),'researcher')=={}


def test_project_conflict_clarifies(tmp_path):
    result=ResearchApplication(tmp_path).ask(principal('finance'),'finance','NCM과 LFP 조사',topic='H')
    assert not result['complete'] and not result['trace']


def test_tool_handler_never_bypasses_policy(tmp_path):
    from tech_research_agent.config import runtime
    from tech_research_agent.provider import ResearchProvider
    import json
    _,_,adapter=runtime('researcher','H','restricted')
    provider=ResearchProvider('research',adapter,{})
    result=json.loads(provider.handle_tool_call('openalex__search_works',{'rp':{'query':'hydrogen'},'op':{}}))
    assert result['status']=='denied' and adapter.trace[-1]['executed'] is False
    result=json.loads(ResearchProvider('analysis',adapter,{}).handle_tool_call('openalex__search_works',{'rp':{'query':'hydrogen'},'op':{}}))
    assert result['status']=='denied'


def test_history_and_explicit_preference_are_scoped(tmp_path):
    app=ResearchApplication(tmp_path)
    app.approve(principal('researcher'),'finance')
    result=app.ask(principal('researcher'),'researcher','수소환원제철을 논문만 조사')
    assert {e['plan']['app'] for e in result['trace']}=={'openalex'}
    again=app.ask(principal('researcher'),'researcher','수소환원제철을 논문만 조사')
    assert again['history_used']
    assert app.store.search(principal('strategy'),'strategy','수소환원제철')==[]


def test_mechanical_audit_flags_unsupported_claims():
    from tech_research_agent.audit import review
    report=review('[fake-id] 이익 999%',[])
    assert report['unknown_citations']==['fake-id'] and report['unmatched_numeric_tokens']==['999%']


def test_deep_environment_changes_scope_and_internal_sources(tmp_path):
    app=ResearchApplication(tmp_path)
    result=app.ask(principal('researcher'),'researcher','수소환원제철 비교 조사',mode='deep')
    searches=[e['plan'] for e in result['trace'] if 'search' in e['plan']['api']]
    assert any(c['app']=='internal_mock' for c in searches)
    assert all(c['op']['limit']==5 and c['op']['from_date']=='2022-01-01' for c in searches)
    assert result['complete']
    public=app.ask(principal('researcher'),'researcher','수소환원제철 비교 조사',mode='quick')
    assert public['history_used']==[]  # Earlier internal evidence is not reused after downgrade.


def test_hermes_profile_scope_is_restored(tmp_path):
    from hermes_constants import get_hermes_home
    from agent.runtime_scope import current_scope
    before=(get_hermes_home(),current_scope())
    result=ResearchApplication(tmp_path).ask(principal('finance'),'finance','수소환원제철 비교 조사')
    assert result['complete']
    assert (get_hermes_home(),current_scope())==before


def test_battery_project_and_history_do_not_cross_projects(tmp_path):
    app=ResearchApplication(tmp_path)
    app.ask(principal('finance'),'finance','수소환원제철 비교 조사',topic='H')
    result=app.ask(principal('finance'),'finance','NCM LFP 양극재 비교 조사',topic='B')
    assert result['complete'] and result['history_used']==[]
    assert all(source['source_id'].startswith('B-') for source in result['evidence'])
