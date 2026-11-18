"""Preference-following MODEL STUB only. Real modes never invoke this selection logic."""
import copy

from .persona_preferences import APIS, effective


def search_plan(context):
    from .mock import search_plan as legacy_plan
    baseline = copy.deepcopy(context)
    persona = baseline['approved_preferences'].pop('research_persona')
    original = legacy_plan(baseline)
    env = context['environment']
    prefs = context.get('persona_guidance', effective(persona['preferences'], env, context['question']))['preferences']
    if env['depth'] == 'restricted':
        return original
    apps = prefs.get('preferred_apps')
    if apps is None and prefs.get('preferred_apis'):
        apps = [api.split('/')[0] for api in prefs['preferred_apis']]
    if apps is None:
        plans = original
    else:
        plans = []
        query = 'hydrogen 수소환원제철' if env['topic'] == 'H' else 'NCM LFP 양극재'
        company = next((item['corp_code'] for item in context['entity_catalog']), None)
        for app in apps:
            rp = {'query': query}
            op = {}
            if app == 'kipris_plus':
                rp['jurisdiction'] = 'KR'
            if app == 'opendart':
                if company is None:
                    continue
                rp = {'corp_code': company, 'from_date': '2025-10-01' if env['depth'] == 'quick' else '2022-01-01', 'to_date': env['cutoff']}
                op = {'keyword': query, 'report_type': 'material'}
            if app == 'posco_ir':
                op = {'kind': 'strategy', 'language': 'ko'}
            plans.append((app+'__'+APIS[app], {'rp': rp, 'op': op}))
    return [configure(name, arguments, prefs, env) for name, arguments in plans]


def configure(name, arguments, prefs, environment):
    arguments = copy.deepcopy(arguments)
    app = name.split('__')[0]
    if name.endswith('__read_financials'):
        return name, arguments
    target = arguments['rp' if app == 'opendart' else 'op']
    dates = {'from_date': prefs.get('search_from_date', target.get('from_date', '2025-10-01' if environment['depth'] == 'quick' else '2022-01-01')),
             'to_date': environment['cutoff']}
    target.update(dates)
    arguments['op']['limit'] = prefs.get('result_limit', arguments['op'].get('limit',3 if environment['depth'] == 'quick' else 5))
    if app != 'opendart':
        arguments['op']['sort'] = prefs.get('sort', {}).get(app, arguments['op'].get('sort','date_desc'))
    if app == 'openalex' and set(prefs.get('criteria', [])) & {'experimental_conditions', 'reproducibility'}:
        arguments['rp']['query'] += ' 실험 조건 재현성'
    return name, arguments


def format_report(text, preferences):
    style = preferences.get('report_format')
    if style == 'table':
        return '| 구분 | 내용 |\n|---|---|\n'+'\n'.join('| 조사 | '+line.replace('|', r'\|')+' |' for line in text.splitlines() if line)
    if style == 'bullets':
        return '\n'.join('- '+line for line in text.splitlines() if line)
    return text
