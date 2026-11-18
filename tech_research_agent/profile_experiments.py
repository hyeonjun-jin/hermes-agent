"""Offline functional comparisons and hash-only live preparation; no live sender or scorer."""
import copy
import json
from pathlib import Path
import tempfile
import sqlite3
from contextlib import closing

from .application import ResearchApplication, principal
from .approvals import digest
from .paired_comparison import input_snapshot
from .profiles import updated_profile
from .config import runtime
from .provider import ResearchProvider

QUESTION = '수소환원제철 관련 논문 추천과 근거를 알려주세요.'
INTERESTS = {'mechanism': ['수소환원 반응 메커니즘'], 'optimization': ['수소환원 공정 최적화']}


def live_preparation(app, actor, question, *, topic='H', mode='quick'):
    """Read local inputs only. This is not a live runner, approval, grant or budget mutation."""
    _, environment, adapter = runtime(actor.user_id, topic, mode, connectors=app.source_connectors)
    app.personas.require(actor, environment['project_id'])
    prefix = '[project='+environment['project_id']+'] '
    with closing(sqlite3.connect(app.store.path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        persona = db.execute('SELECT v.payload FROM tr_personas v JOIN tr_active a '
            'ON v.owner=a.owner AND v.project=a.project AND v.revision=a.revision WHERE v.owner=? AND v.project=?',
            (actor.user_id, environment['project_id'])).fetchone()
        episodes = db.execute('SELECT * FROM episodes WHERE user_id=? AND substr(query,1,length(?))=? ORDER BY id',
                              (actor.user_id, prefix, prefix)).fetchall()
        semantic = db.execute('SELECT payload FROM semantics WHERE user_id=?', (actor.user_id,)).fetchone()
    fixed = {'profile': app.profile(actor, actor.user_id), 'environment': environment, 'question': question,
             'episodes': episodes, 'semantic': semantic, 'schemas': {
                 role: ResearchProvider(role, adapter, {}).get_tool_schemas() for role in ('research', 'analysis', 'verification')}}
    return {'status': 'NO-GO', 'live_execution_enabled': False, 'paid_calls': 0,
        'inputs_sha256': {key: digest(value) for key, value in fixed.items()},
        'persona_sha256': digest(persona), 'persona_exists': persona is not None,
        'profile_is_default_synthetic': app.profiles.is_default(actor.user_id),
        'required': ['administrator_review_of_minimal_profile_and_interest_export',
            'question_and_document_processing_grants', 'persona_and_memory_export_grants_if_used',
            'source_access_and_model_identity_review', 'pinned_usage_plan_and_cost_ceiling',
            'explicit_paid_execution_approval_bound_to_new_inputs'],
        'compare': ['APP/API/RP/OP', 'source_search_and_read_ids', 'raw_research_analysis_verification',
                    'final_recommendation_components', 'model_attempts_tokens_and_cost'],
        'limitation': 'Edited profiles are PRIVATE; existing approved_public does not grant Profile export. '
                      'PairedPublicComparison remains a Persona-only experiment and rejects changed fixed Profiles.'}


def run_offline_comparison():
    experiments = {}
    with tempfile.TemporaryDirectory(prefix='research-profile-comparison-') as directory:
        definitions = {'job': [('researcher', 'researcher', None), ('strategy', 'strategy', None)],
                       'interests': [(name, 'researcher', values) for name, values in INTERESTS.items()]}
        for experiment, conditions in definitions.items():
            arms = {}
            for label, user, interests in conditions:
                app = ResearchApplication(Path(directory)/experiment/label)
                actor = principal(user)
                if interests is not None:
                    app.update_profile(actor, user, {'interests': interests})
                initial, persona = input_snapshot(app, actor, 'H', 'quick', QUESTION)
                result = app.ask(actor, user, QUESTION)
                arms[label] = {'profile': initial['profile'], 'fixed_inputs': {
                    key: digest(initial[key]) for key in ('environment', 'question', 'episodes', 'semantic', 'schemas')},
                    'persona_sha256': digest({k: persona[k] for k in ('revision', 'preferences', 'data_policy')}),
                    'excluded_persona_metadata': 'created_at/reason are not model inputs',
                    'profile_except_interests_sha256': digest(
                        updated_profile(initial['profile'], {'interests': []})),
                    'candidate_ids': result['paper_recommendations']['candidate_ids'],
                    'evidence_sha256': digest(sorted(result['evidence'], key=lambda item: item['source_id'])),
                    'permissions_sha256': digest(initial['permissions']),
                    'recommendations': result['paper_recommendations']['items'], 'complete': result['complete'],
                    'evidence_ids': sorted(i['source_id'] for i in result['evidence']),
                    'tool_calls': [copy.deepcopy(e['plan']) for e in result['trace']],
                    'analysis': next(s['raw_answer'] for s in result['stages'] if s['role'] == 'analysis'),
                    'mock_model_calls': result['model_calls'], 'initial_memory_empty': not initial['episodes'] and not initial['semantic']}
            experiments[experiment] = arms
    return {'mode': 'offline_synthetic_mock', 'paid_calls': 0, 'external_source_calls': 0,
            'performance_verdict': 'not_evaluated', 'experiments': experiments,
            'live_readiness': 'NO-GO: explicit execution, Profile export and existing source/document/Persona/Memory approvals required'}


if __name__ == '__main__':
    print(json.dumps(run_offline_comparison(), ensure_ascii=False, indent=2))
