"""Offline validation of the live runner; no external provider or API key is used."""
import json
import sys

import pytest

from persona_prototype import validation
from persona_prototype.app import ChatApplication, SCOPES, seed
from persona_prototype.domain import Principal
from persona_prototype.mock_llm import mock_endpoint
from persona_prototype.provider import PersonaMemoryProvider


def test_missing_config_never_calls_model(tmp_path, monkeypatch):
    for name in validation.REQUIRED:
        monkeypatch.delenv(name, raising=False)
    def forbidden(*args):
        pytest.fail("No model call is permitted without credentials")
    monkeypatch.setattr(validation, "compare", forbidden)
    path = tmp_path / "blocked.json"
    monkeypatch.setattr(sys, "argv", ["validation", "--output", str(path)])
    assert validation.main() == 2
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["status"] == "blocked_configuration"
    assert report["users"] == []
    assert report["quality_verdict"] == "not_evaluated"


@pytest.mark.parametrize("url", ["ftp://host/v1", "https://user:secret@host/v1",
                                     "https://host/v1?key=secret", "http://remote.example/v1"])
def test_endpoint_rejects_credential_urls_and_remote_cleartext(url):
    with pytest.raises(ValueError) as exc:
        validation.real_settings({"PERSONA_BASE_URL": url, "PERSONA_API_KEY": "not-a-real-key",
                                  "PERSONA_MODEL": "fixture"})
    assert "secret" not in str(exc.value)


def test_live_config_is_explicit_and_has_no_mock_fallback():
    settings = {"PERSONA_BASE_URL": "https://example.invalid/v1", "PERSONA_MODEL": "configured-model",
                "PERSONA_API_KEY": "only-a-fixture"}
    assert validation.real_settings(settings) == tuple(settings[k] for k in validation.REQUIRED)


def test_comparison_records_all_users_using_local_fixture_only(tmp_path):
    with mock_endpoint() as url:
        records = validation.compare((url, "offline-fixture", "persona-mock"), tmp_path, validation.QUESTION)
    assert [r["user"] for r in records] == ["alice", "bob", "carol"]
    assert all(r["status"] == "observed" for r in records)
    assert all(r["model_tool_calls"] for r in records)
    assert all(r["observations"]["environment_retrieved"] for r in records)
    assert all(r["observations"]["recalled_memory"] for r in records)
    assert len({r["observations"]["search_arguments"][0]["tag"] for r in records}) == 3


def test_backend_failure_invalid_arguments_and_no_match_are_traced(tmp_path):
    from persona_prototype.store import MemoryStore
    from persona_prototype.domain import OwnerOnly
    from persona_prototype.provider import MockEnterpriseData

    store = MemoryStore(tmp_path / "memory.sqlite", OwnerOnly())
    seed(store)
    class Unavailable(MockEnterpriseData):
        def search(self, *args, **kwargs):
            raise TimeoutError("sensitive upstream credentials must not be returned")
    actor = Principal("alice", SCOPES)
    provider = PersonaMemoryProvider(store, actor, Unavailable())
    provider.initialize("failure-test")
    failure = provider.handle_tool_call("mock_rag", {"query": "project", "tag": "risk"})
    assert json.loads(failure)["code"] == "backend_error"
    assert "sensitive" not in failure
    assert provider.trace[-1]["status"] == "backend_error"
    for name, args in [("unknown_tool", {}), ("persona_recall", []),
                       ("persona_recall", {"query": 123}),
                       ("persona_recall", {"query": "x", "user_id": "bob", "api_key": "secret"})]:
        assert json.loads(provider.handle_tool_call(name, args))["code"] == "invalid_arguments"
        assert "secret" not in json.dumps(provider.trace[-1])
    assert json.loads(provider.handle_tool_call("persona_recall", {"query": "zzzz-no-match"}))["result"] == []
    assert provider.trace[-1]["status"] == "empty"


def test_bad_calls_pass_through_hermes_and_return_evidence(tmp_path):
    def responder(messages):
        results = [m for m in messages if m["role"] == "tool"]
        if not results:
            calls = [("mock_environment", {"project": "beacon"}),
                     ("mock_rag", {"query": "zzzz-no-match", "tag": "not-a-tag"})]
            return {"role": "assistant", "content": None, "tool_calls": [
                {"id": f"bad-{i}", "type": "function", "function": {
                    "name": name, "arguments": json.dumps(args)}} for i, (name, args) in enumerate(calls)]}, "tool_calls"
        contents = [json.loads(m["content"]) for m in results]
        assert any(c.get("code") == "denied" for c in contents)
        assert any(c.get("result") == [] for c in contents)
        return {"role": "assistant", "content": "권한 없는 프로젝트 접근이 거부되었고 검색 근거가 없습니다."}, "stop"

    with mock_endpoint(responder) as url:
        app = ChatApplication(tmp_path, base_url=url, api_key="offline", model="persona-mock")
        seed(app.store)
        result = app.chat(Principal("alice", SCOPES), "alice", "프로젝트 계획")
    assert not result["loop_error"]
    assert {c["status"] for c in result["tool_calls"]} == {"denied", "empty"}
    assert len(result["model_tool_calls"]) == 2
    assert "beacon" not in result["answer"]
    evidence = validation.observations(result)
    assert not evidence["environment_retrieved"]
    assert len(evidence["tool_errors"]) == 1
