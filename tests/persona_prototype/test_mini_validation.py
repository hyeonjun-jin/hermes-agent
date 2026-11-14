"""Offline limits/usage tests. No OpenAI calls are made."""
from persona_prototype.mini_validation import Budget, ENDPOINT, MODEL, gateway, run

SETTINGS = {"PERSONA_BASE_URL": ENDPOINT, "PERSONA_MODEL": MODEL, "PERSONA_API_KEY": "fixture-only"}


def test_blocked_network_and_missing_key_never_send(tmp_path):
    report = run(SETTINGS, {"type": "restricted", "egress_rules": []}, tmp_path)
    assert report["status"] == "blocked"
    assert report["totals"]["upstream_attempts"] == 0
    assert report["totals"]["estimated_usd"] == 0
    assert report["users"] == []
    assert report["tool_calling_compatibility"] == "not_tested"
    assert run({}, {"type": "unrestricted"}, tmp_path)["status"] == "blocked"


def test_hard_request_limit_model_and_output_cap():
    sent = []
    def send(body):
        sent.append(body)
        return 200, {"usage": {"prompt_tokens": 100, "completion_tokens": 20}}
    budget = Budget(send)
    for _ in range(4):
        assert budget.forward({"messages": [], "model": "other", "max_tokens": 9999})[0] == 200
    assert budget.forward({"messages": []})[0] == 429
    assert len(sent) == 4
    assert all(b["model"] == MODEL and b["max_tokens"] == 512 and not b["stream"] for b in sent)
    assert budget.totals()["reported_input_tokens"] == 400
    assert budget.totals()["estimated_usd"] == (400 * 0.15 + 80 * 0.60) / 1_000_000


def test_remote_failure_is_not_retried_and_unknown_usage_is_not_zero_cost():
    sent = []
    def send(body):
        sent.append(body)
        return 429, {}
    budget = Budget(send)
    for _ in range(8):
        budget.forward({"messages": []})
    assert len(sent) == 1
    assert budget.totals()["estimated_usd"] is None
    assert not budget.totals()["usage_complete"]


def test_large_input_stops_before_upstream():
    budget = Budget(None)
    assert budget.forward({"messages": ["x" * 65000]})[0] == 400
    assert budget.calls == []


def test_budget_gateway_through_actual_hermes_loop(tmp_path):
    from persona_prototype.app import ChatApplication, SCOPES, seed
    from persona_prototype.domain import Principal
    from persona_prototype.mock_llm import respond
    def send(body):
        message, finish = respond(body["messages"])
        return 200, {"id": "offline", "created": 1, "model": MODEL,
                     "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                     "usage": {"prompt_tokens": 100, "completion_tokens": 20}}
    budget = Budget(send)
    with gateway(budget) as url:
        app = ChatApplication(tmp_path, base_url=url, api_key="local-only", model=MODEL, validation_limits=True)
        seed(app.store)
        result = app.chat(Principal("alice", SCOPES), "alice", "프로젝트 계획")
    assert not result["loop_error"]
    assert "[doc-" in result["answer"]
    assert len(budget.calls) == 3
    assert budget.totals()["reported_input_tokens"] == 300
