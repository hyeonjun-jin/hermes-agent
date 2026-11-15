"""Persistent development chat sessions; a token binds requests to a stored owner."""
import hashlib
import hmac
import json
import secrets
import threading
import uuid

from .app import SCOPES, seed
from .data import PROFILES
from .domain import Principal
from .quality import quality_review
from .alignment import PreferenceAligner, COMMENT_PREFERENCES


class ChatSessions:
    def __init__(self, application, budget=None):
        self.app, self.budget = application, budget
        self.lock = threading.RLock()  # Serialize embedded Hermes global runtime activity.
        seed(application.store)
        with self.app.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS web_sessions (id TEXT PRIMARY KEY, owner TEXT,
                    token_hash TEXT, persona TEXT, history TEXT);
                CREATE TABLE IF NOT EXISTS web_turns (id TEXT PRIMARY KEY, session_id TEXT,
                    question TEXT, result TEXT);
                CREATE TABLE IF NOT EXISTS web_feedback (id INTEGER PRIMARY KEY, session_id TEXT,
                    turn_id TEXT, rating TEXT, comment TEXT);
            """)
        self.aligner = PreferenceAligner(self.app.store)

    def create(self, user):
        if user not in PROFILES:
            raise ValueError("Unknown development user")
        actor = Principal(user, SCOPES)
        persona = self.aligner.repository.current(actor)["persona"]
        session_id, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
        with self.app.store.connect() as db:
            db.execute("INSERT INTO web_sessions VALUES (?,?,?,?,?)", (session_id, user,
                       hashlib.sha256(token.encode()).hexdigest(), json.dumps(persona), "[]"))
        return {"session_id": session_id, "session_token": token, "user": user, "persona": persona}

    def owned(self, session_id, token):
        with self.app.store.connect() as db:
            row = db.execute("SELECT owner,token_hash,persona,history FROM web_sessions WHERE id=?", (session_id,)).fetchone()
        if not row or not hmac.compare_digest(row[1], hashlib.sha256(token.encode()).hexdigest()):
            raise PermissionError("Invalid session credential")
        return row

    def list_development(self, user):
        with self.app.store.connect() as db:
            rows = db.execute("SELECT id FROM web_sessions WHERE owner=? ORDER BY rowid DESC LIMIT 50", (user,)).fetchall()
        return [{"session_id": row[0]} for row in rows]

    def resume_development(self, user, session_id):
        with self.lock, self.app.store.connect() as db:
            row = db.execute("SELECT owner,persona FROM web_sessions WHERE id=?", (session_id,)).fetchone()
            if not row or row[0] != user:
                raise PermissionError("Development session owner mismatch")
            token = secrets.token_urlsafe(32)
            db.execute("UPDATE web_sessions SET token_hash=? WHERE id=?",
                       (hashlib.sha256(token.encode()).hexdigest(), session_id))
        return {"session_id": session_id, "session_token": token, "user": user, "persona": json.loads(row[1])}

    def history(self, session_id, token):
        row = self.owned(session_id, token)
        with self.app.store.connect() as db:
            turns = db.execute("SELECT id,question,result FROM web_turns WHERE session_id=? ORDER BY rowid", (session_id,)).fetchall()
        return {"session_id": session_id, "user": row[0], "persona": json.loads(row[2]),
                "turns": [{"turn_id": t[0], "question": t[1], "result": json.loads(t[2])} for t in turns]}

    def ask(self, session_id, token, question):
        with self.lock:
            row = self.owned(session_id, token)
            previous = self.history(session_id, token)["turns"]
            if len(previous) >= 20:
                raise ValueError("Session turn limit reached; create a new conversation")
            if self.budget and (self.budget.failed or len(self.budget.calls) >= self.budget.limit):
                raise RuntimeError("Model budget stopped; no remote call attempted")
            if self.budget and all(w in question for w in ("조사", "분석", "검증")) and self.budget.limit - len(self.budget.calls) < 8:
                raise RuntimeError("Insufficient reserved budget for the complete workflow")
            if self.budget:
                self.budget.case = session_id + ":" + uuid.uuid4().hex
            sources = set()
            prior_environment = None
            for turn in previous:
                saved = turn["result"]
                events = saved.get("tool_calls", []) + saved.get("role_tool_calls", [])
                for event in events:
                    if (event.get("tool") in {"mock_environment", "persona_analysis_environment"}
                            and event.get("status") == "ok"
                            and isinstance(event.get("result"), dict)
                            and event["result"].get("project") == PROFILES[row[0]]["project"]):
                        prior_environment = event["result"]
                sources.update(d["id"] for e in saved.get("role_tool_calls", [])
                               if e["role"] == "research" and e.get("status") == "ok" for d in e["result"])
                sources.update(d["id"] for e in saved.get("tool_calls", [])
                               if e["tool"] == "mock_rag" and e.get("status") == "ok" for d in e["result"])
            result = self.app.chat(Principal(row[0], SCOPES), row[0], question,
                                   session_id=session_id, conversation_history=json.loads(row[3]),
                                   persona_snapshot=json.loads(row[2]), known_source_ids=sources,
                                   prior_environment=prior_environment)
            history = result.pop("history")
            result["quality"] = quality_review(result, sources)
            if self.budget:
                result["usage"] = self.budget.totals()
            turn_id = uuid.uuid4().hex
            with self.app.store.connect() as db:
                db.execute("INSERT INTO web_turns VALUES (?,?,?,?)", (turn_id, session_id, question,
                           json.dumps(result, ensure_ascii=False)))
                db.execute("UPDATE web_sessions SET history=? WHERE id=?", (json.dumps(history, ensure_ascii=False), session_id))
            return {"turn_id": turn_id, **result}

    def feedback(self, session_id, token, turn_id, rating, comment, *, consent=False, preference=None):
        with self.lock:
            row = self.owned(session_id, token)
            with self.app.store.connect() as db:
                if not db.execute("SELECT 1 FROM web_turns WHERE id=? AND session_id=?", (turn_id, session_id)).fetchone():
                    raise ValueError("Turn not in this session")
                db.execute("INSERT INTO web_feedback VALUES(NULL,?,?,?,?)", (session_id, turn_id, rating, comment))
            if consent:
                value = preference or COMMENT_PREFERENCES.get(comment.strip().rstrip(".!"))
                if value:
                    self.aligner.repository.feedback(Principal(row[0], SCOPES), turn_id, value)
                    return {"saved": True, "used_for_alignment": False, "eligible_for_alignment": True}
            self.aligner.repository.revoke_feedback(Principal(row[0], SCOPES), turn_id)
            return {"saved": True, "used_for_alignment": False}

    def alignment_action(self, session_id, token, action, value=None):
        with self.lock:
            row = self.owned(session_id, token)
            actor = Principal(row[0], SCOPES)
            repository = self.aligner.repository
            if action == "inspect":
                return repository.inspect(actor)
            if action == "propose":
                return self.aligner.propose(actor)
            if action == "approve":
                return repository.activate(actor, proposal_id=value)
            if action == "rollback":
                return repository.activate(actor, rollback_revision=value)
            raise ValueError("Unknown Alignment action")

    def compare_personas(self, session_id, token):
        with self.lock:
            row = self.owned(session_id, token)
            if row[0] != "alice":
                raise PermissionError("This experiment is Alice-only")
            if self.budget is None:
                raise ValueError("Use the standalone Mock runner; this route requires a real ledger")
            from .persona_comparison import compare
            return compare(self.app, self.budget, mode="real")
