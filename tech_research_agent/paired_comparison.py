"""Two real Hermes/approved-public workflows, disabled by default and Stub-only in this release."""
import copy
import tempfile
from dataclasses import asdict
from pathlib import Path

import httpx

from .comparison_real import ComparisonPublicAdapter
from .config import runtime
from .connectors.openalex import OpenAlexConnector
from .provider import ResearchProvider
from .real import RealBlocked
from .stub_workflow import WorkflowStub
from .wire_comparison import WireComparison, opaque
from .paired_records import result_record


def input_snapshot(app, actor, topic, mode, question):
    profile, environment, adapter = runtime(actor.user_id, topic, mode, connectors=app.source_connectors)
    app.personas.require(actor, environment['project_id'])
    persona = app.personas.current(actor, environment['project_id'])
    prefix = '[project='+environment['project_id']+'] '
    with app.store.connect() as db:
        episodes = db.execute('SELECT id,session_id,query,response,confirmed,created_at FROM episodes '
            'WHERE user_id=? AND substr(query,1,length(?))=? ORDER BY id', (actor.user_id, prefix, prefix)).fetchall()
    permissions = {k: getattr(adapter.context, k) for k in ('user_id', 'project_id', 'classification', 'cutoff', 'budget', 'observed_at')}
    permissions.update({k: sorted(getattr(adapter.context, k)) for k in ('allowed_projects', 'allowed_sources', 'revoked', 'private_terms')})
    permissions['document_acl'] = {k: sorted(v) for k, v in adapter.context.document_acl.items()}
    permissions['entity_topics'] = adapter.context.entity_topics
    schemas = {role: ResearchProvider(role, adapter, {}).get_tool_schemas() for role in ('research', 'analysis', 'verification')}
    return {'profile': profile, 'environment': environment, 'question': question, 'episodes': episodes,
            'semantic': app.store.semantic(actor, actor.user_id), 'permissions': permissions, 'schemas': schemas}, persona


def validate_arms(apps, root):
    if set(apps) != {'v1', 'v2'} or apps['v1'].store.path.resolve() == apps['v2'].store.path.resolve():
        raise RealBlocked('Two independent v1/v2 stores are required')
    plans = []
    for label, app in apps.items():
        adapter = app.public_real_adapter
        if (not isinstance(adapter, ComparisonPublicAdapter) or adapter.condition != label
                or adapter.live_execution_approved is not False or not isinstance(adapter.transport, WorkflowStub)):
            raise RealBlocked('Only explicit offline Stub comparison adapters are supported')
        if not app.root.resolve().is_relative_to(root) or not adapter.path.is_relative_to(root):
            raise RealBlocked('Operating state/ledgers are forbidden; use isolated disposable copies')
        if not app.source_connectors or any(not isinstance(c, OpenAlexConnector) or
                not isinstance(c.client._transport, httpx.MockTransport) for c in app.source_connectors.values()):
            raise RealBlocked('Only fabricated OpenAlex MockTransport sources are supported in this rehearsal')
        plans.append(asdict(adapter.comparison_plan))
    if plans[0] != plans[1]:
        raise RealBlocked('Both conditions must share one pinned comparison plan and ledger')


class PairedPublicComparison:
    def __init__(self, factory):
        """factory(root) supplies prepared apps and approvals; this runner creates neither approvals nor Personas."""
        self.factory = factory

    def run(self, actor, question, *, enabled=False, topic='H', mode='quick'):
        base = {'mode': 'stub', 'live_execution_approved': False, 'paid_calls': 0, 'external_source_calls': 0,
                'performance_verdict': 'not_evaluated', 'actual_execution_go': False, 'conditions': {}}
        if not enabled:
            return {**base, 'status': 'disabled'}
        audit = WireComparison()
        with tempfile.TemporaryDirectory(prefix='persona-public-pair-') as directory:
            apps = self.factory(Path(directory))
            try:
                validate_arms(apps, Path(directory).resolve())
                return self._run(apps, actor, question, topic, mode, base, audit)
            finally:
                audit.discard_values()
                for connector in {id(c): c for app in apps.values() for c in app.source_connectors.values()}.values():
                    connector.close()

    def _run(self, apps, actor, question, topic, mode, report, audit):
        snapshots = {label: input_snapshot(app, actor, topic, mode, question) for label, app in apps.items()}
        fixed = {label: values[0] for label, values in snapshots.items()}
        report['fixed_inputs'] = {label: {k: opaque(v) for k, v in values.items()} for label, values in fixed.items()}
        if fixed['v1'] != fixed['v2']:
            return {**report, 'status': 'blocked_initial_inputs', 'wire': audit.report()}
        if snapshots['v1'][1]['preferences'] == snapshots['v2'][1]['preferences']:
            return {**report, 'status': 'blocked_identical_personas', 'wire': audit.report()}
        report['source_personas'] = {label: {'version': value[1]['revision'], 'record': opaque(value[1])}
                                     for label, value in snapshots.items()}
        report['conditions'] = {label: {'status': 'not_started', 'complete': False, 'persona_version': value[1]['revision'],
            'model_attempts': 0, 'actual_api_usage': {'input_tokens': 0, 'output_tokens': 0, 'estimated_usd': 0}}
            for label, value in snapshots.items()}
        tools = {schema['name'] for schemas in fixed['v1']['schemas'].values() for schema in schemas}
        for label in ('v1', 'v2'):
            app = apps[label]
            # v1 execution must not affect v2 initial Memory or its active approved Persona.
            current = input_snapshot(app, actor, topic, mode, question)
            if current != snapshots[label]:
                report['status'] = 'blocked_state_drift'
                break
            adapter, original = app.public_real_adapter, app.public_real_adapter.transport
            def capture(body, *, condition=label, sender=original):
                audit.capture(condition, body)  # RealAdapter already called policy.before_send here.
                return sender(body)
            adapter.transport = capture
            try:
                output = app.ask(actor, actor.user_id, question, topic=topic, mode=mode, execution_mode='approved_public')
                report['conditions'][label] = result_record(output, output.get('persona_revision'), tools,
                    adapter.budget.calls[adapter.start_attempts:] if adapter.budget else [])
                report['conditions'][label]['persona_source_unchanged'] = app.personas.current(
                    actor, fixed[label]['environment']['project_id']) == snapshots[label][1]
                if not report['conditions'][label]['persona_source_unchanged']:
                    report['status'] = 'blocked_persona_drift'
                    break
            except (RealBlocked, PermissionError, RuntimeError, ValueError) as exc:
                report['conditions'][label].update(status='stopped', exception_type=type(exc).__name__,
                    model_attempts=len(adapter.budget.calls)-adapter.start_attempts if adapter.budget else 0)
                report['status'] = 'stopped'
                break
            finally:
                adapter.transport = original
            if not output['complete'] or not all(not row['error'] for row in output['stages']):
                report['status'] = 'stopped'
                break
        report['wire'] = audit.report()
        report.setdefault('status', 'completed' if all(row['complete'] for row in report['conditions'].values()) and
                          report['wire']['initial_control_passed'] and not report['wire']['has_unexpected_differences'] else 'control_failed')
        report['confounders'] = ['Actual approved Persona version metadata is preserved, not normalized.',
            'Several preference fields may differ together; no individual causal/quality claim.',
            'Downstream evidence, tool IDs and responses may differ because preceding results differ.',
            'Provider snapshot identity and omitted generation defaults remain live GO/NO-GO checks.']
        return copy.deepcopy(report)
