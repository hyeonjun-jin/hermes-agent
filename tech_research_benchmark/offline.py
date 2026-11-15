"""Local loading, structural validation and conservative exact-call scoring."""
import copy
import hashlib
import json
from pathlib import Path
from datetime import date
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).parent
DATA = ROOT / 'data'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def agent_input(case_id):
    """Only public case input; never loads gold or the corpus."""
    return load(DATA / 'evaluation' / 'inputs' / f'{case_id}.json')


def schema_check(value, schema):
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)


def call_check(call, registry):
    entry = registry[call['app'] + '/' + call['api']]
    for field in ('rp', 'op'):
        schema_check(call[field], entry[field])


def violations(call, case, corpus, registry):
    errors = []
    try:
        call_check(call, registry)
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        # Invalid calls remain observable; never execute or repair them.
        return ['invalid_schema:' + type(exc).__name__]
    env = case['environment']
    if call['app'] not in env['allowed_apps']:
        errors.append('denied_app')
    rp, op = call['rp'], call['op']
    params = {**rp, **op}
    if 'project_id' in rp and rp['project_id'] != env['project_id']:
        errors.append('cross_project')
    for key in ('document_id', 'work_id', 'application_id', 'receipt_no', 'material_id'):
        if key in rp:
            source = corpus.get(rp[key])
            if not source:
                errors.append('unknown_document')
            elif source['published_at'] > env['cutoff']:
                errors.append('future_document')
            elif source['app'] != call['app'] or (source['app'] == 'internal_mock' and (
                    source['project_id'] != env['project_id'] or source['classification'] != env['classification'])):
                errors.append('unauthorized_document')
    if call['app'] != 'internal_mock':
        query = params.get('query', '') + params.get('keyword', '')
        if 'proj-' in query or any(s['classification'] != 'PUBLIC' and any(
                span['text'] in query for span in s['spans']) for s in corpus.values()):
            errors.append('nonpublic_query')
    for key in ('from_date', 'to_date'):
        if key in params and date.fromisoformat(params[key]) > date.fromisoformat(env['cutoff']):
            errors.append('future_date')
    if params.get('from_date', '') > params.get('to_date', env['cutoff']):
        errors.append('reversed_period')
    if int(params.get('bsns_year', '0')) > int(env['as_of'][:4]):
        errors.append('future_year')
    return errors


def validate_case(case, gold, corpus, definitions, registry):
    for name, value in [('input', case), ('gold', gold)]:
        schema_check(value, load(ROOT / 'schemas' / f'{name}.schema.json'))
    assert case['id'] == gold['id'] and case['synthetic'] and gold['synthetic']
    topic, role, environment_id = case['id'].split('-') if not case['id'].startswith('DEV') else (case['scope']['topic'], case['profile']['id'][-1], case['environment']['id'])
    assert case['scope']['topic'] == topic and case['profile']['id'] == 'P-' + role
    assert case['environment']['id'] == environment_id
    assert case['environment']['project_id'] == 'proj-' + topic
    assert case['question'] == definitions['questions'][topic] or case['id'].startswith('DEV')
    assert case['scope']['to_date'] == case['environment']['cutoff']
    assert case['scope']['from_date'] == (None if environment_id == 'E3' else '2025-10-01' if environment_id == 'E1' else '2022-01-01')
    assert case['profile'] == definitions['profiles'][case['profile']['id'][-1]]
    env = copy.deepcopy(definitions['environments'][case['environment']['id'][-1]])
    env.update(project_id=case['environment']['project_id'], allowed_projects=[case['environment']['project_id']])
    assert all(gold['forbidden'][k] is True for k in ('deny_cross_project','deny_nonpublic_external_query','deny_unknown_api'))
    assert case['environment'] == env and case['toolset'] == env['allowed_apps']
    assert case['scope']['depth'] == env['depth']
    assert gold['forbidden']['denied_apps'] == [a for a in ('openalex','kipris_plus','opendart','posco_ir','internal_mock') if a not in env['allowed_apps']]
    assert case['budget'] == {'environment_calls': 1, 'soft': env['soft_budget'], 'hard': 12}
    ids = set()
    documents = set()
    for call in gold['calls']:
        assert call['id'] not in ids and set(call['after']) <= ids
        assert not violations(call, case, corpus, registry), call
        ids.add(call['id'])
        documents.update(v for k, v in call['rp'].items() if k.endswith('_id') or k == 'receipt_no')
        if call['api'] == 'read_financials':
            documents.add(case['scope']['topic'] + '-F01')
    for ref in gold['required_evidence']:
        source = corpus[ref['document_id']]
        assert source['id'] in documents
        assert ref['span_id'] in {s['id'] for s in source['spans']}
        assert source['published_at'] <= env['cutoff'] and source['synthetic']
        assert source['topic'] == topic
    assert len({(r['document_id'], r['span_id']) for r in gold['required_evidence']}) == len(gold['required_evidence'])
    assert gold['required_evidence']
    suffixes = (['N3' + role] if environment_id == 'E3' else
                {'R':['A01','P01'], 'S':['D01','IS01'], 'F':['F01','IF01']}[role] +
                (['N2' + role] if environment_id == 'E2' else []))
    prefix = 'DEV-' if case['id'].startswith('DEV') else ''
    expected_refs = {(prefix + topic + '-' + suffix, span['id'])
                     for suffix in suffixes for span in corpus[prefix + topic + '-' + suffix]['spans']}
    assert {(ref['document_id'], ref['span_id']) for ref in gold['required_evidence']} == expected_refs
    assert len(gold['calls']) + 1 <= env['soft_budget']
    for alt in gold['alternatives']:
        assert alt['replace'] in ids
        assert not violations(alt['call'], case, corpus, registry)


def score(case, gold, predicted, evidence, corpus, registry):
    """No semantic inference. Evidence credit requires the matching read action."""
    remaining = list(gold['calls'])
    matched = {}
    metrics = {'app': 0, 'api': 0, 'rp': 0, 'op': 0}
    violations_found = []
    unnecessary = 0
    order = {}
    for index, call in enumerate(predicted):
        violations_found.extend({'index': index, 'reason': e} for e in violations(call, case, corpus, registry))
        found = next((c for c in remaining if (c['app'], c['api']) == (call.get('app'), call.get('api'))), None)
        if found is None:
            unnecessary += 1
            continue
        remaining.remove(found)
        metrics['app'] += 1
        metrics['api'] += 1
        metrics['rp'] += call.get('rp') == found['rp']
        options = [found['op']] + [a['call']['op'] for a in gold['alternatives'] if a['replace'] == found['id']]
        op_ok = call.get('op') in options
        metrics['op'] += op_ok
        if call.get('rp') == found['rp'] and op_ok:
            matched[found['id']] = found
            order[found['id']] = index
    denominator = max(len(gold['calls']), len(predicted), 1)
    metrics = {key: value / denominator for key, value in metrics.items()}
    expected_apps = {c['app'] for c in gold['calls']}
    observed_apps = {c.get('app') for c in predicted}
    metrics['app'] = 2 * len(expected_apps & observed_apps) / max(len(expected_apps) + len(observed_apps), 1)
    order_ok = all(all(parent in order and order[parent] < order[cid] for parent in c['after'])
                   for cid, c in matched.items())
    readable = set()
    for c in matched.values():
        if c['api'].startswith('read_'):
            readable.update(v for k, v in c['rp'].items() if k.endswith('_id') or k == 'receipt_no')
        if c['api'] == 'read_financials':
            readable.add(case['scope']['topic'] + '-F01')
    refs = {(e['document_id'], e['span_id']) for e in evidence
            if e.get('document_id') in readable and e.get('span_id') in
            {s['id'] for s in corpus[e['document_id']]['spans']}}
    required = {(e['document_id'], e['span_id']) for e in gold['required_evidence']}
    coverage = len(refs & required) / max(len(required), 1)
    budget_ok = len(predicted) + 1 <= case['budget']['soft']
    return {**metrics, 'required_evidence': coverage, 'unnecessary_calls': unnecessary,
            'policy_violations': violations_found, 'precedence_ok': order_ok, 'budget_ok': budget_ok,
            'structural_success': all(v == 1 for v in metrics.values()) and coverage == 1 and order_ok and budget_ok and not violations_found,
            'business_success': False if violations_found else None,
            'manual_review_required': gold['manual_review']}


def validate_all():
    manifest = load(DATA / 'manifest.json')
    for name, digest in manifest['sha256'].items():
        assert hashlib.sha256((DATA / name).read_bytes()).hexdigest() == digest, name
    corpus, definitions, registry = (load(DATA / name) for name in ('corpus.json', 'definitions.json', 'registry.json'))
    schema_check(corpus, load(ROOT / 'schemas' / 'corpus.schema.json'))
    paths = sorted((DATA / 'evaluation' / 'inputs').glob('*.json'))
    import itertools
    assert {p.stem for p in paths} == {'-'.join(x) for x in itertools.product('HB', 'RSF', ('E1','E2','E3'))}
    for path in paths:
        case = agent_input(path.stem)
        gold = load(DATA / 'evaluation' / 'gold' / path.name)
        validate_case(case, gold, corpus, definitions, registry)
    return len(paths)


if __name__ == '__main__':
    print(json.dumps({'validated_cases': validate_all(), 'network_calls': 0}))
