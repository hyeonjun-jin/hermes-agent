"""Budgeted OpenAI gpt-4o-mini validation; fail closed before network access."""
import argparse
import fnmatch
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .validation import QUESTION, observations, real_settings

ENDPOINT = "https://api.openai.com/v1"
MODEL = "gpt-4o-mini"
# Provisional standard rates, not a fetched/current quote; cached input charged at full rate.
RATES = {"input_usd_per_million": 0.15, "output_usd_per_million": 0.60,
         "source": "provisional gpt-4o-mini standard rates; verify https://openai.com/api/pricing/"}


def network_allows(policy):
    policy = policy.get("http_network_policy", policy)
    mode = policy.get("type", policy.get("mode"))
    if mode == "unrestricted":
        return True
    return mode == "restricted" and any(fnmatch.fnmatchcase("api.openai.com", r["host"])
                                         for r in policy.get("egress_rules", []))


class Budget:
    """Count actual upstream attempts, including failures. No automatic remote retry."""
    def __init__(self, send, limit=4):
        self.send, self.limit = send, limit
        self.calls = []
        self.failed = False
        self.lock = threading.Lock()

    def forward(self, body):
        with self.lock:
            if self.failed or len(self.calls) >= self.limit:
                return 429, {"error": {"message": "Validation budget stopped", "type": "budget"}}
            if len(json.dumps(body).encode()) > 64000:
                self.failed = True
                return 400, {"error": {"message": "Input budget exceeded"}}
            body = dict(body, model=MODEL, stream=False, max_tokens=512)
            for key in ("stream_options", "max_completion_tokens"):
                body.pop(key, None)
            record = {"attempt": len(self.calls) + 1, "status": "pending", "usage": None}
            self.calls.append(record)
            try:
                status, payload = self.send(body)
            except Exception as exc:
                record.update(status="transport_error", error_type=type(exc).__name__)
                self.failed = True
                return 502, {"error": {"message": "Upstream request failed"}}
            record["status"] = status
            if status != 200:
                self.failed = True
                return status, {"error": {"message": "OpenAI rejected request"}}
            record["usage"] = payload.get("usage")
            return status, payload

    def totals(self):
        known = [r["usage"] for r in self.calls if r["usage"] is not None]
        inputs = sum(u.get("prompt_tokens", 0) for u in known)
        outputs = sum(u.get("completion_tokens", 0) for u in known)
        complete = len(known) == len(self.calls)
        return {"upstream_attempts": len(self.calls), "usage_complete": complete,
                "reported_input_tokens": inputs, "reported_output_tokens": outputs,
                "estimated_usd": (inputs * 0.15 + outputs * 0.60) / 1_000_000 if complete else None}


@contextmanager
def gateway(budget):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                self.send_error(400, "Only chat completions supported")
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            status, payload = budget.forward(body)
            stream = status == 200 and body.get("stream")
            self.send_response(status)
            self.send_header("Content-Type", "text/event-stream" if stream else "application/json")
            self.end_headers()
            if not stream:
                self.wfile.write(json.dumps(payload).encode())
                return
            choice = payload["choices"][0]
            delta = dict(choice["message"])
            if delta.get("tool_calls"):
                delta["tool_calls"] = [dict(tc, index=i) for i, tc in enumerate(delta["tool_calls"])]
            for value, reason in [(delta, None), ({}, choice["finish_reason"])]:
                chunk = {"id": payload["id"], "created": payload["created"], "model": payload["model"],
                         "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": value, "finish_reason": reason}]}
                if reason:
                    chunk["usage"] = payload.get("usage")
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def run(environ, policy, root, *, memory_control=False):
    report = {"model": MODEL, "endpoint": ENDPOINT, "created_at": datetime.now(UTC).isoformat(),
              "status": "blocked", "users": [], "pricing": RATES,
              "tool_calling_compatibility": "not_tested", "personalization": "not_tested",
              "totals": {"upstream_attempts": 0, "reported_input_tokens": 0,
                         "reported_output_tokens": 0, "estimated_usd": 0},
              "limits": {"requests_per_user": 4, "requests_total": 12, "remote_retries": 0,
                         "output_tokens_per_request": 512, "request_bytes": 64000}}
    try:
        url, key, model = real_settings(environ)
    except ValueError as exc:
        report["reason"] = str(exc)
        return report
    if url.rstrip("/") != ENDPOINT or model != MODEL:
        report["reason"] = "Set PERSONA_BASE_URL=https://api.openai.com/v1 and PERSONA_MODEL=gpt-4o-mini"
        return report
    if not network_allows(policy):
        report["reason"] = "api.openai.com is not allowed by the environment network policy"
        return report
    import httpx
    from .app import ChatApplication, SCOPES, seed
    from .data import PROFILES
    from .domain import Principal
    all_calls = []
    user_counts = dict.fromkeys(PROFILES, 0)
    cases = [(u, "baseline") for u in PROFILES]
    if memory_control:
        cases.append(("alice", "memory_risk"))
    for user, condition in cases:
        with httpx.Client(timeout=20, headers={"Authorization": "Bearer " + key}) as client:
            def send(body):
                response = client.post(ENDPOINT + "/chat/completions", json=body)
                return response.status_code, response.json() if response.status_code == 200 else {}
            remaining = min(4 - user_counts[user], 12 - len(all_calls))
            if remaining <= 0:
                report["users"].append({"user": user, "condition": condition, "error_type": "BudgetExhausted"})
                break
            budget = Budget(send, limit=remaining)
            with gateway(budget) as local_url:
                app = ChatApplication(root / condition, base_url=local_url, api_key="local-gateway", model=MODEL,
                                      validation_limits=True)
                seed(app.store)
                if condition == "memory_risk":
                    # Controlled fixture intervention: only Alice's five confirmed episode responses change.
                    with app.store.connect() as db:
                        db.execute("UPDATE episodes SET response=? WHERE user_id=? AND confirmed=1",
                                   ("focus=risk 확인된 선호", user))
                try:
                    result = app.chat(Principal(user, SCOPES), user, QUESTION)
                    row = {"user": user, "condition": condition, **result, "observations": observations(result)}
                except Exception as exc:
                    row = {"user": user, "condition": condition, "error_type": type(exc).__name__}
        row.update(calls=budget.calls, usage=budget.totals())
        report["users"].append(row)
        all_calls.extend(budget.calls)
        user_counts[user] += len(budget.calls)
        if budget.failed or row.get("error_type") or row.get("loop_error"):
            break
    aggregate = Budget(None)
    aggregate.calls = all_calls
    report["totals"] = aggregate.totals()
    report["calls_by_user"] = user_counts
    report["question"] = QUESTION
    complete = len(report["users"]) == len(cases) and not budget.failed and not any(
        r.get("loop_error") or r.get("error_type") for r in report["users"])
    report["status"] = "executed" if complete else "execution_failed"
    report["personalization"] = "requires_review_of_evidence"
    report["tool_calling_compatibility"] = "observed" if any(
        c.get("status") == "ok" for r in report["users"] for c in r.get("tool_calls", [])) else "not_observed"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--memory-control", action="store_true", help="Also compare Alice with only episodic focus changed")
    args = parser.parse_args()
    try:
        policy = json.loads(Path("/etc/codex/network-policy.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        policy = {}  # Unknown policy fails closed.
    with tempfile.TemporaryDirectory(prefix="mini-validation-") as root:
        report = run(os.environ, policy, Path(root), memory_control=args.memory_control)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(report["status"] + "; report: " + str(args.output))
    return 0 if report["status"] == "executed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
