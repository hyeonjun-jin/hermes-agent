"""Owner-scoped, append-only Persona revisions and explicit approval transactions."""
import json
import uuid
from datetime import UTC, datetime

from .data import PROFILES
from .personalization import TAGS
from .store import build_persona


def preferences(value):
    if not isinstance(value, dict) or set(value) - {"format", "focus"}:
        raise ValueError("Only response format and search focus may be aligned")
    if not value or any(not isinstance(v, str) or v not in ({"bullets", "table", "explanation"} if k == "format" else TAGS)
                        for k, v in value.items()):
        raise ValueError("Invalid preference value")
    return dict(value)


def semantic_preferences(profile, semantic):
    return preferences({"format": semantic.get("format", profile["format"]),
                        **({"focus": semantic["focus"]} if "focus" in semantic else {})})


def feedback_examples(db, owner):
    rows = db.execute("SELECT f.id,f.turn_id,f.preferences,t.question FROM preference_feedback f "
                      "JOIN web_turns t ON t.id=f.turn_id JOIN web_sessions s ON s.id=t.session_id "
                      "WHERE f.owner=? AND s.owner=? ORDER BY f.id DESC LIMIT 12", (owner, owner)).fetchall()
    return [{"feedback_id": r[0], "turn_id": r[1], "preferences": json.loads(r[2]), "question": r[3]}
            for r in reversed(rows)]


class AlignmentStore:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS persona_versions (
                    owner TEXT, revision INTEGER, preferences TEXT, reason TEXT, created_at TEXT,
                    PRIMARY KEY(owner,revision));
                CREATE TABLE IF NOT EXISTS persona_active (owner TEXT PRIMARY KEY, revision INTEGER);
                CREATE TABLE IF NOT EXISTS preference_feedback (
                    id INTEGER PRIMARY KEY, owner TEXT, turn_id TEXT, preferences TEXT,
                    UNIQUE(owner,turn_id));
                CREATE TABLE IF NOT EXISTS alignment_runs (
                    id TEXT PRIMARY KEY, owner TEXT, base_revision INTEGER, baseline TEXT,
                    candidate TEXT, report TEXT, status TEXT);
            """)

    def require(self, actor, scope):
        self.store.authorizer.require(actor, actor.user_id, scope)

    def current(self, actor):
        self.require(actor, "persona:read")
        self.require(actor, "memory:read")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM semantics WHERE user_id=?", (actor.user_id,)).fetchone()
            semantic = json.loads(row[0]) if row else {}
            prefs = semantic_preferences(PROFILES[actor.user_id], semantic)
            db.execute("INSERT OR IGNORE INTO persona_versions VALUES (?,?,?,?,?)",
                       (actor.user_id, 1, json.dumps(prefs), "initial snapshot", datetime.now(UTC).isoformat()))
            db.execute("INSERT OR IGNORE INTO persona_active VALUES (?,1)", (actor.user_id,))
            revision = db.execute("SELECT revision FROM persona_active WHERE owner=?", (actor.user_id,)).fetchone()[0]
        return {"revision": revision, "preferences": prefs,
                "persona": {**build_persona(PROFILES[actor.user_id], semantic), "version": revision}}

    def feedback(self, actor, turn_id, value):
        self.require(actor, "persona:propose")
        value = preferences(value)
        with self.store.connect() as db:
            owner = db.execute("SELECT s.owner FROM web_turns t JOIN web_sessions s ON s.id=t.session_id "
                               "WHERE t.id=?", (turn_id,)).fetchone()
            if not owner or owner[0] != actor.user_id:
                raise PermissionError("Feedback owner mismatch")
            db.execute("INSERT INTO preference_feedback(owner,turn_id,preferences) VALUES (?,?,?) "
                       "ON CONFLICT(owner,turn_id) DO UPDATE SET preferences=excluded.preferences",
                       (actor.user_id, turn_id, json.dumps(value)))
            db.execute("UPDATE alignment_runs SET status='stale' WHERE owner=? AND status='proposed'", (actor.user_id,))

    def revoke_feedback(self, actor, turn_id):
        self.require(actor, "persona:propose")
        with self.store.connect() as db:
            deleted = db.execute("DELETE FROM preference_feedback WHERE owner=? AND turn_id=?", (actor.user_id, turn_id))
            if deleted.rowcount:
                db.execute("UPDATE alignment_runs SET status='stale' WHERE owner=? AND status='proposed'", (actor.user_id,))

    def examples(self, actor):
        self.require(actor, "persona:propose")
        self.require(actor, "memory:read")
        with self.store.connect() as db:
            return feedback_examples(db, actor.user_id)

    def save_run(self, actor, baseline, candidate, report, status):
        self.require(actor, "persona:propose")
        run_id = uuid.uuid4().hex
        with self.store.connect() as db:
            db.execute("INSERT INTO alignment_runs VALUES (?,?,?,?,?,?,?)", (
                run_id, actor.user_id, baseline["revision"], json.dumps(baseline["preferences"]),
                json.dumps(candidate), json.dumps(report, ensure_ascii=False), status))
        return {"proposal_id": run_id, "status": status, "base_revision": baseline["revision"],
                "baseline": baseline["persona"], "candidate_preferences": candidate, "evaluation": report}

    def inspect(self, actor):
        current = self.current(actor)
        with self.store.connect() as db:
            versions = db.execute("SELECT revision,preferences,reason FROM persona_versions WHERE owner=? ORDER BY revision",
                                  (actor.user_id,)).fetchall()
            runs = db.execute("SELECT id,status,report,candidate FROM alignment_runs WHERE owner=? ORDER BY rowid DESC LIMIT 5",
                              (actor.user_id,)).fetchall()
        return {**current, "versions": [{"revision": r[0], "preferences": json.loads(r[1]), "reason": r[2]} for r in versions],
                "proposals": [{"proposal_id": r[0], "status": r[1], "evaluation": json.loads(r[2]),
                               "candidate_preferences": json.loads(r[3])} for r in runs]}

    def activate(self, actor, *, proposal_id=None, rollback_revision=None):
        scope = "persona:approve" if proposal_id else "persona:rollback"
        self.require(actor, scope)
        self.require(actor, "persona:read")
        self.require(actor, "memory:read")
        self.require(actor, "memory:write")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute("SELECT revision FROM persona_active WHERE owner=?", (actor.user_id,)).fetchone()
            if not active:
                raise ValueError("No versioned Persona")
            row = db.execute("SELECT payload FROM semantics WHERE user_id=?", (actor.user_id,)).fetchone()
            semantic = json.loads(row[0]) if row else {}
            prefs, reason = self._approved_preferences(db, actor, proposal_id, rollback_revision, active[0], semantic)
            revision = db.execute("SELECT MAX(revision)+1 FROM persona_versions WHERE owner=?", (actor.user_id,)).fetchone()[0]
            db.execute("INSERT INTO persona_versions VALUES (?,?,?,?,?)",
                       (actor.user_id, revision, json.dumps(prefs), reason, datetime.now(UTC).isoformat()))
            for key in ("format", "focus"):
                semantic.pop(key, None)
            semantic.update(prefs, persona_version=revision, alignment_source=reason)
            db.execute("INSERT INTO semantics(user_id,payload) VALUES (?,?) "
                       "ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload", (actor.user_id, json.dumps(semantic)))
            db.execute("UPDATE persona_active SET revision=? WHERE owner=?", (revision, actor.user_id))
            if proposal_id:
                db.execute("UPDATE alignment_runs SET status='applied' WHERE id=? AND owner=?", (proposal_id, actor.user_id))
            db.execute("UPDATE alignment_runs SET status='stale' WHERE owner=? AND status='proposed'", (actor.user_id,))
        return self.current(actor)

    def _approved_preferences(self, db, actor, proposal_id, rollback_revision, revision, semantic):
        if not proposal_id:
            row = db.execute("SELECT preferences FROM persona_versions WHERE owner=? AND revision=?",
                             (actor.user_id, rollback_revision)).fetchone()
            if not row:
                raise ValueError("Unknown own Persona revision")
            return preferences(json.loads(row[0])), "rollback:" + str(rollback_revision)
        row = db.execute("SELECT base_revision,baseline,candidate,report,status FROM alignment_runs WHERE id=? AND owner=?",
                         (proposal_id, actor.user_id)).fetchone()
        if not row:
            raise PermissionError("Proposal access denied")
        report = json.loads(row[3])
        if row[4] != "proposed" or not report.get("improved") or report.get("mode") != "mock":
            raise ValueError("Proposal has not passed evaluation")
        if row[0] != revision or json.loads(row[1]) != semantic_preferences(PROFILES[actor.user_id], semantic):
            raise ValueError("Stale proposal; evaluate again against the active Persona")
        if report.get("feedback_snapshot") != feedback_examples(db, actor.user_id):
            raise ValueError("Feedback changed; evaluate again")
        return preferences(json.loads(row[2])), "approved_alignment:" + proposal_id
