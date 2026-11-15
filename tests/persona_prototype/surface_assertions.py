"""Exact request-surface diagnostics for local fixture model requests only."""
import difflib
import hashlib
import json


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _diff_lines(field, value):
    if field == 'system':
        lines = []
        for index, content in enumerate(value):
            lines.append(f'[system message {index}]')
            lines.extend(content.splitlines() if isinstance(content, str) else _json(content).splitlines())
        return lines
    return _json(value).splitlines()


def surface_report(requests):
    snapshots = [{'system': [m['content'] for m in r['messages'] if m['role'] == 'system'],
                  'tools': r['tools']} for r in requests]
    changes = []
    for index, current in enumerate(snapshots[1:], 1):
        fields = {}
        for field in ('system', 'tools'):
            before, after = snapshots[0][field], current[field]
            if before != after:
                fields[field] = '\n'.join(difflib.unified_diff(
                    _diff_lines(field, before), _diff_lines(field, after),
                    fromfile='request-0/' + field, tofile=f'request-{index}/' + field))
        if fields:
            changes.append({'request_index': index, 'diffs': fields,
                            'system_changed': 'system' in fields, 'tools_changed': 'tools' in fields})
    return {'snapshots': snapshots, 'changes': changes,
            'fingerprints': [{field: hashlib.sha256(_json(s[field]).encode()).hexdigest()
                              for field in ('system', 'tools')} for s in snapshots]}


def assert_stable_surface(requests, artifact):
    report = surface_report(requests)
    artifact.write_text(_json(report) + '\n', encoding='utf-8')
    assert not report['changes'], _json({'artifact': str(artifact), 'changes': report['changes']})
