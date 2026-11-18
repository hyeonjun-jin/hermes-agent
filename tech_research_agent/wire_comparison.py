"""Hash-only inspection of the complete prepared JSON body; no headers or raw text are exported."""
import copy
import hashlib
import json

from .approvals import digest
from .real import RealBlocked

PERSONA_PARTS = {
    'context.approved_preferences.research_persona.preferences',
    'context.persona_guidance.preferences', 'context.persona_guidance.overrides',
    'context.persona_guidance.source_focus', 'context.persona_guidance.field_sources',
}
VERSION_PARTS = {'context.persona_revision', 'context.approved_preferences.research_persona.version'}
RESULT_PARTS = {'context.evidence', 'context.previous_stages', 'context.verification_audit',
                'context.retrieval_limits', 'messages.results', 'messages.layout'}
CONTEXT_KEYS = {'data_label', 'role', 'profile', 'environment', 'question', 'persona_revision',
                'history', 'evidence', 'previous_stages', 'retrieval_limits', 'entity_catalog', 'verification_audit'}
GUIDANCE_KEYS = {'preferences', 'overrides', 'priority', 'report_is_not_tool_op', 'causal_proof',
                 'source_focus', 'field_sources', 'history_usage'}


def opaque(value):
    return {'sha256': digest(value), 'ordered_sha256': ordered_digest(value), 'redacted': True}


def ordered_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def safe_key(value, allowed):
    return value if value in allowed else 'unknown-'+digest(value)


def components(body):
    """Cover every JSON body field, including unrecognized context/message fields, without masking them."""
    systems = [m for m in body['messages'] if m['role'] == 'system']
    if len(systems) != 1 or not isinstance(systems[0].get('content'), str):
        raise RealBlocked('Wire comparison requires one server system message')
    prefix, tail = systems[0]['content'].split('TECH_CONTEXT=', 1)
    context, end = json.JSONDecoder().raw_decode(tail)
    result = {
        'system.instructions': prefix+'TECH_CONTEXT=<CONTEXT>'+tail[end:],
        'system.metadata': {k: v for k, v in systems[0].items() if k != 'content'},
        'messages.users': [m for m in body['messages'] if m['role'] == 'user'],
        'messages.results': [m for m in body['messages'] if m['role'] not in {'system', 'user'}],
        'messages.layout': [m['role'] for m in body['messages']],
        'tools': body.get('tools', {'absent': True}),
        'options': {k: v for k, v in body.items() if k not in {'messages', 'tools'}},
        'context.field_order': list(context),
    }
    for key, value in context.items():
        if key == 'approved_preferences':
            result['context.approved_preferences.field_order'] = list(value)
            for name, item in value.items():
                path = 'context.approved_preferences.'+safe_key(name, {'research_persona', 'data_policy', 'explicitly_approved', 'source_focus'})
                if name == 'research_persona':
                    result[path+'.field_order'] = list(item)
                    result.update({path+'.'+safe_key(k, {'version', 'preferences'}): v for k, v in item.items()})
                else:
                    result[path] = item
        elif key == 'persona_guidance':
            result['context.persona_guidance.field_order'] = list(value)
            result.update({'context.persona_guidance.'+safe_key(k, GUIDANCE_KEYS): v for k, v in value.items()})
        else:
            result['context.'+safe_key(key, CONTEXT_KEYS)] = value
    return context['role'], result


def differences(left, right, *, initial):
    changes = []
    for key in sorted(set(left) | set(right)):
        a, b = left.get(key, {'absent': True}), right.get(key, {'absent': True})
        if ordered_digest(a) == ordered_digest(b):
            continue
        category = ('persona_preferences' if key in PERSONA_PARTS else 'persona_version_metadata'
                    if key in VERSION_PARTS else 'downstream_results' if not initial and key in RESULT_PARTS
                    else 'unexpected_control_difference')
        changes.append({'component': key, 'classification': category, 'v1': opaque(a), 'v2': opaque(b)})
    return changes


class WireComparison:
    """Only digests and named components survive capture; raw bodies are never kept in reports."""
    def __init__(self):
        self._parts = {'v1': {}, 'v2': {}}
        self.records = {'v1': [], 'v2': []}
        self.initial = None
        self.comparisons = []

    def capture(self, condition, body):
        role, parts = components(body)
        sequence = sum(row['role'] == role for row in self.records[condition])+1
        key = (role, sequence)
        # Keep comparison values in memory only; export hashes below, never the values.
        self._parts[condition][key] = copy.deepcopy(parts)
        self.records[condition].append({'role': role, 'ordinal': sequence, 'payload': opaque(body),
            'components': {name: opaque(value) for name, value in parts.items()}})
        if condition == 'v2' and key in self._parts['v1']:
            initial = key == ('research', 1)
            changes = differences(self._parts['v1'][key], parts, initial=initial)
            row = {'role': role, 'ordinal': sequence, 'initial_request': initial, 'differences': changes,
                   'control_passed': not any(c['classification'] == 'unexpected_control_difference' for c in changes)}
            if initial and not any(c['classification'] == 'persona_preferences' for c in changes):
                row['control_passed'] = False
            self.comparisons.append(row)
            if initial:
                self.initial = row
                if not row['control_passed']:
                    raise RealBlocked('Initial paired wire control failed or exported preferences are identical')

    def report(self):
        unmatched = [dict(condition=condition, role=key[0], ordinal=key[1])
                     for condition in ('v1', 'v2') for key in self._parts[condition]
                     if key not in self._parts['v2' if condition == 'v1' else 'v1']]
        return {'capture_boundary': 'Prepared JSON body after policy.before_send, before Stub transport; no headers/TLS capture',
                'records': self.records, 'comparisons': self.comparisons, 'unmatched_requests': unmatched,
                'initial_control_passed': bool(self.initial and self.initial['control_passed']),
                'has_unexpected_differences': any(not row['control_passed'] for row in self.comparisons)}

    def discard_values(self):
        self._parts = {'v1': {}, 'v2': {}}
