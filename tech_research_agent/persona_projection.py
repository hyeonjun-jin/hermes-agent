"""Administrator-reviewed minimal expressions; PRIVATE Persona records are never relabelled."""
import copy

from .approvals import digest
from .approved_memory import memory_subject
from .persona_preferences import preferences
from .real import RealBlocked


def public_persona_subject(user_id, project_id, source, fields):
    """Prepare a subject for a server administrator to review, not an approval or a transmission."""
    persona = source['research_persona']
    values = preferences(persona['preferences'])
    if (source.get('explicitly_approved') is not True or type(persona['version']) is not int or persona['version'] < 1
            or not isinstance(fields, (list, tuple)) or not fields
            or any(not isinstance(field, str) or field not in values for field in fields)
            or len(fields) != len(set(fields))):
        raise ValueError('Invalid minimal Persona expression')
    record = {'explicitly_approved': True, 'data_policy': 'PUBLIC',
              'research_persona': {'version': persona['version'],
                                   'preferences': {field: values[field] for field in sorted(fields)}}}
    subject = memory_subject('preference', user_id, project_id, record)
    subject['persona_binding'] = {'revision': persona['version'], 'content_sha256': digest(source)}
    return subject


def load_projection(policy, source, reader, user_id, project_id):
    if reader is None:
        raise RealBlocked('PRIVATE Persona requires a current reader and an exact administrator projection grant')
    if digest(reader()) != digest(source):
        raise RealBlocked('Persona changed before projection selection')
    matches = {}
    for grant in policy.registry.eligible_persona_projections(policy.adapter.context):
        subject = grant['subject']
        try:
            fields = list(subject['record']['research_persona']['preferences'])
            expected = public_persona_subject(user_id, project_id, source, fields)
        except (KeyError, TypeError, ValueError):
            continue
        if subject == expected:
            matches[digest(subject)] = (subject, fields)
    if len(matches) != 1:
        raise RealBlocked('Exactly one current administrator-reviewed Persona expression is required')
    subject, fields = next(iter(matches.values()))

    def current():
        try:
            return public_persona_subject(user_id, project_id, reader(), fields)
        except (KeyError, TypeError, ValueError) as exc:
            raise RealBlocked('Current Persona no longer supports the approved expression') from exc

    policy.register_memory(subject, current)
    return copy.deepcopy(subject['record'])
