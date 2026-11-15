"""Project facts are sourced from Profile and authorized Environment, not preference recall."""
import json

import pytest
from fastapi.testclient import TestClient

from persona_prototype.app import ChatApplication, SCOPES, seed
from persona_prototype.data import PROFILES, ENVIRONMENTS
from persona_prototype.domain import Principal
from persona_prototype.mock_llm import mock_endpoint
from persona_prototype.provider import MockEnterpriseData
from persona_prototype.web_backend import create_app
from persona_prototype.web_mock import web_respond
from persona_prototype.web_sessions import ChatSessions

QUESTION = "제 프로젝트 이름과 현재 진행 단계를 알려주세요"


@pytest.mark.parametrize("user", ["alice", "bob", "carol"])
def test_same_fact_question_uses_own_environment_and_not_subagents(tmp_path, user):
    with TestClient(create_app(tmp_path, mode="mock", dev_mode=True)) as client:
        session = client.post("/dev/sessions", json={"user": user}).json()
        response = client.post(f'/sessions/{session["session_id"]}/messages',
            headers={"Authorization": "Bearer " + session["session_token"]}, json={"message": QUESTION})
        assert response.status_code == 200
        result = response.json()
    project = PROFILES[user]["project"]
    environment = ENVIRONMENTS[project]
    assert project in result["answer"] and environment["stage"] in result["answer"]
    assert f"[profile:{user}]" in result["answer"] and f"[environment:{project}]" in result["answer"]
    assert result["delegations"] == result["role_tool_calls"] == []
    assert [(e["tool"], e["args"], e["status"]) for e in result["tool_calls"]] == [
        ("mock_environment", {"project": project}, "ok")]
    assert result["completion"]["environment_read"] and result["completion"]["complete"]
    assert result["fact_validation"]["grounded"]
    assert result["format_validation"]["requested"] == PROFILES[user]["format"]
    assert len(result["recall_events"][0]["records"]) == 4
    assert result["fact_validation"]["sources"]["stage"]["value"] != result["recall_events"][0]["tag_hints"][0]["tag"]


def test_snapshot_reuse_and_fresh_lookup_keep_stable_prompt_and_tools(tmp_path, monkeypatch):
    requests = []
    with mock_endpoint(web_respond, request_observer=requests.append) as url:
        app = ChatApplication(tmp_path, base_url=url, api_key="offline", model="persona-mock", multi_agent=True)
        sessions = ChatSessions(app)
        session = sessions.create("alice")
        args = (session["session_id"], session["session_token"])
        first = sessions.ask(*args, QUESTION)
        assert "prototype" in first["answer"]
        monkeypatch.setitem(ENVIRONMENTS, "atlas", {**ENVIRONMENTS["atlas"], "stage": "pilot"})
        snapshot = sessions.ask(*args, "이전 조회 당시 프로젝트 이름과 진행 단계를 알려주세요")
        assert "prototype" in snapshot["answer"] and "현재 상태 미확인" in snapshot["answer"]
        assert snapshot["tool_calls"] == snapshot["delegations"] == []
        assert snapshot["fact_validation"]["sources"]["stage"]["source"] == "session-environment:atlas"
        greeting = sessions.ask(*args, "안녕하세요")
        assert greeting["tool_calls"] == greeting["delegations"] == []
        identity = sessions.ask(*args, "제 프로젝트 이름을 알려주세요")
        assert "atlas" in identity["answer"] and identity["tool_calls"] == []
        current = sessions.ask(*args, QUESTION)
        assert "pilot" in current["answer"] and "prototype" not in current["answer"]
        assert len(current["tool_calls"]) == 1
    systems = [[m["content"] for m in r["messages"] if m["role"] == "system"] for r in requests]
    assert all(system == systems[0] for system in systems)
    assert all(r["tools"] == requests[0]["tools"] for r in requests)
    assert requests[0]["tool_choice"]["function"]["name"] == "mock_environment"


def bad_fact_model(project="atlas", *, skip_tool=False):
    def respond(messages):
        boundary = max(i for i, m in enumerate(messages) if m["role"] == "user")
        if not skip_tool and not any(m["role"] == "tool" for m in messages[boundary + 1:]):
            return {"role": "assistant", "content": None, "tool_calls": [
                {"id": "env", "type": "function", "function": {"name": "mock_environment",
                 "arguments": json.dumps({"project": project})}}]}, "tool_calls"
        return {"role": "assistant", "content": "프로젝트 이름: hermes-agent\n현재 진행 단계: delivery / 배달 확인 선호"}, "stop"
    return respond


def test_wrong_model_facts_are_audited_and_not_persisted_as_session_answer(tmp_path):
    with mock_endpoint(bad_fact_model()) as url:
        app = ChatApplication(tmp_path, base_url=url, api_key="offline", model="persona-mock", multi_agent=True)
        sessions = ChatSessions(app)
        session = sessions.create("alice")
        result = sessions.ask(session["session_id"], session["session_token"], QUESTION)
        assert "hermes-agent" in result["raw_answer"]  # Keep original evidence of the model failure.
        assert "hermes-agent" not in result["answer"] and "delivery" not in result["answer"]
        assert "atlas" in result["answer"] and "prototype" in result["answer"]
        assert set(result["fact_validation"]["issues"]) == {
            "project_value_not_grounded_in_profile", "stage_value_not_grounded_in_environment",
            "preference_presented_as_environment_fact"}
        row = sessions.owned(session["session_id"], session["session_token"])
        assert json.loads(row[3])[-1]["content"] == result["answer"]
        assert result["quality"]["fact_grounding"]["grounded"]


def test_model_ignoring_required_tool_cannot_claim_current_stage(tmp_path):
    requests = []
    with mock_endpoint(bad_fact_model(skip_tool=True), request_observer=requests.append) as url:
        app = ChatApplication(tmp_path, base_url=url, api_key="offline", model="persona-mock", multi_agent=True)
        seed(app.store)
        result = app.chat(Principal("alice", SCOPES), "alice", QUESTION)
    assert requests[0]["tool_choice"]["function"]["name"] == "mock_environment"
    assert result["tool_calls"] == []
    assert "미확인" in result["answer"] and "prototype" not in result["answer"]
    assert not result["completion"]["complete"]
    assert "missing_environment_evidence" in result["fact_validation"]["issues"]


@pytest.mark.parametrize("failure", ["foreign_project", "missing_permission", "backend_error", "missing_stage"])
def test_environment_failure_is_unknown_without_leaking_or_guessing(tmp_path, monkeypatch, failure):
    if failure in {"backend_error", "missing_stage"}:
        def unavailable(self, principal, project):
            if failure == "backend_error":
                raise TimeoutError("fixture unavailable")
            return {"project": project}
        monkeypatch.setattr(MockEnterpriseData, "environment", unavailable)
    project = "beacon" if failure == "foreign_project" else "atlas"
    with mock_endpoint(bad_fact_model(project)) as url:
        app = ChatApplication(tmp_path, base_url=url, api_key="offline", model="persona-mock", multi_agent=True)
        seed(app.store)
        scopes = SCOPES - {"environment:read"} if failure == "missing_permission" else SCOPES
        result = app.chat(Principal("alice", scopes), "alice", QUESTION)
    assert "atlas" in result["answer"] and "미확인" in result["answer"]
    assert not result["completion"]["complete"]
    assert "prototype" not in result["answer"] and "review" not in result["answer"]
    assert "delivery" not in result["answer"] and "beacon" not in result["answer"]
    if failure in {"foreign_project", "missing_permission"}:
        assert result["tool_calls"][0]["status"] == "denied"


def test_memory_cannot_override_profile_and_unobserved_history_is_unknown(tmp_path):
    with mock_endpoint(bad_fact_model(skip_tool=True)) as url:
        app = ChatApplication(tmp_path, base_url=url, api_key="offline", model="persona-mock", multi_agent=True)
        sessions = ChatSessions(app)
        actor = Principal("alice", SCOPES)
        app.store.save_semantic(actor, "alice", {"format": "bullets", "project": "hermes-agent", "stage": "delivery"})
        app.store.append(actor, "alice", "fixture", "프로젝트 이름 진행 단계", "프로젝트=hermes-agent 단계=delivery", confirmed=True)
        session = sessions.create("alice")
        result = sessions.ask(session["session_id"], session["session_token"], "제 프로젝트 이름을 알려주세요")
        assert "atlas" in result["answer"] and "hermes-agent" not in result["answer"]
        assert result["tool_calls"] == []
        history = sessions.ask(session["session_id"], session["session_token"], "이전 조회 당시 진행 단계를 알려주세요")
        assert "미확인" in history["answer"] and history["tool_calls"] == []
        assert not history["fact_validation"]["grounded"]
