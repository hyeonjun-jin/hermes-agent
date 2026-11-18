"""Environment resource listings must never alter permissions or imply evidence."""

from tech_research_agent.config import runtime
from tech_research_agent.environment_resources import environment_source_overview


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
