"""Behavioral integration tests through the actual Hermes loop and local model HTTP API."""
import pytest

from persona_prototype.app import ChatApplication, SCOPES, seed
from persona_prototype.domain import Principal
from persona_prototype.mock_llm import mock_endpoint
from persona_prototype.provider import PersonaMemoryProvider


@pytest.fixture
def app(tmp_path):
    with mock_endpoint() as url:
        instance = ChatApplication(tmp_path, base_url=url, api_key="mock-only", model="persona-mock")
        seed(instance.store)
        yield instance


def actor(user):
    return Principal(user, SCOPES)


def test_same_question_uses_persona_and_confirmed_memory(app):
    question = "현재 프로젝트 계획을 어떻게 진행하면 좋을까요?"
    outcomes = {user: app.chat(actor(user), user, question) for user in ("alice", "bob", "carol")}
    assert outcomes["alice"]["answer"].startswith("- ")
    assert "| 프로젝트 |" in outcomes["bob"]["answer"]
    assert "단계별 안내" in outcomes["carol"]["answer"]
    for user, tag, project in [("alice", "delivery", "atlas"), ("bob", "risk", "beacon"),
                               ("carol", "onboarding", "cedar")]:
        result = outcomes[user]
        calls = {c["tool"]: c for c in result["tool_calls"]}
        assert calls["mock_rag"]["args"]["tag"] == tag
        assert calls["mock_environment"]["args"]["project"] == project
        assert calls["mock_rag"]["result"]
        assert all(d["tag"] == tag for d in calls["mock_rag"]["result"])
        assert "[doc-" in result["answer"]
        saved = app.store.search(actor(user), user, question)
        assert any(row["session_id"] == result["session_id"] and not row["confirmed"] for row in saved)


def test_memory_change_alters_search_without_changing_profile(app):
    before = app.chat(actor("alice"), "alice", "프로젝트 계획")
    app.store.append(actor("alice"), "alice", "feedback", "프로젝트 계획", "focus=risk", confirmed=True)
    after = app.chat(actor("alice"), "alice", "프로젝트 계획")
    assert before["persona"] == after["persona"]
    assert next(c for c in after["tool_calls"] if c["tool"] == "mock_rag")["args"]["tag"] == "risk"
    assert next(c for c in before["tool_calls"] if c["tool"] == "mock_rag")["args"]["tag"] == "delivery"


def test_semantic_update_changes_next_session_persona(app):
    app.store.save_semantic(actor("alice"), "alice", {"format": "table"})
    assert "| 프로젝트 |" in app.chat(actor("alice"), "alice", "프로젝트 계획")["answer"]


def test_owner_and_scope_checks_and_memory_isolation(app):
    for operation in [lambda: app.store.semantic(actor("alice"), "bob"),
                      lambda: app.store.search(actor("alice"), "bob", "프로젝트"),
                      lambda: app.store.append(actor("alice"), "bob", "x", "q", "r"),
                      lambda: app.store.save_semantic(actor("alice"), "bob", {}),
                      lambda: app.chat(actor("alice"), "bob", "프로젝트")]:
        with pytest.raises(PermissionError):
            operation()
    with pytest.raises(PermissionError):
        app.store.semantic(Principal("alice", frozenset()), "alice")
    provider = PersonaMemoryProvider(app.store, actor("alice"))
    provider.initialize("test")
    assert "Access denied" in provider.handle_tool_call("mock_environment", {"project": "beacon"})
    assert "Invalid tool arguments" in provider.handle_tool_call("persona_recall", {"query": "x", "user_id": "bob"})
    assert all("focus=delivery" in r["response"] for r in app.store.search(actor("alice"), "alice", "프로젝트"))
    restricted = PersonaMemoryProvider(app.store, Principal("alice", frozenset({"memory:read"})))
    restricted.initialize("test")
    assert "Access denied" in restricted.handle_tool_call("mock_rag", {"query": "計画", "tag": "risk"})


def test_persistence_seed_idempotence_and_child_no_writes(app):
    seed(app.store)
    with app.store.connect() as db:
        assert db.execute("SELECT count(*) FROM episodes").fetchone()[0] == 15
    from persona_prototype.store import MemoryStore
    reopened = MemoryStore(app.store.path, app.store.authorizer)
    assert reopened.semantic(actor("bob"), "bob")["format"] == "table"
    assert reopened.search(actor("bob"), "bob", "프로젝트")
    provider = PersonaMemoryProvider(reopened, actor("bob"))
    provider.initialize("child", agent_context="subagent")
    provider.sync_turn("child-only-query", "not a user preference")
    assert reopened.search(actor("bob"), "bob", "child-only-query") == []


def test_concurrent_memory_writers_remain_scoped(app):
    from concurrent.futures import ThreadPoolExecutor

    def write_and_read(user):
        app.store.append(actor(user), user, "parallel", "unique-marker", user)
        return app.store.search(actor(user), user, "unique-marker")

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(write_and_read, ["alice", "bob", "carol"]))
    for user, rows in zip(["alice", "bob", "carol"], results):
        assert len(rows) == 1
        assert rows[0]["response"] == user
