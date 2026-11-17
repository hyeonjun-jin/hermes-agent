"""Project/owner-scoped episodic feedback and append-only research Persona revisions."""
import copy
import json
import uuid
from datetime import UTC, datetime

from .approvals import digest
from .persona_preferences import DIMENSIONS, preferences


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class ResearchPersonaStore:
    def __init__(self, store, project_access):
        self.store, self.project_access = store, project_access
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS tr_turns(id TEXT PRIMARY KEY,owner TEXT,project TEXT,payload TEXT);
                CREATE TABLE IF NOT EXISTS tr_feedback(id INTEGER PRIMARY KEY,owner TEXT,project TEXT,turn_id TEXT,payload TEXT,
                    UNIQUE(owner,project,turn_id));
                CREATE TABLE IF NOT EXISTS tr_personas(owner TEXT,project TEXT,revision INTEGER,payload TEXT,PRIMARY KEY(owner,project,revision));
                CREATE TABLE IF NOT EXISTS tr_active(owner TEXT,project TEXT,revision INTEGER,PRIMARY KEY(owner,project));
                CREATE TABLE IF NOT EXISTS tr_proposals(id TEXT PRIMARY KEY,owner TEXT,project TEXT,payload TEXT,status TEXT);
                CREATE TABLE IF NOT EXISTS tr_persona_events(id INTEGER PRIMARY KEY,owner TEXT,project TEXT,kind TEXT,payload TEXT,created_at TEXT);
            ''')

    def require(self, actor, project, *, write=False, scope=None):
        self.store.authorizer.require(actor, actor.user_id, 'memory:read')
        if write:
            self.store.authorizer.require(actor, actor.user_id, 'memory:write')
        if scope:
            self.store.authorizer.require(actor, actor.user_id, scope)
        if not self.project_access(actor, project):
            raise PermissionError('Current project access denied')

    def _active(self, db, actor, project):
        initial = {'revision': 1, 'preferences': {}, 'data_policy': 'PRIVATE', 'reason': 'initial', 'created_at': datetime.now(UTC).isoformat()}
        db.execute('INSERT OR IGNORE INTO tr_personas VALUES (?,?,1,?)', (actor.user_id, project, encoded(initial)))
        db.execute('INSERT OR IGNORE INTO tr_active VALUES (?,?,1)', (actor.user_id, project))
        row = db.execute('SELECT v.payload FROM tr_personas v JOIN tr_active a ON v.owner=a.owner AND v.project=a.project AND v.revision=a.revision '
                         'WHERE v.owner=? AND v.project=?', (actor.user_id, project)).fetchone()
        return json.loads(row[0])

    def current(self, actor, project):
        self.require(actor, project)
        with self.store.connect() as db:
            return self._active(db, actor, project)

    def record_turn(self, actor, project, result):
        self.require(actor, project, write=True)
        identifier = uuid.uuid4().hex
        with self.store.connect() as db:
            db.execute('INSERT INTO tr_turns VALUES (?,?,?,?)', (identifier, actor.user_id, project, encoded(result)))
        return identifier

    def feedback(self, actor, project, turn_id, dimensions, changes, comment='', *, confirmed=False, consent=False):
        self.require(actor, project, write=True, scope='persona:propose')
        if (not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSIONS) or
                any(not isinstance(value, str) or value not in {'helpful', 'needs_change', 'not_assessed'} for value in dimensions.values()) or
                not isinstance(comment, str) or len(comment) > 4000 or type(confirmed) is not bool or type(consent) is not bool):
            raise ValueError('Invalid structured feedback')
        changes = preferences(changes)
        payload = {'dimensions': dimensions, 'changes': changes, 'comment': comment, 'confirmed': confirmed,
                   'alignment_consent': consent, 'data_policy': 'PRIVATE'}
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            turn = db.execute('SELECT payload FROM tr_turns WHERE id=? AND owner=? AND project=?', (turn_id, actor.user_id, project)).fetchone()
            if turn is None:
                raise PermissionError('Research turn owner/project mismatch')
            payload['turn_sha256'] = digest(json.loads(turn[0]))
            db.execute('INSERT INTO tr_feedback(owner,project,turn_id,payload) VALUES (?,?,?,?) '
                       'ON CONFLICT(owner,project,turn_id) DO UPDATE SET payload=excluded.payload',
                       (actor.user_id, project, turn_id, encoded(payload)))
            self._event(db, actor, project, 'feedback', {'turn_id': turn_id, **payload})
            db.execute("UPDATE tr_proposals SET status='stale' WHERE owner=? AND project=? AND status='proposed'", (actor.user_id, project))
        return payload

    def _examples(self, db, actor, project):
        rows = db.execute('SELECT f.id,f.turn_id,f.payload,t.payload FROM tr_feedback f JOIN tr_turns t ON f.turn_id=t.id '
                          'WHERE f.owner=? AND f.project=? AND t.owner=f.owner AND t.project=f.project ORDER BY f.id',
                          (actor.user_id, project)).fetchall()
        examples = []
        for identifier, turn_id, raw, turn_raw in rows:
            feedback, turn = json.loads(raw), json.loads(turn_raw)
            if feedback['confirmed'] and feedback['alignment_consent'] and turn.get('complete') and feedback['changes']:
                examples.append({'feedback_id': identifier, 'turn_id': turn_id, 'feedback': feedback, 'turn': turn})
        return examples[-12:]

    def examples(self, actor, project):
        self.require(actor, project, scope='persona:propose')
        with self.store.connect() as db:
            return self._examples(db, actor, project)

    def save_proposal(self, actor, project, payload, status):
        self.require(actor, project, write=True, scope='persona:propose')
        identifier = uuid.uuid4().hex
        with self.store.connect() as db:
            db.execute('INSERT INTO tr_proposals VALUES (?,?,?,?,?)', (identifier, actor.user_id, project, encoded(payload), status))
        return {'proposal_id': identifier, 'status': status, **copy.deepcopy(payload)}

    def inspect(self, actor, project):
        self.require(actor, project)
        with self.store.connect() as db:
            active = self._active(db, actor, project)
            versions = [json.loads(row[0]) for row in db.execute('SELECT payload FROM tr_personas WHERE owner=? AND project=? ORDER BY revision', (actor.user_id, project))]
            proposals = [{'proposal_id': row[0], 'status': row[1], **json.loads(row[2])} for row in db.execute(
                'SELECT id,status,payload FROM tr_proposals WHERE owner=? AND project=? ORDER BY rowid DESC LIMIT 8', (actor.user_id, project))]
            events = [{'kind': row[0], 'details': json.loads(row[1]), 'created_at': row[2]} for row in db.execute(
                'SELECT kind,payload,created_at FROM tr_persona_events WHERE owner=? AND project=? ORDER BY id DESC LIMIT 30', (actor.user_id, project))]
        return {'active': active, 'versions': versions, 'proposals': proposals, 'events': events}

    def reject(self, actor, project, proposal_id):
        self.require(actor, project, write=True, scope='persona:approve')
        with self.store.connect() as db:
            changed = db.execute("UPDATE tr_proposals SET status='rejected' WHERE id=? AND owner=? AND project=? AND status='proposed'", (proposal_id, actor.user_id, project))
            if not changed.rowcount:
                raise ValueError('Unknown or inactive own proposal')
            self._event(db, actor, project, 'rejected', {'proposal_id': proposal_id})

    def activate(self, actor, project, *, proposal_id=None, rollback_revision=None, public_synthetic=False):
        if (proposal_id is None) == (rollback_revision is None) or type(public_synthetic) is not bool:
            raise ValueError('Choose a proposal or rollback revision')
        self.require(actor, project, write=True, scope='persona:approve' if proposal_id else 'persona:rollback')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            active = self._active(db, actor, project)
            prefs, reason = self._target(db, actor, project, active, proposal_id, rollback_revision)
            revision = db.execute('SELECT MAX(revision)+1 FROM tr_personas WHERE owner=? AND project=?', (actor.user_id, project)).fetchone()[0]
            version = {'revision': revision, 'preferences': preferences(prefs), 'data_policy': 'PUBLIC_SYNTHETIC' if public_synthetic else 'PRIVATE',
                       'reason': reason, 'created_at': datetime.now(UTC).isoformat()}
            db.execute('INSERT INTO tr_personas VALUES (?,?,?,?)', (actor.user_id, project, revision, encoded(version)))
            db.execute('UPDATE tr_active SET revision=? WHERE owner=? AND project=?', (revision, actor.user_id, project))
            if proposal_id:
                db.execute("UPDATE tr_proposals SET status='applied' WHERE id=? AND owner=? AND project=?", (proposal_id, actor.user_id, project))
            db.execute("UPDATE tr_proposals SET status='stale' WHERE owner=? AND project=? AND status='proposed'", (actor.user_id, project))
            self._event(db, actor, project, 'activated', version)
        return version

    def _target(self, db, actor, project, active, proposal_id, rollback):
        if rollback is not None:
            row = db.execute('SELECT payload FROM tr_personas WHERE owner=? AND project=? AND revision=?', (actor.user_id, project, rollback)).fetchone()
            if row is None:
                raise ValueError('Unknown own project revision')
            return json.loads(row[0])['preferences'], 'rollback:'+str(rollback)
        row = db.execute('SELECT payload,status FROM tr_proposals WHERE id=? AND owner=? AND project=?', (proposal_id, actor.user_id, project)).fetchone()
        if row is None:
            raise PermissionError('Proposal owner/project mismatch')
        proposal = json.loads(row[0])
        raw = db.execute('SELECT payload FROM semantics WHERE user_id=?', (actor.user_id,)).fetchone()
        semantic = json.loads(raw[0]) if raw else {}
        if (row[1] != 'proposed' or not proposal['replay'].get('functional_check') or
                proposal['baseline'] != active or proposal['legacy_sha256'] != digest(semantic) or
                proposal['feedback_snapshot'] != self._examples(db, actor, project)):
            raise ValueError('Stale or unchecked proposal; generate again')
        return proposal['candidate_preferences'], 'approved:'+proposal_id

    @staticmethod
    def _event(db, actor, project, kind, payload):
        db.execute('INSERT INTO tr_persona_events(owner,project,kind,payload,created_at) VALUES (?,?,?,?,?)',
                   (actor.user_id, project, kind, encoded(payload), datetime.now(UTC).isoformat()))
