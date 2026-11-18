"""Owner-edited development profiles, separate from Persona/Memory and never auto-exported."""
import copy
import re

FIELDS = {'business_unit', 'department', 'job', 'expertise', 'interests', 'criteria'}


def updated_profile(original, changes):
    if not isinstance(changes, dict) or set(changes)-FIELDS:
        raise ValueError('Profile fields cannot change identity, permissions or Persona')
    for field, value in changes.items():
        values = value if field == 'interests' else [value]
        if (not isinstance(values, list) or (field == 'interests' and not 0 <= len(values) <= 10) or
                any(not isinstance(v, str) or not v.strip() or len(v) > 200 or
                    any(ord(c) < 32 for c in v) or re.search(r'sk-(?:proj-)?[\w-]{20,}', v) for v in values)):
            raise ValueError('Profile values must be bounded text; interests is a list of at most ten topics')
    return {**copy.deepcopy(original), **copy.deepcopy(changes)}


class ProfileDirectory:
    """Process-local development edits; no database migration or inference from history."""
    def __init__(self, defaults):
        self.defaults = copy.deepcopy(defaults)
        self.edits = {}

    def get(self, user_id):
        return copy.deepcopy(self.edits.get(user_id, self.defaults[user_id]))

    def update(self, user_id, changes):
        self.edits[user_id] = updated_profile(self.get(user_id), changes)
        return self.get(user_id)

    def reset(self, user_id):
        self.edits.pop(user_id, None)

    def is_default(self, user_id):
        return self.get(user_id) == self.defaults[user_id]
