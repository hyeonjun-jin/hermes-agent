"""Relevant automatic recall, bilingual retrieval, provenance and controlled interventions."""
import json
import re

from persona_prototype.app import ChatApplication, SCOPES, seed
from persona_prototype.domain import Principal
from persona_prototype.mock_llm import mock_endpoint
from persona_prototype.provider import PersonaMemoryProvider
from persona_prototype.personalization import format_answer


def test_prefetch_relevance_isolation_and_tag_validation(tmp_path):
    from persona_prototype.store import MemoryStore
    from persona_prototype.domain import OwnerOnly
    store = MemoryStore(tmp_path / "memory.sqlite", OwnerOnly())
    seed(store)
    for user, focus in [("alice", "delivery"), ("bob", "risk"), ("carol", "onboarding")]:
        provider = PersonaMemoryProvider(store, Principal(user, SCOPES))
        provider.initialize("test")
        context = json.loads(provider.prefetch("current project plan"))
        assert len(context["episodic_records"]) == 4
        assert {h["tag"] for h in context["tag_hints"]} == {focus}
        assert provider.prefetch("unrelated astronomy") == ""
        invalid = json.loads(provider.handle_tool_call("mock_rag", {"query": "project plan", "tag": "atlas"}))
        assert invalid["code"] == "invalid_tag"
        english = json.loads(provider.handle_tool_call("mock_rag", {"query": "current project plan", "tag": focus}))
        assert english["result"]
        assert provider.trace[-1]["tag_sources"]
        assert json.loads(provider.handle_tool_call("mock_rag", {"query": "zzzz", "tag": focus}))["result"] == []
        assert provider.trace[-1]["status"] == "empty"


def test_format_fallback_preserves_content_without_llm():
    raw = "검증 근거 [doc-3]\n위험 | 관리"
    bullets, audit = format_answer(raw, "bullets")
    assert all(line.startswith("- ") for line in bullets.splitlines())
    assert "[doc-3]" in bullets and audit["fallback_applied"]
    mixed, _ = format_answer("설명\n- 이미 목록", "bullets")
    assert mixed == "- 설명\n- 이미 목록"
    table, audit = format_answer(raw, "table")
    assert table.startswith("| 내용 |\n|---|\n")
    assert "위험 \\| 관리" in table and audit["fallback_applied"]
    assert format_answer(raw, "explanation")[0] == raw


def test_prefetch_reaches_actual_model_request_and_only_memory_changes_behavior(tmp_path):
    requests = []
    def responder(messages):
        system = "\n".join(str(m.get("content", "")) for m in messages if m["role"] == "system")
        persona = json.loads(re.search(r'PERSONA_JSON=(\{[^\n]+\})', system)[1])
        user_context = "\n".join(str(m.get("content", "")) for m in messages if m["role"] == "user")
        start = user_context.index('{"episodic_records":')
        memory, _ = json.JSONDecoder().raw_decode(user_context[start:])
        requests.append({"system": system, "persona": persona, "memory": memory})
        tools = [json.loads(m["content"])["result"] for m in messages if m["role"] == "tool"]
        if tools:
            return {"role": "assistant", "content": "atlas " + " ".join(
                f'[{d["id"]}] {d["text"]}' for d in tools[0])}, "stop"
        tag = memory["tag_hints"][0]["tag"]
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": "rag", "type": "function", "function": {"name": "mock_rag", "arguments": json.dumps(
                {"query": "current project plan", "tag": tag})}},
            {"id": "env", "type": "function", "function": {"name": "mock_environment", "arguments": json.dumps(
                {"project": persona["project"]})}}]}, "tool_calls"

    outcomes = []
    with mock_endpoint(responder) as url:
        for condition in ("delivery", "risk"):
            app = ChatApplication(tmp_path / condition, base_url=url, api_key="offline", model="persona-mock")
            seed(app.store)
            if condition == "risk":
                with app.store.connect() as db:
                    db.execute("UPDATE episodes SET response=? WHERE user_id=? AND confirmed=1",
                               ("focus=risk 확인된 선호", "alice"))
            outcomes.append(app.chat(Principal("alice", SCOPES), "alice", "현재 프로젝트 계획을 어떻게 진행하면 좋을까요?"))
    a, b = outcomes
    assert a["persona"] == b["persona"]
    assert len({r["system"] for r in requests[:2]}) == 1
    assert len({r["system"] for r in requests[2:]}) == 1
    assert [c["tool"] for c in a["tool_calls"]] == ["mock_rag", "mock_environment"]
    assert a["tool_calls"][1]["result"] == b["tool_calls"][1]["result"]
    assert a["tool_calls"][0]["args"]["tag"] == "delivery"
    assert b["tool_calls"][0]["args"]["tag"] == "risk"
    assert "[doc-1]" in a["answer"] and "[doc-3]" in b["answer"]
    assert a["format_validation"]["fallback_applied"]
    assert a["answer"].startswith("- ") and b["answer"].startswith("- ")
    assert a["recall_events"][0]["mode"] == "prefetch"
