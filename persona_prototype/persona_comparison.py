"""Explicit, bounded paired experiment. Mock by default; live calls use the existing backend ledger."""
import argparse
import hashlib
import json
import re
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from openai import OpenAIError

from .app import ChatApplication, SCOPES, seed
from .alignment_replay import format_matches
from .comparison_provider import ComparisonProvider, ENTRYPOINT
from .comparison_controls import paired_request_guard
from .data import PROFILES, ENVIRONMENTS
from .domain import Principal
from .mini_validation import MODEL, ENDPOINT, RATES, gateway
from .multi_validation import MultiBudget
from .web_mock import web_respond

REQUIRED_CALLS = 8
QUESTION = "현재 프로젝트 계획에 필요한 문서를 검색하고, 환경 정보에 맞춘 권고와 근거 문서 ID를 한국어로 알려주세요."
CONDITIONS = (("v1", "bullets", "delivery"), ("v2", "table", "risk"))


def inputs(app):
    actor = Principal("alice", SCOPES)
    with app.store.connect() as db:
        episodes = db.execute("SELECT id,session_id,query,response,confirmed,created_at FROM episodes "
                              "WHERE user_id=? ORDER BY id", ("alice",)).fetchall()
    return {"profile": dict(PROFILES["alice"]), "environment": dict(ENVIRONMENTS["atlas"]),
            "semantic": app.store.semantic(actor, "alice"), "episodes": episodes, "question": QUESTION}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def known_usage(record):
    usage = record.get("usage")
    return isinstance(usage, dict) and all(type(usage.get(key)) is int and usage[key] >= 0
                                          for key in ("prompt_tokens", "completion_tokens"))


def summarize(label, result, snapshot, calls):
    raw, answer = result["raw_answer"], result["answer"]
    searches = [e for e in result["role_tool_calls"] if e["role"] == "research"]
    documents = [d for e in searches if e.get("status") == "ok" for d in e["result"]]
    environment = [e["result"] for e in result["tool_calls"] if e.get("status") == "ok"]
    checked = result["completion"]["checked_document_ids"]
    cited = sorted(set(re.findall(r"\bdoc-\d+\b", raw)))
    metrics = {"raw_format_compliant": format_matches(raw, result["persona"]["format"]),
               "final_format_compliant": format_matches(answer, result["persona"]["format"]),
               "fallback_applied": result["format_validation"]["fallback_applied"],
               "cited_document_ids": cited, "citations_present": bool(cited), "checked_document_ids": checked,
               "unsupported_citations": sorted(set(cited) - set(checked)),
               "expected_project_literal_present": snapshot["profile"]["project"] in raw,
               "expected_stage_literal_present": snapshot["environment"]["stage"] in raw,
               "environment_matches_fixture": environment == [snapshot["environment"]],
               "preference_as_stage_flag": bool(re.search(r"(?:단계|stage)\s*[:：=][^\n]*(?:delivery|risk|선호)", raw)),
               "semantic_review_required": True,
               "note": "Literal/format/source checks are indicators, not proof of semantic correctness."}
    names = [t["function"]["name"] for t in result["model_tool_calls"]]
    complete = (result["completion"]["complete"] and not result["loop_error"]
                and names.count(ENTRYPOINT) == 1 and metrics["environment_matches_fixture"])
    return {"condition": label, "source_persona_version_label": 1 if label == "v1" else 2,
            "model_persona": result["persona"], "input_fingerprint": fingerprint(snapshot),
            "initial_inputs": snapshot, "recall_events": result["recall_events"],
            "main_model_tool_calls": result["model_tool_calls"], "research_tool_calls": searches,
            "research_documents": documents, "delegations": result["delegations"],
            "environment_observations": result["tool_calls"], "raw_answer": raw, "final_answer": answer,
            "metrics": metrics, "completion": result["completion"], "complete": bool(complete), "calls": calls}


def compare(application, budget, *, mode):
    """Called under ChatSessions.lock for live use; no ledger is created or reset here."""
    before = budget.totals()
    report = {"mode": mode, "model": MODEL, "endpoint": ENDPOINT, "status": "blocked", "cases": [],
              "ledger_before": before, "pricing": RATES, "question": QUESTION,
              "limits": {"required_remaining": REQUIRED_CALLS, "experiment_max": 8, "ledger_cap": 12,
                         "per_variant_main": 2, "per_variant_research": 2, "output_tokens": 512, "retries": 0},
              "scope": "Main + native Research; Environment/original checks are code, not Analysis/Verification agents",
              "controls": "Only format/focus differ; model-visible version metadata fixed at 1; fresh identical Memory copies",
              "semantic_review_required": True, "personalization_improvement": "not_established"}
    if (budget.failed or not before["usage_complete"] or budget.limit != 12 or budget.main_limit != 2
            or application.model != MODEL or any(not known_usage(c) for c in budget.calls)
            or budget.limit - len(budget.calls) < REQUIRED_CALLS):
        report["reason"] = "Need eight remaining calls in the existing healthy, complete 12-call ledger"
        report["ledger_after"] = before
        return report
    start = len(budget.calls)
    run_id = uuid.uuid4().hex
    with paired_request_guard(budget) as controls, tempfile.TemporaryDirectory(prefix="persona-paired-") as root:
        template = ChatApplication(Path(root) / "template", base_url=application.base_url,
                                   api_key=application.api_key, model=application.model,
                                   authorizer=application.store.authorizer)
        seed(template.store)
        reference = inputs(template)
        app = ChatApplication(Path(root) / "condition", base_url=application.base_url, api_key=application.api_key,
                              model=application.model, validation_limits=True, multi_agent=True,
                              provider_class=ComparisonProvider, authorizer=application.store.authorizer)
        for label, style, focus in CONDITIONS:
            budget.case = "persona-pair:" + run_id + ":" + label
            offset = len(budget.calls)
            with template.store.connect() as source, app.store.connect() as target:
                source.backup(target)
            snapshot = inputs(app)
            if fingerprint(snapshot) != fingerprint(reference):
                report["reason"] = "Controlled inputs changed; refusing the next condition"
                break
            persona = {"version": 1, "project": "atlas", "language": "ko", "format": style, "focus": focus}
            try:
                result = app.chat(Principal("alice", SCOPES), "alice", QUESTION, persona_snapshot=persona)
                row = summarize(label, result, snapshot, budget.calls[offset:])
            except (OSError, ValueError, RuntimeError, httpx.HTTPError, OpenAIError) as exc:
                row = {"condition": label, "complete": False, "error_type": type(exc).__name__}
            report["cases"].append(row)
            if budget.failed or not row["complete"]:
                break
    after = budget.totals()
    used = len(budget.calls) - start
    known = budget.calls[start:]
    complete_usage = all(known_usage(c) for c in known)
    tokens_in = sum(c["usage"].get("prompt_tokens", 0) for c in known if c.get("usage"))
    tokens_out = sum(c["usage"].get("completion_tokens", 0) for c in known if c.get("usage"))
    report.update(ledger_after=after, calls=known, request_controls=controls,
                  usage={"ledger_reservations": used, "model_attempts": controls["requests_forwarded"],
                         "paid_api_attempts": controls["requests_forwarded"] if mode == "real" else 0,
                         "input_tokens": tokens_in, "output_tokens": tokens_out,
                         "usage_complete": complete_usage, "tokens_are_simulated": mode != "real",
                         "estimated_usd": (tokens_in * .15 + tokens_out * .60) / 1_000_000
                         if mode == "real" and complete_usage else 0 if mode == "mock" else None})
    report["status"] = "executed" if len(report["cases"]) == 2 and all(
        c["complete"] for c in report["cases"]) and not budget.failed and used <= 8 else "incomplete"
    return report


def mock_response(messages):
    if any("[PERSONA_ROLE=research]" in str(m.get("content", "")) for m in messages if m["role"] == "user"):
        return web_respond(messages)
    tools = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
    if not tools:
        return {"role": "assistant", "content": None, "tool_calls": [{"id": "compare", "type": "function",
                "function": {"name": ENTRYPOINT, "arguments": "{}"}}]}, "tool_calls"
    bundle = tools[-1]
    if "environment" not in bundle:
        return {"role": "assistant", "content": "근거 미확인"}, "stop"
    env = bundle["environment"]
    text = f'프로젝트 {env["project"]}, 단계 {env["stage"]}. '
    text += " ".join(f'[{d["id"]}] {d["text"]}' for d in bundle["originals"])
    return {"role": "assistant", "content": text}, "stop"


def run_mock():
    def send(body):
        message, finish = mock_response(body["messages"])
        return 200, {"id": "offline", "created": 1, "model": MODEL,
                     "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                     "usage": {"prompt_tokens": 100, "completion_tokens": 20}}
    budget = MultiBudget(send, limit=12, main_limit=2)
    with gateway(budget) as url, tempfile.TemporaryDirectory(prefix="persona-offline-") as root:
        app = ChatApplication(Path(root), base_url=url, api_key="local-only", model=MODEL)
        return compare(app, budget, mode="mock")


def run_live(api, execute):
    if not execute:
        return {"status": "blocked", "reason": "Real mode requires --execute; no backend request sent"}
    parsed = urlsplit(api)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        return {"status": "blocked", "reason": "Use the loopback backend inside Codespaces/Cloud"}
    with httpx.Client(base_url=api, timeout=240, follow_redirects=False, trust_env=False) as client:
        health = client.get("/health").json()
        if (health.get("mode") != "real" or health.get("model") != MODEL or health.get("stopped")
                or health.get("remaining_calls", 0) < REQUIRED_CALLS or not health.get("usage", {}).get("usage_complete")):
            return {"status": "blocked", "reason": "Existing real backend needs eight remaining calls", "health": health}
        session_response = client.post("/dev/sessions", json={"user": "alice"})
        session_response.raise_for_status()
        session = session_response.json()
        response = client.post(f'/sessions/{session["session_id"]}/validation/persona-comparison',
                               headers={"Authorization": "Bearer " + session["session_token"]}, json={"confirm": True})
        response.raise_for_status()
        return response.json()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["mock", "real"], default="mock")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--api", default="http://127.0.0.1:8001")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_mock() if args.mode == "mock" else run_live(args.api, args.execute)
    except (OSError, ValueError, RuntimeError, httpx.HTTPError, OpenAIError) as exc:
        report = {"status": "execution_error", "error_type": type(exc).__name__,
                  "note": "No automatic retry. Inspect existing backend ledger before any rerun."}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Report: " + str(args.output) + "; status: " + report["status"])
    return 0 if report["status"] == "executed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
