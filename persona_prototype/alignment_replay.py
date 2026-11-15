"""Always-local paired replay with Hermes; isolated fixture memory, fixed environment.

The responder implements deterministic preference following. Scores verify the
prototype plumbing only; they do not estimate GPT-4o mini performance.
"""
import tempfile
from pathlib import Path

from .app import ChatApplication, SCOPES, seed
from .data import ENVIRONMENTS, PROFILES
from .domain import Principal
from .mock_llm import mock_endpoint
from .web_mock import web_respond
from .output_format import format_matches


class MockReplay:
    mode = "mock"

    def __init__(self, responder=web_respond):
        self.responder = responder

    def compare(self, user, baseline, candidate, heldout):
        calls = []
        def observe(body):
            if len(calls) >= 24:
                raise RuntimeError("Local replay call cap reached")
            calls.append(1)
        outcomes = {}
        with tempfile.TemporaryDirectory(prefix="persona-alignment-") as root, mock_endpoint(
                self.responder, request_observer=observe) as url:
            for label, persona in (("before", baseline), ("after", candidate)):
                app = ChatApplication(Path(root) / label, base_url=url, api_key="offline", model="persona-mock",
                                      validation_limits=True, multi_agent=True)
                seed(app.store)
                actor = Principal(user, SCOPES)
                response = app.chat(actor, user, heldout["question"], persona_snapshot=persona)
                facts = app.chat(actor, user, "제 프로젝트 이름과 현재 진행 단계를 알려주세요", persona_snapshot=persona)
                outcomes[label] = measure(response, facts, heldout["preferences"], user)
        before, after = outcomes["before"], outcomes["after"]
        improved = (after["safe"] and before["safe"] and after["score"] > before["score"]
                    and all(after["metrics"].get(k, 0) >= v for k, v in before["metrics"].items()))
        return {**outcomes, "improved": improved, "local_mock_calls": len(calls), "paid_calls": 0,
                "reason": "Improved held-out Mock preference score with safety checks" if improved else "No safe measured improvement"}


def measure(response, facts, target, user):
    events = response["tool_calls"] + response["role_tool_calls"]
    searches = [e for e in events if e["tool"] in {"mock_rag", "persona_research_search"} and e.get("status") == "ok"]
    tags = [e["args"]["tag"] for e in searches]
    metrics = {}
    if "format" in target:
        metrics["format"] = int(response["format_validation"]["requested"] == target["format"]
                                and format_matches(response["answer"], target["format"]))
    if "focus" in target:
        metrics["search_focus"] = int(bool(tags) and all(t == target["focus"] for t in tags))
    project = PROFILES[user]["project"]
    source = facts["fact_validation"].get("sources", {})
    safe = (not response["loop_error"] and not facts["loop_error"]
            and response["completion"].get("complete", False)
            and source.get("project", {}).get("value") == project
            and source.get("stage", {}).get("value") == ENVIRONMENTS[project]["stage"]
            and facts["fact_validation"].get("grounded", False)
            and all(e.get("status") not in {"denied", "backend_error", "invalid_arguments"} for e in events))
    return {"metrics": metrics, "score": sum(metrics.values()) / max(1, len(metrics)), "safe": safe,
            "persona": response["persona"], "search_tags": tags,
            "tools": [{"tool": e["tool"], "args": e["args"], "status": e.get("status")} for e in events],
            "answer": response["answer"], "raw_answer": response["raw_answer"],
            "format_validation": response["format_validation"], "facts": source}
