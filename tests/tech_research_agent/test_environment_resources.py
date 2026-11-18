"""Environment resource listings must never alter permissions or imply evidence."""

from tech_research_agent.config import runtime
import copy
import json
from types import SimpleNamespace

import pytest

from tech_research_agent.environment_resources import environment_source_overview
from tech_research_agent.evidence_ui import evidence_overview
from tech_research_agent.provider import ResearchProvider


def test_policy_and_connector_state_are_independent_and_immutable():
    env = {"allowed_sources": ["openalex", "posco_ir"]}
    connectors = {"openalex": object(), "opendart": object()}
    before = list(env["allowed_sources"])
    rows = environment_source_overview(env, connectors)
    by_name = {row["정보 자원"]: row for row in rows}

    assert by_name["OpenAlex"]["Environment 정책"] == "허용"
    assert by_name["OpenAlex"]["외부 Connector"] == "설정됨"
    assert by_name["POSCO IR"]["Environment 정책"] == "허용"
    assert by_name["POSCO IR"]["외부 Connector"] == "미설정"
    assert by_name["OpenDART"]["Environment 정책"] == "미허용"
    assert by_name["OpenDART"]["외부 Connector"] == "설정됨"
    assert env["allowed_sources"] == before


def test_restricted_environment_shows_external_sources_denied():
    _, env, _ = runtime("researcher", "H", "restricted")
    rows = environment_source_overview(env, {})
    assert len(rows) == 4
    assert all(row["Environment 정책"] == "미허용" for row in rows)
    assert all(row["외부 Connector"] == "미설정" for row in rows)


def test_quick_environment_lists_sources_but_not_fake_connection():
    _, env, _ = runtime("strategy", "H", "quick")
    rows = environment_source_overview(env)
    assert {row["정보 자원"] for row in rows} == {"OpenAlex", "KIPRIS Plus", "OpenDART", "POSCO IR"}
    assert all(row["Environment 정책"] == "허용" for row in rows)
    assert all(row["외부 Connector"] == "미설정" for row in rows)


@pytest.mark.parametrize('mode', ['quick', 'deep', 'restricted'])
def test_resources_describe_access_without_documents_or_connector_secrets(mode):
    _, env, adapter = runtime('researcher', 'H', mode)
    resources = env['information_resources']
    assert [r['source'] for r in resources] == env['allowed_sources']
    assert adapter.context.allowed_sources == set(env['allowed_sources'])
    assert all(set(r) == {'source', 'name', 'material_type', 'access_conditions'} for r in resources)
    for resource in resources:
        conditions = resource['access_conditions']
        assert conditions['project_access'] == 'server_acl'
        assert conditions['publication_date'] == 'at_or_before_cutoff'
        assert conditions['external_llm_processing'] == 'separate_server_approval'
    assert not any('spans' in r or 'items' in r or 'api_key' in r or 'abstract' in r for r in resources)


def test_connector_enabled_is_not_connectivity_or_permission():
    env = {'allowed_sources': ['openalex']}
    connector = SimpleNamespace(enabled=False, _api_key='DO_NOT_DISPLAY')
    rows = environment_source_overview(env, {'openalex': connector})
    assert rows[0]['외부 Connector'] == '설정됨' and rows[0]['활성 설정'] == '비활성'
    assert all('미확인' in row['연결 확인'] for row in rows)
    assert 'DO_NOT_DISPLAY' not in json.dumps(rows)
    connector.enabled = True
    assert environment_source_overview(env, {'openalex': connector})[0]['활성 설정'] == '활성'


def test_resource_metadata_cannot_grant_access_or_change_tool_schema():
    profile, env, adapter = runtime('researcher', 'H', 'restricted')
    provider = ResearchProvider('research', adapter, {'profile': profile, 'environment': env})
    before = copy.deepcopy(provider.get_tool_schemas())
    env['allowed_sources'].append('openalex')
    env['information_resources'].append({'source': 'openalex', 'access_conditions': {'granted': True}})
    result = json.loads(provider.handle_tool_call('openalex__search_works', {'rp': {'query': 'hydrogen'}, 'op': {}}))
    assert result['status'] == 'denied' and adapter.trace[-1]['executed'] is False
    assert adapter.context.allowed_sources == {'internal_mock'}
    assert provider.get_tool_schemas() == before


def test_mock_research_context_and_receipt_backed_evidence_stay_separate(tmp_path):
    from tech_research_agent.application import ResearchApplication, principal
    result = ResearchApplication(tmp_path).ask(principal('researcher'), 'researcher', '수소환원제철을 논문만 조사')
    assert [s['role'] for s in result['stages']] == ['research', 'analysis', 'verification']
    assert result['complete'] and result['evidence']
    snapshot = result['input_snapshot']
    assert snapshot['profile']['job'] == '박사 연구원'
    assert snapshot['environment']['information_resources']
    assert 'evidence' not in snapshot['environment']
    for event in result['trace']:
        supplied = event['input_provenance']['supplied_context']
        assert supplied['environment'] == snapshot['environment']
        assert supplied['profile'] == snapshot['profile']
        assert supplied['persona_guidance'] == snapshot['persona_guidance']
    rows = evidence_overview(result)
    assert len(rows) == len(result['evidence'])
    assert all(row['자료 구분'] == 'SYNTHETIC' and '미확인' not in row['조회 근거'] for row in rows)
    assert all('research-tool-' in row['조회 근거'] and 'verification-tool-' in row['조회 근거'] for row in rows)
    assert evidence_overview({**result, 'evidence': []}) == []
    search_only = {**result, 'trace': [e for e in result['trace'] if not e['plan']['api'].startswith('read_')]}
    assert all('미확인' in row['조회 근거'] for row in evidence_overview(search_only))
    for condition in ('failed', 'denied', 'changed'):
        unverified = copy.deepcopy(result)
        for event in unverified['trace']:
            if condition == 'failed': event['result']['status'] = 'unavailable'
            if condition == 'denied': event['egress_policy'] = {'status': 'denied'}
            if condition == 'changed': event['result']['items'] = []
        assert all('미확인' in row['조회 근거'] for row in evidence_overview(unverified))
