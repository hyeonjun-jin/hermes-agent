"""Opt-in live comparison runner. Missing credentials never fall back to a mock."""
import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

REQUIRED = ("PERSONA_BASE_URL", "PERSONA_API_KEY", "PERSONA_MODEL")
QUESTION = "현재 프로젝트 계획을 어떻게 진행하면 좋을까요?"


def real_settings(environ):
    missing = [name for name in REQUIRED if not environ.get(name, "").strip()]
    if missing:
        raise ValueError("Missing environment variables: " + ", ".join(missing))
    url, key, model = (environ[name].strip() for name in REQUIRED)
    parsed = urlsplit(url)
    if (parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("PERSONA_BASE_URL must be an HTTP(S) endpoint without embedded credentials/query/fragment")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Remote PERSONA_BASE_URL requires HTTPS")
    return url, key, model


def observations(result):
    calls = result["tool_calls"]
    return {"selected_tools": [c["tool"] for c in calls],
            "search_arguments": [c["args"] for c in calls if c["tool"] == "mock_rag"],
            "recalled_memory": [c.get("result", []) for c in calls if c["tool"] == "persona_recall"],
            "environment_retrieved": any(c["tool"] == "mock_environment" and c["status"] == "ok" for c in calls),
            "tool_errors": [c for c in calls if c["status"] not in {"ok", "empty"}],
            "note": "Environment retrieval alone does not establish use in the final answer; inspect answer and evidence."}


def compare(settings, root, question):
    from .app import ChatApplication, SCOPES, seed
    from .data import PROFILES
    from .domain import Principal
    app = ChatApplication(root, base_url=settings[0], api_key=settings[1], model=settings[2])
    seed(app.store)
    records = []
    for user in PROFILES:
        try:
            result = app.chat(Principal(user, SCOPES), user, question)
            records.append({"user": user, "status": "loop_error" if result["loop_error"] else "observed",
                            **result, "observations": observations(result)})
        except Exception as exc:
            # Report type only. Authentication/transport exception text may contain a key or URL.
            records.append({"user": user, "status": "execution_error", "error_type": type(exc).__name__})
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--question", default=QUESTION)
    args = parser.parse_args()
    report = {"mode": "real", "created_at": datetime.now(UTC).isoformat(), "question": args.question,
              "quality_verdict": "not_evaluated", "users": []}
    try:
        settings = real_settings(os.environ)
    except ValueError as exc:
        report.update(status="blocked_configuration", reason=str(exc))
        exit_code = 2
    else:
        # Fresh, independent fixture state per comparison; no changes to the existing demo memory.
        with tempfile.TemporaryDirectory(prefix="persona-live-") as root:
            report["users"] = compare(settings, Path(root), args.question)
        report["status"] = "executed" if all(r["status"] == "observed" for r in report["users"]) else "execution_failed"
        report["model"] = settings[2]
        report["attribution"] = "No per-user tool plan or response branches in real mode. Persona and fixture preferences are explicit inputs; model chooses calls under a shared prompt."
        exit_code = 0 if report["status"] == "executed" else 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{report['status']}; report: {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
