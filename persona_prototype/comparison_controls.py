"""Check (never rewrite) model-visible controls before forwarding a paired request."""
import hashlib
import json
import re
from contextlib import contextmanager


def request_fingerprint(body):
    def normalize(match):
        persona = json.loads(match[1])
        persona["format"] = "<variable>"
        persona["focus"] = "<variable>"
        return "PERSONA_JSON=" + json.dumps(persona, sort_keys=True)
    systems = [re.sub(r"PERSONA_JSON=([^\n]+)", normalize, m.get("content", ""))
               for m in body["messages"] if m["role"] == "system"]
    controls = {"systems": systems, **{k: body.get(k) for k in (
        "tools", "tool_choice", "model", "temperature", "top_p", "seed", "max_tokens", "stream")}}
    return hashlib.sha256(json.dumps(controls, sort_keys=True).encode()).hexdigest()


@contextmanager
def paired_request_guard(budget):
    original = budget.send
    baseline, rounds = {}, {}
    audit = {"consistent": True, "requests_checked": 0, "requests_forwarded": 0, "normalized_fields": ["format", "focus"],
             "baseline_fingerprints": baseline, "rewrites_model_requests": False}

    def send(body):
        users = "\n".join(str(m.get("content", "")) for m in body["messages"] if m["role"] == "user")
        role = "research" if "[PERSONA_ROLE=research]" in users else "main"
        counter = (budget.case, role)
        rounds[counter] = rounds.get(counter, 0) + 1
        key = role + ":" + str(rounds[counter])
        signature = request_fingerprint(body)
        if budget.case.endswith(":v1"):
            baseline[key] = signature
        elif signature != baseline.get(key):
            audit["consistent"] = False
            raise ValueError("Non-preference request controls changed; no forwarding")
        audit["requests_checked"] += 1
        audit["requests_forwarded"] += 1
        return original(body)

    budget.send = send
    try:
        yield audit
    finally:
        budget.send = original
