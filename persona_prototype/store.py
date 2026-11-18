"""Scoped SQLite memory; lexical search baseline, not embedding retrieval."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import UTC, datetime

from .domain import Authorizer, Principal
from .personalization import terms, TAGS


class MemoryStore:
    def __init__(self, path: Path, authorizer: Authorizer):
        self.path, self.authorizer = path, authorizer
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY, user_id TEXT, session_id TEXT,
                    query TEXT, response TEXT, confirmed INTEGER, created_at TEXT);
                CREATE TABLE IF NOT EXISTS semantics (
                    user_id TEXT PRIMARY KEY, payload TEXT);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_semantic(self, actor: Principal, user_id: str, payload: dict):
        self.authorizer.require(actor, user_id, "memory:write")
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO semantics VALUES (?, ?)",
                       (user_id, json.dumps(payload, ensure_ascii=False)))

    def semantic(self, actor: Principal, user_id: str) -> dict:
        self.authorizer.require(actor, user_id, "memory:read")
        with self.connect() as db:
            row = db.execute("SELECT payload FROM semantics WHERE user_id=?", (user_id,)).fetchone()
        return json.loads(row[0]) if row else {}

    def append(self, actor: Principal, user_id: str, session_id: str, query: str,
               response: str, *, confirmed: bool = False):
        self.authorizer.require(actor, user_id, "memory:write")
        with self.connect() as db:
            db.execute("INSERT INTO episodes VALUES (NULL, ?, ?, ?, ?, ?, ?)",
                       (user_id, session_id, query, response, int(confirmed),
                        datetime.now(UTC).isoformat()))

    def search(self, actor: Principal, user_id: str, query: str, k: int = 4, *, confirmed_only=False,
               project_id=None) -> list[dict]:
        self.authorizer.require(actor, user_id, "memory:read")
        if not 1 <= k <= 10:
            raise ValueError("k must be between 1 and 10")
        query_terms = terms(query)
        with self.connect() as db:
            # This is a candidate filter, not project authorization; callers enforce current project access.
            project_clause = " AND substr(query,1,length(?))=?" if project_id is not None else ""
            prefix = "[project=" + project_id + "] " if project_id is not None else ""
            rows = db.execute("SELECT id,session_id,query,response,confirmed,created_at FROM episodes "
                              "WHERE user_id=?" + project_clause + " ORDER BY id DESC",
                              (user_id, prefix, prefix) if project_id is not None else (user_id,)).fetchall()
        ranked = []
        for row in rows:
            if confirmed_only and not row[4]:
                continue
            score = len(query_terms & terms(row[2] + " " + row[3]))
            if score:
                ranked.append((score, row))
        ranked.sort(key=lambda item: (item[0], item[1][0]), reverse=True)
        keys = ("id", "session_id", "query", "response", "confirmed", "created_at")
        return [dict(zip(keys, row)) for _, row in ranked[:k]]


def build_persona(profile: dict, semantic: dict) -> dict:
    # Only explicit, allowlisted preferences become instructions. Raw episodes are evidence.
    style = semantic.get("format", profile["format"])
    if style not in {"bullets", "table", "explanation"}:
        raise ValueError("Unsupported format")
    version = semantic.get("persona_version", 1)
    if type(version) is not int or version < 1:
        raise ValueError("Invalid Persona version")
    result = {"version": version, "project": profile["project"], "format": style, "language": profile["language"]}
    if "focus" in semantic:
        if semantic["focus"] not in TAGS:
            raise ValueError("Unsupported search focus")
        result["focus"] = semantic["focus"]
    return result
