"""Bounded live validation of native Hermes specialists and a direct simple answer."""
import argparse
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .mini_validation import Budget, ENDPOINT, MODEL, RATES, gateway, network_allows
from .validation import real_settings

COMPLEX = "현재 프로젝트 계획을 관련 문서로 조사하고, 환경과 제약에 맞춰 분석한 뒤 근거와 누락 정보를 검증해 주세요."
SIMPLE = "안녕하세요. 한 문장으로 인사해 주세요."


class MultiBudget(Budget):
    """Shared remote cap plus individual role caps. Classifies by server-created child goal."""
    def __init__(self, send, *, limit=12, main_limit=4):
        super().__init__(send, limit=limit)
        self.main_limit = main_limit
        self.case = "complex"
        self.by_actor = {}

    def forward(self, body):
        users = "\n".join(str(m.get("content", "")) for m in body.get("messages", []) if m.get("role") == "user")
        match = re.search(r"\[PERSONA_ROLE=(research|analysis|verification)\]", users)
        role = match[1] if match else "main"
        actor = self.case + ":" + role
        limit = (1 if self.case == "simple" else self.main_limit) if role == "main" else 2
        if self.by_actor.get(actor, 0) >= limit:
            self.failed = True
            return 429, {"error": {"message": "Agent call cap reached"}}
        before = len(self.calls)
        result = super().forward(body)
        if len(self.calls) > before:
            self.by_actor[actor] = self.by_actor.get(actor, 0) + 1
            self.calls[-1]["actor"] = actor
            self.calls[-1]["offered_tools"] = [t.get("function", {}).get("name") for t in body.get("tools", [])]
        return result


def run(environ, policy, root, *, complex_only=False, total_limit=12):
    if not 1 <= total_limit <= 12:
        raise ValueError("Total request limit must be between 1 and 12")
    scenarios = [("complex", COMPLEX)] + ([] if complex_only else [("simple", SIMPLE)])
    report = {"model": MODEL, "endpoint": ENDPOINT, "created_at": datetime.now(UTC).isoformat(),
              "status": "blocked", "scenarios": [], "pricing": RATES,
              "limits": {"total_remote_attempts": total_limit, "complex_main": 2, "each_specialist": 2,
                         "simple_main": 1, "output_tokens": 512, "remote_retries": 0}}
    try:
        url, key, model = real_settings(environ)
    except ValueError as exc:
        report["reason"] = str(exc)
        return report
    if url.rstrip("/") != ENDPOINT or model != MODEL or not network_allows(policy):
        report["reason"] = "OpenAI endpoint/model or network policy not ready"
        return report
    import httpx
    from .app import ChatApplication, SCOPES, seed
    from .domain import Principal
    with httpx.Client(timeout=20, headers={"Authorization": "Bearer " + key}) as client:
        def send(body):
            response = client.post(ENDPOINT + "/chat/completions", json=body)
            return response.status_code, response.json() if response.status_code == 200 else {}
        budget = MultiBudget(send, limit=total_limit, main_limit=2)
        with gateway(budget) as local_url:
            for name, question in scenarios:
                if budget.failed:
                    break
                budget.case = name
                app = ChatApplication(root / name, base_url=local_url, api_key="local-gateway", model=MODEL,
                                      validation_limits=True, multi_agent=True)
                seed(app.store)
                try:
                    result = app.chat(Principal("alice", SCOPES), "alice", question)
                    report["scenarios"].append({"scenario": name, "question": question, **result})
                except Exception as exc:
                    report["scenarios"].append({"scenario": name, "error_type": type(exc).__name__})
                    break
    report.update(calls=budget.calls, totals=budget.totals(), calls_by_actor=budget.by_actor)
    report["status"] = "executed" if len(report["scenarios"]) == len(scenarios) and not budget.failed and all(
        not r.get("loop_error") and not r.get("error_type") and r.get("completion", {}).get("complete")
        for r in report["scenarios"]) else "incomplete"
    report["quality_note"] = "Completion is a mechanical check. Review role summaries, source documents, gaps and raw final answer."
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--complex-only", action="store_true")
    parser.add_argument("--max-total", type=int, default=12)
    args = parser.parse_args()
    try:
        policy = json.loads(Path("/etc/codex/network-policy.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        policy = {}
    with tempfile.TemporaryDirectory(prefix="persona-multi-") as root:
        report = run(os.environ, policy, Path(root), complex_only=args.complex_only, total_limit=args.max_total)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(report["status"] + "; report: " + str(args.output))
    return 0 if report["status"] == "executed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
