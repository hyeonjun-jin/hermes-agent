"""Loopback-only development FastAPI backend. User selection is NOT authentication."""
import argparse
import asyncio
import json
import os
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .app import ChatApplication
from .mini_validation import ENDPOINT, MODEL, gateway, network_allows
from .multi_validation import MultiBudget
from .validation import real_settings
from .web_sessions import ChatSessions


class PersistentBudget(MultiBudget):
    """Reserve attempts on disk before sending; restart never silently resets the cap."""
    def __init__(self, send, path):
        super().__init__(self._send, limit=12, main_limit=2)
        self.path, self.upstream = path, send
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.calls = saved["calls"]
            self.failed = saved["failed"]

    def persist(self):
        temporary = self.path.with_suffix(".pending")
        temporary.write_text(json.dumps({"calls": self.calls, "failed": self.failed}, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

    def _send(self, body):
        self.persist()
        return self.upstream(body)

    def forward(self, body):
        result = super().forward(body)
        self.persist()
        return result


class NewSession(BaseModel):
    user: Literal["alice", "bob", "carol"]


class Message(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class PreferenceInput(BaseModel):
    model_config = {"extra": "forbid"}
    format: Literal["bullets", "table", "explanation"] | None = None
    focus: Literal["delivery", "risk", "onboarding"] | None = None


class Feedback(BaseModel):
    turn_id: str
    rating: Literal["helpful", "unhelpful"]
    comment: str = Field(default="", max_length=2000)
    consent_for_alignment: bool = False
    preference: PreferenceInput | None = None


class Approval(BaseModel):
    model_config = {"extra": "forbid"}
    confirm: Literal[True]


def check_real_network(environ, policy_path=None):
    """Codex policy takes precedence; Codespaces uses its own enforced egress/proxy."""
    path = policy_path or Path("/etc/codex/network-policy.json")
    try:
        contents = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # A Codex installation with a missing policy must still fail closed.
        if (path.parent.exists() or environ.get("CODESPACES") != "true"
                or not environ.get("CODESPACE_NAME", "").strip()):
            raise RuntimeError("Codex network policy unavailable; expected a recognized Codespaces runtime") from None
        return "github-codespaces"
    except OSError:
        raise RuntimeError("Codex network policy unreadable") from None
    try:
        allowed = network_allows(json.loads(contents))
    except (ValueError, TypeError, AttributeError, KeyError):
        raise RuntimeError("Codex network policy invalid") from None
    if not allowed:
        raise RuntimeError("Codex network policy does not allow OpenAI")
    return "codex"


def create_app(root: Path, *, mode="mock", dev_mode=False):
    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True, mode=0o700)
        with ExitStack() as stack:
            budget = None
            if mode == "mock":
                from .mock_llm import mock_endpoint
                from .web_mock import web_respond
                url = stack.enter_context(mock_endpoint(web_respond))
                key, model = "offline", "persona-mock"
            elif mode == "real":
                import httpx
                url, key, model = real_settings(os.environ)
                if url.rstrip("/") != ENDPOINT or model != MODEL:
                    raise RuntimeError("Real mode requires the OpenAI endpoint and gpt-4o-mini")
                await asyncio.to_thread(check_real_network, os.environ)
                client = stack.enter_context(httpx.Client(
                    timeout=20, headers={"Authorization": "Bearer " + key},
                    verify=True, trust_env=True, follow_redirects=False))
                def send(body):
                    response = client.post(ENDPOINT + "/chat/completions", json=body)
                    return response.status_code, response.json() if response.status_code == 200 else {}
                budget = PersistentBudget(send, root / "usage.json")
                url = stack.enter_context(gateway(budget))
                key = "local-gateway"
            else:
                raise ValueError("Unknown mode")
            application = ChatApplication(root, base_url=url, api_key=key, model=model,
                                          validation_limits=True, multi_agent=True)
            app.state.sessions = ChatSessions(application, budget)
            yield

    api = FastAPI(title="Persona Chat development API", lifespan=lifespan)

    def development():
        if not dev_mode:
            raise HTTPException(403, "Development user selection disabled; production identity integration is not implemented")

    def token(authorization):
        development()
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Session credential required")
        return authorization[7:]

    def invoke(operation):
        try:
            return operation()
        except PermissionError:
            raise HTTPException(403, "Session access denied") from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except RuntimeError:
            raise HTTPException(429, "Model call budget stopped; no automatic retry") from None

    @api.get("/health")
    def health():
        budget = api.state.sessions.budget
        return {"mode": mode, "model": MODEL if mode == "real" else "mock (not a real LLM)",
                "development_only": dev_mode, "usage": budget.totals() if budget else None,
                "stopped": bool(budget and budget.failed),
                "remaining_calls": max(0, budget.limit - len(budget.calls)) if budget else None}

    @api.post("/dev/sessions")
    def new_session(body: NewSession):
        development()
        return api.state.sessions.create(body.user)

    @api.get("/dev/sessions")
    def list_sessions(user: Literal["alice", "bob", "carol"]):
        development()
        return api.state.sessions.list_development(user)

    @api.post("/dev/sessions/{session_id}/resume")
    def resume_session(session_id: str, body: NewSession):
        development()
        return invoke(lambda: api.state.sessions.resume_development(body.user, session_id))

    @api.get("/sessions/{session_id}")
    def history(session_id: str, authorization: str | None = Header(default=None)):
        credential = token(authorization)
        return invoke(lambda: api.state.sessions.history(session_id, credential))

    @api.post("/sessions/{session_id}/messages")
    def message(session_id: str, body: Message, authorization: str | None = Header(default=None)):
        credential = token(authorization)
        return invoke(lambda: api.state.sessions.ask(session_id, credential, body.message))

    @api.post("/sessions/{session_id}/feedback")
    def feedback(session_id: str, body: Feedback, authorization: str | None = Header(default=None)):
        credential = token(authorization)
        return invoke(lambda: api.state.sessions.feedback(
            session_id, credential, body.turn_id, body.rating, body.comment, consent=body.consent_for_alignment,
            preference=body.preference.model_dump(exclude_none=True) if body.preference else None))

    @api.get("/sessions/{session_id}/alignment")
    def alignment_status(session_id: str, authorization: str | None = Header(default=None)):
        credential = token(authorization)
        return invoke(lambda: api.state.sessions.alignment_action(session_id, credential, "inspect"))

    @api.post("/sessions/{session_id}/alignment/proposals")
    def alignment_propose(session_id: str, authorization: str | None = Header(default=None)):
        credential = token(authorization)
        return invoke(lambda: api.state.sessions.alignment_action(session_id, credential, "propose"))

    @api.post("/sessions/{session_id}/alignment/{proposal_id}/approve")
    def alignment_approve(session_id: str, proposal_id: str, body: Approval,
                          authorization: str | None = Header(default=None)):
        credential = token(authorization)
        return invoke(lambda: api.state.sessions.alignment_action(session_id, credential, "approve", proposal_id))

    @api.post("/sessions/{session_id}/alignment/rollback/{revision}")
    def alignment_rollback(session_id: str, revision: int, body: Approval,
                           authorization: str | None = Header(default=None)):
        credential = token(authorization)
        return invoke(lambda: api.state.sessions.alignment_action(session_id, credential, "rollback", revision))

    @api.get("/dev/audit")
    def audit():
        development()
        budget = api.state.sessions.budget
        return {"mode": mode, "calls": budget.calls if budget else [], "totals": budget.totals() if budget else None}

    return api


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path("/workspace/persona-web-state"))
    parser.add_argument("--mode", choices=["mock", "real"], default="mock")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--dev", action="store_true")
    args = parser.parse_args()
    uvicorn.run(create_app(args.state, mode=args.mode, dev_mode=args.dev), host="127.0.0.1", port=args.port,
                log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
