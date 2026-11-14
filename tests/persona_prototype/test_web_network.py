"""Offline Codespaces/Codex gates and real-mode wiring with a stubbed HTTP send."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from persona_prototype import web_backend
from persona_prototype.mini_validation import ENDPOINT, MODEL
from persona_prototype.web_mock import web_respond


CODESPACES = {"CODESPACES": "true", "CODESPACE_NAME": "fixture-codespace"}


def test_codespaces_without_codex_policy_does_not_create_one(tmp_path):
    path = tmp_path / "absent-codex" / "network-policy.json"
    assert web_backend.check_real_network(CODESPACES, path) == "github-codespaces"
    assert not path.parent.exists()
    with pytest.raises(RuntimeError):
        web_backend.check_real_network({}, path)
    with pytest.raises(RuntimeError):
        web_backend.check_real_network({"CODESPACES": "true"}, path)
    path.parent.mkdir()
    with pytest.raises(RuntimeError):
        web_backend.check_real_network(CODESPACES, path)  # Missing policy in a Codex installation.


@pytest.mark.parametrize("contents,allowed", [
    ('{"type":"restricted","egress_rules":[{"host":"api.openai.com"}]}', True),
    ('{"type":"restricted","egress_rules":[]}', False),
    ('{"type":"disabled"}', False),
    ('not json', False),
    ('[]', False),
])
def test_codex_policy_takes_precedence_over_codespaces(tmp_path, contents, allowed):
    path = tmp_path / "network-policy.json"
    path.write_text(contents)
    if allowed:
        assert web_backend.check_real_network(CODESPACES, path) == "codex"
    else:
        with pytest.raises(RuntimeError):
            web_backend.check_real_network(CODESPACES, path)


@pytest.fixture
def offline_codespaces(monkeypatch, tmp_path):
    for name, value in {**CODESPACES, "PERSONA_BASE_URL": ENDPOINT,
                        "PERSONA_MODEL": MODEL, "PERSONA_API_KEY": "fixture-only"}.items():
        monkeypatch.setenv(name, value)
    check = web_backend.check_real_network
    monkeypatch.setattr(web_backend, "check_real_network",
                        lambda env: check(env, tmp_path / "absent-codex" / "network-policy.json"))
    sent = []
    original = httpx.Client.post

    def post(client, url, **kwargs):
        if str(url) != ENDPOINT + "/chat/completions":
            return original(client, url, **kwargs)
        assert client.headers["Authorization"] == "Bearer fixture-only"
        assert not client.follow_redirects
        sent.append(kwargs["json"])
        message, finish = web_respond(kwargs["json"]["messages"])
        return httpx.Response(200, json={"id": "offline", "created": 1, "model": MODEL,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20}})

    monkeypatch.setattr(httpx.Client, "post", post)
    return sent


def test_real_codespaces_wiring_keeps_shared_budget_and_usage(tmp_path, offline_codespaces):
    with TestClient(web_backend.create_app(tmp_path, mode="real", dev_mode=True)) as client:
        assert offline_codespaces == []  # Startup never probes a paid endpoint.
        sessions = [client.post("/dev/sessions", json={"user": user}).json()
                    for user in ("alice", "bob", "carol")]
        for i in range(13):
            session = sessions[i % 3]
            response = client.post(f'/sessions/{session["session_id"]}/messages',
                headers={"Authorization": "Bearer " + session["session_token"]}, json={"message": "안녕하세요"})
            assert response.status_code == (200 if i < 12 else 429)
        health = client.get("/health").json()
        assert health["remaining_calls"] == 0
        assert health["usage"]["reported_input_tokens"] == 1200
        assert health["usage"]["estimated_usd"] == (1200 * .15 + 240 * .60) / 1_000_000
    assert len(offline_codespaces) == 12
    assert all(b["model"] == MODEL and b["max_tokens"] == 512 and not b["stream"]
               for b in offline_codespaces)
    saved = (tmp_path / "usage.json").read_text()
    assert "fixture-only" not in saved
    assert len(json.loads(saved)["calls"]) == 12


@pytest.mark.parametrize("failure", [403, 429, "transport"])
def test_codespaces_network_and_api_failure_stop_without_retry(monkeypatch, tmp_path, offline_codespaces, failure):
    original = httpx.Client.post
    sent = []
    def post(client, url, **kwargs):
        if str(url) != ENDPOINT + "/chat/completions":
            return original(client, url, **kwargs)
        sent.append(1)
        if failure == "transport":
            raise httpx.ConnectError("fixture platform egress denied")
        return httpx.Response(failure, json={})
    monkeypatch.setattr(httpx.Client, "post", post)
    with TestClient(web_backend.create_app(tmp_path, mode="real", dev_mode=True)) as client:
        session = client.post("/dev/sessions", json={"user": "alice"}).json()
        url = f'/sessions/{session["session_id"]}/messages'
        headers = {"Authorization": "Bearer " + session["session_token"]}
        client.post(url, headers=headers, json={"message": "안녕하세요"})
        assert client.post(url, headers=headers, json={"message": "다시"}).status_code == 429
        health = client.get("/health").json()
        assert health["stopped"] and health["usage"]["upstream_attempts"] == 1
        assert health["usage"]["estimated_usd"] is None
    assert sent == [1]


@pytest.mark.parametrize("name,value", [("PERSONA_API_KEY", ""), ("PERSONA_MODEL", "other"),
                                        ("PERSONA_BASE_URL", "https://example.com/v1")])
def test_real_settings_reject_before_send(monkeypatch, tmp_path, offline_codespaces, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises((RuntimeError, ValueError)), TestClient(web_backend.create_app(tmp_path, mode="real")):
        pass
    assert offline_codespaces == []


def test_default_mock_never_checks_network_or_sends_to_openai(monkeypatch, tmp_path, offline_codespaces):
    def unexpected(env):
        raise AssertionError("Mock must not enter the real-mode network gate")
    monkeypatch.setattr(web_backend, "check_real_network", unexpected)
    with TestClient(web_backend.create_app(tmp_path)) as client:
        assert client.get("/health").json()["mode"] == "mock"
    assert offline_codespaces == []
