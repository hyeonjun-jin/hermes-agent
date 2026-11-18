"""Bounded research preferences, never authorization or arbitrary instructions."""
import copy
from datetime import date

APIS = {'openalex': 'search_works', 'kipris_plus': 'search_patents',
        'opendart': 'list_disclosures', 'posco_ir': 'search_materials'}
DIMENSIONS = ('sources', 'scope_recency', 'depth', 'technical_detail', 'business_detail', 'financial_detail', 'report')
CRITERIA = {'experimental_conditions', 'reproducibility', 'claim_scope', 'condition_matched_comparison',
            'commercialization', 'financial_risk'}


def preferences(value):
    if not isinstance(value, dict) or set(value)-{'preferred_apps', 'preferred_apis', 'lookback_months', 'result_limit',
                                                 'sort', 'depth', 'technical_detail', 'business_detail', 'financial_detail',
                                                 'criteria', 'report_format'}:
        raise ValueError('Unsupported research preference; permissions and free instructions cannot be aligned')
    for key, item in value.items():
        validate_field(key, item)
    return copy.deepcopy(value)


def validate_field(key, value):
    enums = {'depth': {'brief', 'detailed'}, 'technical_detail': {'brief', 'detailed'},
             'business_detail': {'brief', 'detailed'}, 'financial_detail': {'brief', 'detailed'},
             'report_format': {'bullets', 'table', 'explanation'}}
    if key in enums:
        valid = isinstance(value, str) and value in enums[key]
    elif key in {'lookback_months', 'result_limit'}:
        valid = type(value) is int and (value in {6, 12, 36, 60} if key == 'lookback_months' else 1 <= value <= 10)
    elif key in {'preferred_apps', 'preferred_apis', 'criteria'}:
        allowed = set(APIS) if key == 'preferred_apps' else {app+'/'+api for app, api in APIS.items()} if key == 'preferred_apis' else CRITERIA
        valid = (isinstance(value, list) and bool(value) and all(isinstance(v, str) and v in allowed for v in value)
                 and len(value) == len(set(value)))
    elif key == 'sort':
        valid = (isinstance(value, dict) and bool(value) and not set(value)-set(APIS) and
                 all(isinstance(v, str) and v in ({'date_desc'} if app == 'kipris_plus' else
                      {'date_desc', 'relevance'} if app in {'posco_ir', 'opendart'} else
                      {'date_desc', 'relevance', 'citations_desc'}) for app, v in value.items()))
        # OpenDART exposes no sort OP in the current registry.
        valid = valid and 'opendart' not in value
    else:
        valid = False
    if not valid:
        raise ValueError('Invalid research preference: '+key)


def memory_record(version):
    if version['revision'] == 1 and not version['preferences']:
        return None
    return {'explicitly_approved': True, 'data_policy': version['data_policy'],
            'research_persona': {'version': version['revision'], 'preferences': preferences(version['preferences'])}}


def combine(legacy, aligned):
    if aligned is None:
        return copy.deepcopy(legacy)
    result = {**copy.deepcopy(legacy), **copy.deepcopy(aligned)}
    if legacy and legacy.get('data_policy') not in {'PUBLIC', 'PUBLIC_SYNTHETIC'}:
        result['data_policy'] = 'PRIVATE'
    return result


def effective(value, environment, question):
    """Advisory decision inputs; this function never invokes or rewrites a Tool Call."""
    prefs = preferences(value)
    notes = []
    if 'preferred_apps' in prefs:
        prefs['preferred_apps'] = [app for app in prefs['preferred_apps'] if app in environment['allowed_sources']]
    if '논문만' in question:
        prefs['preferred_apps'] = ['openalex'] if 'openalex' in environment['allowed_sources'] else []
        notes.append('current_request_papers_only')
    elif '재무 중심' in question:
        prefs['preferred_apps'] = [app for app in ('opendart', 'posco_ir') if app in environment['allowed_sources']]
        notes.append('current_request_finance')
    if 'preferred_apis' in prefs:
        prefs['preferred_apis'] = [api for api in prefs['preferred_apis'] if api.split('/')[0] in environment['allowed_sources']
                                   and api.split('/')[0] in prefs.get('preferred_apps', APIS)]
    if 'result_limit' in prefs:
        prefs['result_limit'] = min(prefs['result_limit'], 3 if environment['depth'] != 'deep' else 5)
    if 'lookback_months' in prefs:
        end = date.fromisoformat(environment['cutoff'])
        month = end.year*12+end.month-prefs['lookback_months']
        start = date(month//12, month%12+1, 1)
        floor = date(end.year-1, end.month+1, 1) if end.month < 12 else date(end.year, 1, 1)
        if environment['depth'] == 'deep':
            floor = date(2022, 1, 1)
        prefs['search_from_date'] = max(start, floor).isoformat()
    return {'preferences': prefs, 'overrides': notes,
            'priority': ['server_policy', 'current_environment_and_request', 'approved_persona', 'legacy_preferences', 'history'],
            'report_is_not_tool_op': True, 'causal_proof': False}


def resolve(approved, environment, question, profile):
    """Canonical advisory view only; never mutate stored Memory or rewrite model Tool Calls."""
    result = copy.deepcopy(approved)
    persona = result.get('research_persona', {}).get('preferences', {})
    guidance = effective(persona, environment, question)
    explicit = bool(guidance['overrides'])
    source_choice = explicit or bool(set(persona) & {'preferred_apps', 'preferred_apis'})
    legacy = result.get('source_focus')
    if source_choice:
        result.pop('source_focus', None)  # Keep conflicting Legacy preference in storage, not in the model view.
    elif legacy not in {'science', 'strategy', 'finance', 'papers_only'}:
        result.pop('source_focus', None)
    guidance['source_focus'] = ('papers_only' if 'current_request_papers_only' in guidance['overrides'] else
                              'finance' if 'current_request_finance' in guidance['overrides'] else
                              None if source_choice else result.get('source_focus', profile['focus']))
    guidance['field_sources'] = {key: 'approved_persona' for key in guidance['preferences']}
    for key in ('preferred_apps', 'preferred_apis', 'result_limit', 'search_from_date'):
        if key in guidance['preferences'] and guidance['preferences'].get(key) != persona.get(key):
            guidance['field_sources'][key] = 'current_environment_and_request'
    guidance['field_sources']['source_focus'] = ('current_environment_and_request' if explicit else
        'approved_persona' if source_choice else 'legacy_preferences' if 'source_focus' in result else 'profile_default')
    guidance['history_usage'] = 'Past observations only; no implicit preference extraction and no override of resolved preferences'
    return result, guidance
