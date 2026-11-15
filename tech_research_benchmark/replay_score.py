"""Evaluator-only bridge; keep Gold outside OfflineAdapter and Agent inputs."""
from .offline import score


def score_replay(case, gold, replay_payload, corpus, registry):
    report = score(case, gold, replay_payload['predicted'], replay_payload['evidence'], corpus, registry)
    report['policy_audit'] = replay_payload['policy_audit']
    report['mock_units'] = replay_payload['mock_units']
    report['attempts'] = replay_payload['attempts']
    report['execution_failures'] = replay_payload['execution_failures']
    if report['policy_audit']:
        report.update(business_success=False, structural_success=False)
    if report['execution_failures']:
        report['structural_success'] = False
    return report
