"""Native Hermes delegation integration; offline models, real parent and child loops."""
import json
import re

from persona_prototype.app import ChatApplication, SCOPES, seed
from persona_prototype.domain import Principal
from persona_prototype.mock_llm import mock_endpoint
from persona_prototype.multi_agent import ROLE_TOOLS, MultiAgentProvider, RoleScope, _ROLE_SCOPE, role_handler


def specialist_responder(messages):
    users = "\n".join(str(m.get("content", "")) for m in messages if m["role"] == "user")
    role = re.search(r"\[PERSONA_ROLE=(research|analysis|verification)\]", users)
    tools = [m for m in messages if m["role"] == "tool"]
    def calls(entries):
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": "sa-" + str(i), "type": "function", "function": {
                "name": name, "arguments": json.dumps(args)}} for i, (name, args) in enumerate(entries)]}, "tool_calls"
    if role:
        role = role[1]
        if not tools:
            if role == "research":
                return calls([(ROLE_TOOLS[role], {"query": "project plan delivery", "tag": "delivery"})])
            if role == "analysis":
                return calls([(ROLE_TOOLS[role], {"project": "atlas"})])
            return calls([(ROLE_TOOLS[role], {})])
        for m in tools:
            assert "result" in json.loads(m["content"]), m["content"]
        return {"role": "assistant", "content": f"{role}: doc-1 doc-2 근거 확인. atlas 작은 단위 배포. 불확실성: 상세 일정 미제공."}, "stop"
    if "안녕" in users:
        return {"role": "assistant", "content": "안녕하세요."}, "stop"
    if len(tools) < 3:
        return calls([("delegate_specialist", {"role": ["research", "analysis", "verification"][len(tools)]})])
    return {"role": "assistant", "content": "배포 계획 [doc-1], 일정 담당자 [doc-2]. 상세 일정은 미제공입니다."}, "stop"


def test_native_delegate_all_three_roles_and_simple_direct_answer(tmp_path):
    with mock_endpoint(specialist_responder) as url:
        app = ChatApplication(tmp_path / "complex", base_url=url, api_key="offline", model="persona-mock", multi_agent=True)
        seed(app.store)
        result = app.chat(Principal("alice", SCOPES), "alice", "프로젝트 계획을 검토해 주세요.")
        assert not result["loop_error"]
        assert [d["role"] for d in result["delegations"]] == list(ROLE_TOOLS)
        assert result["completion"]["complete"], result["delegations"]
        assert result["completion"]["checked_document_ids"] == ["doc-1", "doc-2"]
        assert {e["role"] for e in result["role_tool_calls"]} == set(ROLE_TOOLS)
        assert all(e["status"] == "ok" for e in result["role_tool_calls"])
        assert result["delegations"][2]["context"]["environment_evidence"][0]["project"] == "atlas"
        verification = next(e for e in result["role_tool_calls"] if e["role"] == "verification")
        assert verification["result"]["environment"][0]["constraint"] == "작은 단위 배포"
        assert {d["id"] for d in verification["result"]["documents"]} == {"doc-1", "doc-2"}
        research_context = result["delegations"][0]["context"]
        assert "profile" not in research_context and "episodes" not in research_context
        assert "confirmation" not in research_context
        assert "[doc-1]" in result["answer"] and "[doc-2]" in result["answer"]
        simple = ChatApplication(tmp_path / "simple", base_url=url, api_key="offline", model="persona-mock", multi_agent=True)
        seed(simple.store)
        direct = simple.chat(Principal("alice", SCOPES), "alice", "안녕하세요")
        assert direct["delegations"] == [] and direct["role_tool_calls"] == []
        assert direct["completion"]["complete"]


def test_role_context_denies_unbound_foreign_home_and_foreign_tools(tmp_path):
    from persona_prototype.store import MemoryStore
    from persona_prototype.domain import OwnerOnly
    from hermes_constants import hermes_home_key
    store = MemoryStore(tmp_path / "memory.sqlite", OwnerOnly())
    seed(store)
    provider = MultiAgentProvider(store, Principal("alice", SCOPES))
    provider.initialize("test")
    assert "denied" in role_handler(ROLE_TOOLS["analysis"], {"project": "atlas"})
    for home, tool in [("other-home", ROLE_TOOLS["research"]), (hermes_home_key(), ROLE_TOOLS["analysis"])]:
        token = _ROLE_SCOPE.set(RoleScope(provider, "research", home))
        try:
            assert "denied" in role_handler(tool, {"project": "beacon"})
        finally:
            _ROLE_SCOPE.reset(token)
    assert "error" in json.loads(provider.role_tool("analysis", {"project": "beacon"}))
    assert "error" in json.loads(provider.role_tool("verification", {"document_id": "doc-3"}))
    assert not provider.finish("unverified [doc-999]")[1]["delegated"]


def test_local_formatting_changes_presentation_not_facts():
    from persona_prototype.personalization import format_answer
    text = "수율 98.2%, 기준 2026-11-15. [doc-1]\n원인 미확정 | 추가 확인 필요."
    bullets, _ = format_answer(text, "bullets")
    assert "\n".join(line.removeprefix("- ") for line in bullets.splitlines()) == text
    table, _ = format_answer(text, "table")
    cell = table.splitlines()[2][2:-2].replace("<br>", "\n").replace("\\|", "|")
    assert cell == text


def test_multi_budget_caps_children_and_stops_after_remote_error(tmp_path):
    from persona_prototype.multi_validation import MultiBudget, run
    sent = []
    def send(body):
        sent.append(body)
        return 200, {"usage": {"prompt_tokens": 3, "completion_tokens": 2}}
    budget = MultiBudget(send)
    body = {"messages": [{"role": "user", "content": "[PERSONA_ROLE=research] Search"}]}
    assert budget.forward(body)[0] == 200
    assert budget.forward(body)[0] == 200
    assert budget.forward(body)[0] == 429
    assert len(sent) == 2 and budget.by_actor == {"complex:research": 2}
    assert budget.calls[0]["actor"] == "complex:research"
    assert run({}, {}, tmp_path)["status"] == "blocked"


def test_verification_cannot_complete_without_evidence_or_all_roles(tmp_path):
    from persona_prototype.store import MemoryStore
    from persona_prototype.domain import OwnerOnly
    store = MemoryStore(tmp_path / "memory.sqlite", OwnerOnly())
    seed(store)
    provider = MultiAgentProvider(store, Principal("alice", SCOPES))
    provider.initialize("test")
    provider.question = "조사 분석 검증"
    assert not provider.finish("완료했습니다.")[1]["complete"]
    assert "error" in json.loads(provider.delegate("verification"))
    provider.delegations.append({"role": "research"})
    assert "error" in json.loads(provider.delegate("research"))
    assert not provider.finish("[doc-999]")[1]["complete"]


def test_main_can_choose_workflow_once_with_real_native_children(tmp_path):
    offered = []
    def responder(messages):
        users = "\n".join(str(m.get("content", "")) for m in messages if m["role"] == "user")
        if "[PERSONA_ROLE=" in users:
            return specialist_responder(messages)
        if any(m["role"] == "tool" for m in messages):
            return {"role": "assistant", "content": "작은 단위 배포 [doc-1], 담당자 확인 [doc-2]. 상세 일정 미확정."}, "stop"
        return {"role": "assistant", "content": None, "tool_calls": [{"id": "wf", "type": "function",
                "function": {"name": "delegate_specialist", "arguments": '{"role":"workflow"}'}}]}, "tool_calls"
    with mock_endpoint(responder, request_observer=offered.append) as url:
        app = ChatApplication(tmp_path, base_url=url, api_key="offline", model="persona-mock", multi_agent=True)
        seed(app.store)
        result = app.chat(Principal("alice", SCOPES), "alice", "프로젝트 계획을 조사 분석 검증해 주세요")
    assert len(result["model_tool_calls"]) == 1
    assert result["completion"]["complete"], result["delegations"]
    assert len(result["delegations"]) == 3
    assert len(offered) == 8
    for request in offered:
        users = "\n".join(str(m.get("content", "")) for m in request["messages"] if m["role"] == "user")
        match = re.search(r"\[PERSONA_ROLE=(research|analysis|verification)\]", users)
        expected = {ROLE_TOOLS[match[1]]} if match else {"delegate_specialist"}
        assert {t["function"]["name"] for t in request["tools"]} == expected
        has_results = any(m["role"] == "tool" for m in request["messages"])
        expected_choice = "none" if has_results else ("required" if match else {
            "type": "function", "function": {"name": "delegate_specialist"}})
        assert request["tool_choice"] == expected_choice


def test_truncated_native_summary_is_not_success():
    from persona_prototype.multi_agent import successful
    assert not successful({"status": "completed", "exit_reason": "max_iterations", "truncated": True})
    assert successful({"status": "completed", "exit_reason": "completed", "truncated": False})


def test_concurrent_role_principals_do_not_cross_project_boundaries(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from persona_prototype.store import MemoryStore
    from persona_prototype.domain import OwnerOnly
    from hermes_constants import hermes_home_key
    store = MemoryStore(tmp_path / "memory.sqlite", OwnerOnly())
    seed(store)
    home = hermes_home_key()
    def execute(user, project, other):
        provider = MultiAgentProvider(store, Principal(user, SCOPES))
        provider.initialize("isolated-" + user)
        token = _ROLE_SCOPE.set(RoleScope(provider, "analysis", home))
        try:
            own = json.loads(role_handler(ROLE_TOOLS["analysis"], {"project": project}))
            foreign = json.loads(role_handler(ROLE_TOOLS["analysis"], {"project": other}))
            return own, foreign
        finally:
            _ROLE_SCOPE.reset(token)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(execute, "alice", "atlas", "beacon")
        b = pool.submit(execute, "bob", "beacon", "atlas")
        for outcome, project in [(a.result(), "atlas"), (b.result(), "beacon")]:
            assert outcome[0]["result"]["project"] == project
            assert "error" in outcome[1]
