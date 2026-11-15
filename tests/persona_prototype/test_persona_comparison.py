"""Offline paired-control checks; the production API adapter is stubbed before any send."""
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from persona_prototype.app import ChatApplication, SCOPES
from persona_prototype.domain import Principal
from persona_prototype.mini_validation import MODEL, ENDPOINT, gateway
from persona_prototype.web_backend import PersistentBudget, create_app
from persona_prototype import web_backend
from persona_prototype.persona_comparison import compare, mock_response, run_mock, run_live
from persona_prototype.comparison_controls import paired_request_guard


def response_for(body):
    message, finish = mock_response(body["messages"])
    return {"id": "offline", "created": 1, "model": MODEL,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


def ledger(path, count):
    path.write_text(json.dumps({"failed": False, "calls": [
        {"attempt": i + 1, "status": 200, "usage": {"prompt_tokens": 5, "completion_tokens": 1}}
        for i in range(count)]}))


def test_mock_pair_changes_only_preference_inputs_and_records_raw_vs_rendered():
    report = run_mock()
    assert report["status"] == "executed", report
    assert report["usage"]["model_attempts"] == 8 and report["usage"]["paid_api_attempts"] == 0
    assert report["usage"]["tokens_are_simulated"] and report["usage"]["estimated_usd"] == 0
    v1, v2 = report["cases"]
    assert v1["initial_inputs"] == v2["initial_inputs"]
    assert v1["input_fingerprint"] == v2["input_fingerprint"]
    assert v1["model_persona"] == {**v2["model_persona"], "format": "bullets", "focus": "delivery"}
    assert all("focus=delivery" in row[3] for row in v2["initial_inputs"]["episodes"])
    assert {d["id"] for d in v1["research_documents"]} == {"doc-1", "doc-2"}
    assert {d["id"] for d in v2["research_documents"]} == {"doc-3"}
    assert v2["research_tool_calls"][0]["args"]["tag"] == "risk"
    assert v2["delegations"][0]["context"]["focus_evidence"][0]["source"] == "approved_persona"
    for case in (v1, v2):
        assert len(case["calls"]) == 4
        assert case["completion"]["roles_run"] == ["research"]
        assert case["environment_observations"][0]["origin"] == "deterministic_harness"
        assert case["metrics"]["environment_matches_fixture"]
        assert not case["metrics"]["raw_format_compliant"]
        assert case["metrics"]["final_format_compliant"] and case["metrics"]["fallback_applied"]
        assert case["metrics"]["semantic_review_required"]
        assert not case["metrics"]["unsupported_citations"]
    assert report["personalization_improvement"] == "not_established"
    assert report["request_controls"]["consistent"] and report["request_controls"]["requests_checked"] == 8


@pytest.mark.parametrize("count", [5, 11, 12])
def test_insufficient_existing_budget_is_not_modified_or_sent(tmp_path, count):
    path = tmp_path / "usage.json"
    ledger(path, count)
    original = path.read_bytes()
    def no_send(body):
        raise AssertionError("No send is allowed when the paired budget is unavailable")
    budget = PersistentBudget(no_send, path)
    app = ChatApplication(tmp_path / "app", base_url="http://127.0.0.1:1/v1", api_key="offline", model=MODEL)
    report = compare(app, budget, mode="real")
    assert report["status"] == "blocked" and report["cases"] == []
    assert path.read_bytes() == original
    assert len(budget.calls) == count


def test_existing_ledger_is_extended_without_reset_and_survives_restart(tmp_path):
    path = tmp_path / "usage.json"
    ledger(path, 4)
    old = json.loads(path.read_text())["calls"]
    sent = []
    def send(body):
        sent.append(body)
        return 200, response_for(body)
    budget = PersistentBudget(send, path)
    with gateway(budget) as url:
        app = ChatApplication(tmp_path / "app", base_url=url, api_key="offline", model=MODEL)
        report = compare(app, budget, mode="mock")
    assert report["status"] == "executed"
    saved = json.loads(path.read_text())
    assert saved["calls"][:4] == old and len(saved["calls"]) == 12
    assert report["ledger_before"]["upstream_attempts"] == 4
    assert report["ledger_after"]["upstream_attempts"] == 12
    assert all(b["model"] == MODEL and b["max_tokens"] == 512 and not b["stream"] for b in sent)
    restored = PersistentBudget(send, path)
    assert len(restored.calls) == 12


@pytest.mark.parametrize("usage", [None, {}])
def test_pending_or_incomplete_usage_blocks_without_touching_ledger(tmp_path, usage):
    path = tmp_path / "usage.json"
    path.write_text(json.dumps({"failed": False, "calls": [{"status": "pending", "usage": usage}]}))
    original = path.read_bytes()
    def no_send(body):
        raise AssertionError("Unknown usage must block")
    budget = PersistentBudget(no_send, path)
    app = ChatApplication(tmp_path / "app", base_url="http://127.0.0.1:1/v1", api_key="offline", model=MODEL)
    assert compare(app, budget, mode="real")["status"] == "blocked"
    assert path.read_bytes() == original


@pytest.mark.parametrize("transport_error", [False, True])
def test_first_external_error_stops_pair_without_retry(tmp_path, transport_error):
    sent = []
    def send(body):
        sent.append(body)
        if transport_error:
            raise httpx.ConnectError("offline egress denial")
        return 429, {}
    path = tmp_path / "usage.json"
    ledger(path, 0)
    budget = PersistentBudget(send, path)
    with gateway(budget) as url:
        app = ChatApplication(tmp_path / "app", base_url=url, api_key="offline", model=MODEL)
        report = compare(app, budget, mode="real")
    assert report["status"] == "incomplete" and len(report["cases"]) == 1
    assert len(sent) == 1 and budget.failed
    assert report["usage"]["estimated_usd"] is None and not report["usage"]["usage_complete"]
    assert json.loads(path.read_text())["failed"]


def test_real_cli_requires_explicit_execute_before_any_backend_request(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("No connection without --execute")
    monkeypatch.setattr(httpx, "Client", unexpected)
    assert run_live("http://127.0.0.1:8001", False)["status"] == "blocked"
    assert run_live("https://example.com", True)["status"] == "blocked"


def test_request_guard_allows_preferences_but_rejects_other_controls_without_rewriting():
    sent = []
    def original(body):
        sent.append(body)
    budget = SimpleNamespace(case="pair:v1", send=original)
    def body(style, focus, version=1):
        return {"messages": [{"role": "system", "content": 'PERSONA_JSON=' + json.dumps(
            {"version": version, "project": "atlas", "format": style, "focus": focus})},
            {"role": "user", "content": "fixed question"}], "tools": []}
    first, second = body("bullets", "delivery"), body("table", "risk")
    saved = json.dumps(second)
    with paired_request_guard(budget) as audit:
        budget.send(first)
        budget.case = "pair:v2"
        budget.send(second)
        assert audit["consistent"] and len(sent) == 2
    assert budget.send is original and json.dumps(second) == saved
    with paired_request_guard(budget) as audit:
        budget.case = "pair:v1"
        budget.send(first)
        budget.case = "pair:v2"
        with pytest.raises(ValueError):
            budget.send(body("table", "risk", version=2))
        assert not audit["consistent"] and len(sent) == 3
        assert audit["requests_forwarded"] == 1
    assert budget.send is original


def test_cli_preflight_never_posts_when_existing_backend_has_insufficient_budget(monkeypatch):
    requests = []
    def handle(request):
        requests.append(request)
        assert request.method == "GET" and request.url.path == "/health"
        return httpx.Response(200, json={"mode": "real", "model": MODEL, "stopped": False,
                                        "remaining_calls": 7, "usage": {"usage_complete": True}})
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)))
    assert run_live("http://127.0.0.1:8001", True)["status"] == "blocked"
    assert len(requests) == 1


def test_real_backend_route_uses_its_existing_ledger_and_keeps_active_persona(tmp_path, monkeypatch):
    for key, value in {"PERSONA_BASE_URL": ENDPOINT, "PERSONA_MODEL": MODEL, "PERSONA_API_KEY": "fixture-only"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(web_backend, "check_real_network", lambda env: "offline-test")
    sent = []
    original = httpx.Client.post
    def post(client, url, **kwargs):
        if str(url) != ENDPOINT + "/chat/completions":
            return original(client, url, **kwargs)
        assert client.headers["Authorization"] == "Bearer fixture-only"
        sent.append(kwargs["json"])
        return httpx.Response(200, json=response_for(kwargs["json"]))
    monkeypatch.setattr(httpx.Client, "post", post)
    ledger(tmp_path / "usage.json", 4)
    api = create_app(tmp_path, mode="real", dev_mode=True)
    with TestClient(api) as client:
        session = client.post("/dev/sessions", json={"user": "alice"}).json()
        headers = {"Authorization": "Bearer " + session["session_token"]}
        path = f'/sessions/{session["session_id"]}/validation/persona-comparison'
        store = api.state.sessions.app.store
        before = store.semantic(Principal("alice", SCOPES), "alice")
        assert client.post(path, headers=headers, json={"confirm": False}).status_code == 422
        bob = client.post("/dev/sessions", json={"user": "bob"}).json()
        assert client.post(f'/sessions/{bob["session_id"]}/validation/persona-comparison',
                           headers={"Authorization": "Bearer " + bob["session_token"]}, json={"confirm": True}).status_code == 403
        assert sent == []
        response = client.post(path, headers=headers, json={"confirm": True})
        assert response.status_code == 200 and response.json()["status"] == "executed"
        assert len(sent) == 8
        assert response.json()["usage"]["input_tokens"] == 800
        assert response.json()["usage"]["estimated_usd"] == (800 * .15 + 160 * .60) / 1_000_000
        assert store.semantic(Principal("alice", SCOPES), "alice") == before
        frozen = (tmp_path / "usage.json").read_bytes()
        assert client.post(path, headers=headers, json={"confirm": True}).json()["status"] == "blocked"
        assert len(sent) == 8 and (tmp_path / "usage.json").read_bytes() == frozen
