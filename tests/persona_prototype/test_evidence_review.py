"""Current Environment and bounded document search are independent sources."""
import pytest

from persona_prototype.app import SCOPES, seed
from persona_prototype.domain import Principal, OwnerOnly
from persona_prototype.store import MemoryStore
from persona_prototype.multi_agent import MultiAgentProvider
from persona_prototype.evidence import collect_evidence, evidence_review, ground_evidence


def provider_for(tmp_path, user='alice'):
    store = MemoryStore(tmp_path / 'memory.sqlite', OwnerOnly())
    seed(store)
    provider = MultiAgentProvider(store, Principal(user, SCOPES))
    provider.initialize('fixture-' + user)
    provider.question = '프로젝트 계획을 조사 분석 검증해 주세요'
    return provider


@pytest.mark.parametrize('user,project,stage', [('alice', 'atlas', 'prototype'), ('bob', 'beacon', 'review'),
                                              ('carol', 'cedar', 'learning')])
def test_empty_search_does_not_erase_authorized_environment(tmp_path, user, project, stage):
    provider = provider_for(tmp_path, user)
    provider.role_tool('research', {'query': 'zzzz', 'tag': 'risk'})
    provider.role_tool('analysis', {'project': project})
    raw = '문서에서 미발견. Environment 정보가 없습니다. 진행 단계: 미확인. 일정은 존재하지 않습니다.'
    answer, audit = ground_evidence(provider, raw)
    evidence = collect_evidence(provider)
    assert evidence['documents']['state'] == 'not_found_in_search'
    assert evidence['environment']['state'] == 'observed'
    assert evidence['environment']['items'][0]['stage'] == stage
    kinds = {issue['kind'] for issue in audit['raw_review']['issues']}
    assert {'known_environment_as_unknown', 'environment_fact_omitted', 'unscoped_absence_claim'} <= kinds
    assert f'[environment:{project}]' in answer and stage in answer
    assert '미발견은 실제 부재를 뜻하지 않습니다' in answer
    assert audit['applied'] and audit['semantic_review_required']
    assert 'doc-1' not in answer


def test_environment_review_distinguishes_gaps_denials_and_literal_mentions(tmp_path):
    provider = provider_for(tmp_path)
    provider.role_tool('analysis', {'project': 'atlas'})
    evidence = collect_evidence(provider)
    good = '프로젝트 atlas. 현재 단계: 프로토타입. 제약: 작은 단위 배포. 상세 일정은 미확인.'
    assert evidence_review(good, evidence)['issues'] == []
    for text in ('Environment 정보를 확인하지 못했습니다.', '현재 단계는 prototype인지 미확인입니다.',
                 '프로젝트 atlas. 단계: 미확인. 제약: 작은 단위 배포.'):
        review = evidence_review(text, evidence)
        assert any(i['kind'] == 'known_environment_as_unknown' for i in review['issues'])
    wrong = evidence_review('프로젝트 atlas. 현재 단계: delivery. 제약: 작은 단위 배포.', evidence)
    assert any(i['kind'] == 'environment_fact_conflict' for i in wrong['issues'])
    missing = evidence_review('프로젝트 atlas. 현재 단계: prototype.', evidence)
    assert any(i.get('field') == 'constraint' for i in missing['issues'])


def test_failed_foreign_or_historical_evidence_cannot_become_current(tmp_path):
    provider = provider_for(tmp_path)
    provider.prior_environment = {'project': 'atlas', 'stage': 'old', 'constraint': 'old'}
    provider.role_tool('analysis', {'project': 'beacon'})
    provider.trace.append({'tool': 'mock_environment', 'args': {'project': 'beacon'}, 'status': 'ok',
                           'result': {'project': 'beacon', 'stage': 'review'}})
    answer, audit = ground_evidence(provider, '일정 미확인')
    assert 'review' not in answer and 'old' not in answer
    assert audit['sources']['environment']['state'] != 'observed'
    assert audit['sources']['documents']['state'] == 'not_checked'


def test_document_gap_is_not_a_global_absence_statement(tmp_path):
    provider = provider_for(tmp_path)
    evidence = collect_evidence(provider)
    assert evidence_review('이번 검색에서 상세 일정은 찾지 못했다. 실제 존재 여부는 미확인.', evidence)['issues'] == []
    assert any(i['kind'] == 'unscoped_absence_claim' for i in
               evidence_review('일정은 존재하지 않습니다.', evidence)['issues'])


@pytest.mark.parametrize('user', ['alice', 'bob', 'carol'])
def test_grounding_runs_after_native_workflow_without_an_extra_model_call(tmp_path, user):
    import json
    from persona_prototype.app import ChatApplication
    from persona_prototype.data import ENVIRONMENTS, PROFILES
    from persona_prototype.mock_llm import mock_endpoint
    from persona_prototype.web_mock import web_respond
    calls = []
    raw = '환경 정보를 확인하지 못했습니다. 진행 단계: 미확인. 수율 98.2%, 2026-11-15 기준. 상세 일정은 미확정.'
    def respond(messages):
        users = '\n'.join(str(m.get('content', '')) for m in messages if m['role'] == 'user')
        if '[PERSONA_ROLE=' not in users and any(m['role'] == 'tool' for m in messages):
            return {'role': 'assistant', 'content': raw}, 'stop'
        return web_respond(messages)
    with mock_endpoint(respond, request_observer=calls.append) as url:
        app = ChatApplication(tmp_path, base_url=url, api_key='offline', model='persona-mock', multi_agent=True)
        seed(app.store)
        result = app.chat(Principal(user, SCOPES), user, '프로젝트 계획을 조사 분석 검증해 주세요')
    project = PROFILES[user]['project']
    assert len(calls) == 8
    assert [e['role'] for e in result['delegations']] == ['research', 'analysis', 'verification']
    assert result['raw_answer'] == raw
    assert result['evidence_validation']['applied']
    assert result['source_evidence']['environment']['items'] == [ENVIRONMENTS[project]]
    assert result['completion']['quality_review_required']
    for value in [ENVIRONMENTS[project]['stage'], '98.2%', '2026-11-15', '미확정']:
        assert value in result['answer']
    for other in set(PROFILES) - {user}:
        assert 'profile:' + other not in result['answer']
    assert result['format_validation']['raw_valid'] == (user == 'carol')
    assert 'doc-999' not in json.dumps(result)


def test_quality_flags_stage_denial_even_when_expected_literal_is_present():
    from persona_prototype.quality import quality_review
    result = {'raw_answer': '현재 단계: prototype인지 미확인입니다.', 'answer': '현재 단계: prototype인지 미확인입니다.',
              'role_tool_calls': [{'role': 'analysis', 'status': 'ok',
                                   'result': {'project': 'atlas', 'stage': 'prototype'}}]}
    assert quality_review(result)['possible_environment_contradiction']
