"""Separate history/preference grants; persisted reports do not acquire retransmission rights."""
import copy

from .approvals import digest
from .real import RealBlocked


def memory_subject(kind, user_id, project_id, record):
    return {'kind': kind, 'user_id': user_id, 'project_id': project_id, 'record': copy.deepcopy(record)}


def load_memory(store, actor, user_id, question, environment, policy):
    # The existing authorizer is authoritative, not the identity in a grant or Persona.
    store.authorizer.require(actor, user_id, 'memory:read')
    policy.memory_access = lambda: store.authorizer.require(actor, user_id, 'memory:read')
    semantic = store.semantic(actor, user_id)
    approved = semantic if semantic.get('explicitly_approved') else {}
    if approved:
        if approved.get('data_policy') not in {'PUBLIC', 'PUBLIC_SYNTHETIC'}:
            raise RealBlocked('PRIVATE or unclassified preference cannot leave this application')
        subject = memory_subject('preference', user_id, environment['project_id'], approved)
        policy.register_memory(subject, lambda: memory_subject('preference', user_id, environment['project_id'], store.semantic(actor, user_id)))
    history = []
    for record in store.search(actor, user_id, question):
        if not record['query'].startswith('[project='+environment['project_id']+']'):
            continue
        subject = memory_subject('history', user_id, environment['project_id'], record)
        grant = policy.register_memory(subject, history_reader(store, actor, user_id, environment['project_id'], record['id']))
        history.append({'memory_id': record['id'], 'question': record['query'].split('] ', 1)[-1],
                        'summary': record['response'][:500], 'data_policy': 'PUBLIC_APPROVED',
                        'approval_id': grant['approval_id'], 'record_sha256': digest(subject)})
    return approved, history


def history_reader(store, actor, user_id, project_id, identifier):
    def read():
        store.authorizer.require(actor, user_id, 'memory:read')
        with store.connect() as database:
            row = database.execute('SELECT id,session_id,query,response,confirmed,created_at FROM episodes WHERE id=? AND user_id=?',
                                   (identifier, user_id)).fetchone()
        if row is None:
            raise RealBlocked('Memory unavailable')
        record = dict(zip(('id', 'session_id', 'query', 'response', 'confirmed', 'created_at'), row))
        return memory_subject('history', user_id, project_id, record)
    return read
