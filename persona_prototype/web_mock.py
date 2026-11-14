"""Deterministic development model for UI/HTTP tests, never a fallback for real mode."""
import json
import re

def web_respond(messages):
    system = "\n".join(str(m.get("content", "")) for m in messages if m["role"] == "system")
    index = max(i for i, m in enumerate(messages) if m["role"] == "user")
    user = str(messages[index]["content"])
    tools = [json.loads(m["content"]) for m in messages[index + 1:] if m["role"] == "tool"]
    role = re.search(r"\[PERSONA_ROLE=(research|analysis|verification)\]", user)
    def calls(entries):
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"web-{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
            for i, (n, a) in enumerate(entries)]}, "tool_calls"
    if role:
        from .multi_agent import ROLE_TOOLS
        role = role[1]
        if not tools:
            if role == "research":
                focus = re.search(r'"tag":\s*"(delivery|risk|onboarding)"', user)[1]
                args = {"query": "project plan", "tag": focus}
            elif role == "analysis":
                args = {"project": re.search(r'"project":\s*"([a-z]+)"', user)[1]}
            else:
                args = {}
            return calls([(ROLE_TOOLS[role], args)])
        result = tools[0].get("result", {})
        if role == "research":
            text = "문서 근거: " + " ".join(f'[{d["id"]}] {d["text"]}' for d in result)
        elif role == "analysis":
            text = f'프로젝트 {result["project"]}, 단계 {result["stage"]}, 확인된 제약: {result["constraint"]}.'
        else:
            text = "원문 확인: " + ", ".join(d["id"] for d in result["documents"])
            text += ". Environment는 별도 관측 근거입니다. 상세 일정은 미확인입니다."
        return {"role": "assistant", "content": text}, "stop"
    persona = json.loads(re.search(r'PERSONA_JSON=(\{[^\n]+\})', system)[1])
    if tools and "stages" in tools[0]:
        pack = tools[0]["source_evidence"]
        env = pack["environment"]["items"][0]
        docs = pack["documents"]["items"]
        text = f'{env["project"]}: {env["stage"]}, {env["constraint"]}. '
        text += " ".join(f'[{d["id"]}] {d["text"]}' for d in docs)
        return {"role": "assistant", "content": text + " 상세 일정은 미확인입니다."}, "stop"
    plain = re.sub(r"<memory-context>.*?</memory-context>", "", user, flags=re.DOTALL)
    if all(w in plain for w in ("조사", "분석", "검증")):
        return calls([("delegate_specialist", {"role": "workflow"})])
    prior = " ".join(str(m.get("content", "")) for m in messages[:index] if m["role"] == "user")
    code = re.search(r"R-\d+", prior)
    if code and any(w in plain for w in ("코드", "기억", "앞서")):
        text = "이전 대화에서 알려주신 코드는 " + code[0] + "입니다."
    elif "기억" in plain or "코드" in plain:
        text = "알려주신 내용을 이 대화에서 참고하겠습니다."
    else:
        text = f'안녕하세요. 사용자 프로젝트는 {persona["project"]}입니다.'
    return {"role": "assistant", "content": text}, "stop"
