"""Real Hermes sessions through FastAPI; deterministic model, no remote LLM calls."""
from fastapi.testclient import TestClient

from persona_prototype.web_backend import create_app, PersistentBudget
from persona_prototype.quality import quality_review


def create(client, user="alice"):
    response = client.post("/dev/sessions", json={"user": user})
    assert response.status_code == 200
    value = response.json()
    return value, {"Authorization": "Bearer " + value["session_token"]}


def test_sessions_history_feedback_and_cross_user_denial(tmp_path):
    application = create_app(tmp_path, mode="mock", dev_mode=True)
    with TestClient(application) as client:
        alice, headers = create(client)
        bob, bob_headers = create(client, "bob")
        sid = alice["session_id"]
        first = client.post(f"/sessions/{sid}/messages", headers=headers, json={"message": "제 업무 코드는 R-42입니다. 기억해주세요."})
        assert first.status_code == 200, first.text
        second = client.post(f"/sessions/{sid}/messages", headers=headers, json={"message": "앞서 알려준 코드는 무엇인가요?"})
        assert "R-42" in second.json()["answer"]
        assert first.json()["session_id"] == second.json()["session_id"] == sid
        assert len(client.get(f"/sessions/{sid}", headers=headers).json()["turns"]) == 2
        assert client.get(f"/sessions/{sid}", headers=bob_headers).status_code == 403
        assert client.post(f"/dev/sessions/{sid}/resume", json={"user": "bob"}).status_code == 403
        assert client.post(f"/sessions/{sid}/messages", headers=bob_headers, json={"message": "코드"}).status_code == 403
        assert client.get(f'/sessions/{bob["session_id"]}', headers=bob_headers).json()["turns"] == []
        feedback = client.post(f"/sessions/{sid}/feedback", headers=headers, json={
            "turn_id": second.json()["turn_id"], "rating": "helpful", "comment": "대화 맥락이 유지됩니다."})
        assert feedback.json() == {"saved": True, "used_for_alignment": False}
        with application.state.sessions.app.store.connect() as db:
            assert db.execute("SELECT count(*) FROM web_feedback").fetchone()[0] == 1
    # Restarting the backend preserves the session and history, not a live process object.
    with TestClient(create_app(tmp_path, mode="mock", dev_mode=True)) as client:
        assert len(client.get(f"/sessions/{sid}", headers=headers).json()["turns"]) == 2
        third = client.post(f"/sessions/{sid}/messages", headers=headers, json={"message": "이전 코드를 다시 알려주세요."})
        assert "R-42" in third.json()["answer"]
        listed = client.get("/dev/sessions?user=alice").json()
        assert {r["session_id"] for r in listed} == {sid}


def test_all_users_persona_complex_then_simple_and_frozen_persona(tmp_path):
    application = create_app(tmp_path, mode="mock", dev_mode=True)
    with TestClient(application) as client:
        for user, project in [("alice", "atlas"), ("bob", "beacon"), ("carol", "cedar")]:
            session, headers = create(client, user)
            sid = session["session_id"]
            response = client.post(f"/sessions/{sid}/messages", headers=headers,
                                   json={"message": "현재 프로젝트 계획을 조사 분석 검증해 주세요."})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["completion"]["complete"], result["delegations"]
            assert result["quality"]["korean_present"]
            assert not result["quality"]["possible_environment_contradiction"]
            assert result["quality"]["source_ids"]
            assert project in result["answer"]
            if user == "alice":
                from persona_prototype.domain import Principal
                from persona_prototype.app import SCOPES
                application.state.sessions.app.store.save_semantic(Principal(user, SCOPES), user, {"format": "table"})
            followup = client.post(f"/sessions/{sid}/messages", headers=headers, json={"message": "안녕하세요"}).json()
            assert followup["delegations"] == []
            assert followup["persona"] == session["persona"]
            assert followup["format_validation"]["requested"] == session["persona"]["format"]


def test_dev_identity_disabled_by_default(tmp_path):
    with TestClient(create_app(tmp_path, mode="mock")) as client:
        assert client.post("/dev/sessions", json={"user": "alice"}).status_code == 403


def test_budget_survives_restart_and_does_not_store_key(tmp_path):
    path = tmp_path / "usage.json"
    seen = []
    def send(body):
        seen.append(body)
        assert path.exists()  # Reservation precedes actual sending.
        return 200, {"usage": {"prompt_tokens": 100, "completion_tokens": 10}}
    budget = PersistentBudget(send, path)
    budget.forward({"messages": []})
    restored = PersistentBudget(send, path)
    assert len(restored.calls) == 1
    assert restored.totals()["reported_input_tokens"] == 100
    assert "Authorization" not in path.read_text(encoding="utf-8")
    restored.calls *= 12
    restored.forward({"messages": []})
    assert len(seen) == 1


def test_semantic_contradiction_and_format_are_separate():
    from persona_prototype.personalization import format_answer
    raw = "Environment 정보가 없습니다. [doc-1]"
    answer, formatting = format_answer(raw, "table")
    quality = quality_review({"raw_answer": raw, "answer": answer, "role_tool_calls": [
        {"role": "analysis", "status": "ok", "result": {"project": "atlas", "constraint": "작은 단위 배포"}},
        {"role": "research", "status": "ok", "result": [{"id": "doc-1"}]}]})
    assert formatting["fallback_applied"]
    assert quality["possible_environment_contradiction"]
    assert not quality["unsupported_source_ids"]
    assert quality["semantic_review_required"]


def test_complex_request_requires_enough_budget_before_any_model_call(tmp_path):
    from types import SimpleNamespace
    api = create_app(tmp_path, mode="mock", dev_mode=True)
    with TestClient(api) as client:
        session, headers = create(client)
        budget = SimpleNamespace(failed=False, calls=[{}] * 11, limit=12)
        api.state.sessions.budget = budget
        response = client.post(f'/sessions/{session["session_id"]}/messages', headers=headers,
                               json={"message": "프로젝트 계획을 조사 분석 검증해 주세요."})
        assert response.status_code == 429
        assert len(budget.calls) == 11


def test_missing_search_results_are_not_global_absence(tmp_path):
    from persona_prototype.app import ChatApplication, SCOPES, seed
    from persona_prototype.domain import Principal
    from persona_prototype.multi_agent import MultiAgentProvider
    app = ChatApplication(tmp_path, base_url="http://127.0.0.1:1/v1", api_key="offline", model="persona-mock")
    seed(app.store)
    provider = MultiAgentProvider(app.store, Principal("alice", SCOPES))
    provider.initialize("no-network-test")
    assert provider.evidence()["documents"]["state"] == "not_checked"
    provider.handle_tool_call("mock_rag", {"query": "zzzz", "tag": "delivery"})
    assert provider.evidence()["documents"]["state"] == "not_found_in_search"
    provider.handle_tool_call("mock_environment", {"project": "atlas"})
    assert provider.evidence()["environment"]["state"] == "observed"
