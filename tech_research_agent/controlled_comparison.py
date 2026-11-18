"""Offline input-isolation rehearsal. No real mode, paid budget or source connector is accepted."""
import argparse
import copy
import json
from pathlib import Path

from .approvals import digest
from .config import runtime
from .persona_replay import TechnicalMockReplay
from persona_prototype.mini_validation import MODEL, ENDPOINT, RATES

QUESTION = '수소환원제철을 비교 조사해주세요.'
BASELINE = {'preferred_apps': ['openalex'], 'lookback_months': 12, 'result_limit': 3,
            'technical_detail': 'brief', 'criteria': ['experimental_conditions'], 'report_format': 'bullets'}
CANDIDATE = {'preferred_apps': ['kipris_plus'], 'lookback_months': 36, 'result_limit': 2,
             'technical_detail': 'detailed', 'criteria': ['claim_scope'], 'report_format': 'table'}


def run():
    """Use only synthetic, disposable copies; labels v1/v2 do not install Persona versions."""
    user = 'researcher'
    profile, environment, _ = runtime(user, 'H', 'quick')
    semantic = {'source_focus': 'science', 'explicitly_approved': True, 'data_policy': 'PRIVATE'}
    episodes = [{'session_id': 'fixed-offline-history', 'query': '[project=proj-H] '+QUESTION,
                 'response': 'SYNTHETIC 수소환원제철의 과거 검토 기록. 최신 결과는 재확인해야 합니다.',
                 'confirmed': True, 'created_at': '2026-09-01T00:00:00+00:00'}]
    baseline = {'revision': 1, 'preferences': copy.deepcopy(BASELINE), 'data_policy': 'PRIVATE',
                'reason': 'offline fixture only', 'created_at': '2026-09-01T00:00:00+00:00'}
    turn = {'environment': environment, 'question': QUESTION, 'input_snapshot': {'profile': profile}}
    replay = TechnicalMockReplay().compare(user, baseline, CANDIDATE, turn, semantic,
                                            initial_episodes=episodes, fixed_revision=2)
    inputs = {}
    for label in ('before', 'after'):
        snapshot = replay[label]['input']
        inputs[label] = {key: snapshot[key] for key in ('profile', 'environment', 'history', 'persona_revision')}
        inputs[label].update(user=user, question=QUESTION, initial_episodes=episodes, legacy_semantic=semantic,
                             model='technical-research-mock', max_tokens=1024,
                             allowed_sources=environment['allowed_sources'])
    matched = inputs['before'] == inputs['after']
    return {'mode': 'offline_mock', 'paid_calls': 0, 'external_source_calls': 0,
            'actual_api_usage': {'input_tokens': 0, 'output_tokens': 0, 'estimated_usd': 0},
            'quality_verdict': 'not_evaluated', 'fixed_inputs': inputs['before'],
            'fixed_input_sha256': {key: digest(value) for key, value in inputs.items()},
            'inputs_match': matched, 'functional_check': matched and replay['functional_check'],
            'conditions': {'v1': BASELINE, 'v2': CANDIDATE}, 'outcomes': replay,
            'live_plan': {'model': MODEL, 'endpoint': ENDPOINT, 'max_tokens': 512, 'remote_retries': 0,
                          'r3_pair_minimum_calls': 12, 'r2_pair_minimum_calls': 10, 'pricing': RATES,
                          'go': False, 'reason': 'Requires ledger availability, role-cap, cost and egress review; no paid path in this runner'},
            'limitations': ['Scripted decisions are not LLM evidence; mock token usage is not actual API usage.',
                            'Only Offline revision metadata is normalized to 2; real approved versions must not be rewritten.',
                            'Fixed-input equality covers application snapshots, not complete Hermes wire prompts/session metadata.',
                            'Multiple preference dimensions change together; effects cannot be attributed to one dimension.',
                            'Live documents, model snapshot, generation defaults and stochasticity remain future controls.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().name == 'usage.json':
        parser.error('An operating usage ledger is never an experiment output')
    # Exclusive creation also rejects existing files and symlinks; never overwrite a ledger/report.
    with args.output.open('x', encoding='utf-8') as stream:
        report = run()
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print('Offline Mock only; report:', args.output)
    return 0 if report['functional_check'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
