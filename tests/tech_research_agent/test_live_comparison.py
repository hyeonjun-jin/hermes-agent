"""Live branch exercised through a patched network method. Real network and operating data forbidden."""
import copy
import json
import socket
from dataclasses import asdict
from datetime import timedelta

import pytest

from tech_research_agent.application import principal
from tech_research_agent.approvals import digest
from tech_research_agent.comparison_budget import ComparisonPlan
from tech_research_agent.comparison_real import ComparisonPublicAdapter
from tech_research_agent.live_execution import LiveExecutionApproval
from tech_research_agent.paired_comparison import PairedPublicComparison, input_snapshot
from tech_research_agent.real import RealAdapter, RealBlocked
from tech_research_agent.response_models import ResponseModels
from tests.tech_research_agent.paired_fixtures import PairFixture, PreferenceStub, NOW, QUESTION, PRIVATE

DATED = 'gpt-4o-mini-2024-07-18'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original = socket.socket.connect
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in {'127.0.0.1', '::1'}:
            pytest.fail('External API forbidden')
        return original(sock, address)
    def forbidden(*a, **kw):
        pytest.fail('Actual network sender must be patched before enabling the simulated live branch')
    monkeypatch.setattr(socket.socket, 'connect', connect)
    monkeypatch.setattr(RealAdapter, '_network_send', forbidden)
    monkeypatch.setattr('tech_research_agent.real.check_real_network', lambda env: 'offline-test-policy')
    monkeypatch.setenv('PERSONA_API_KEY', 'fabricated-test-credential-not-valid')
    monkeypatch.setenv('PERSONA_MODEL', 'gpt-4o-mini')
    monkeypatch.setenv('PERSONA_BASE_URL', 'https://api.openai.com/v1')


class LiveHarness:
    def __init__(self, root, *, models=('gpt-4o-mini',), response_model='gpt-4o-mini', omit_projection=False, state_mutation=None):
        self.root, self.now, self.response_model = root, NOW, response_model
        self.mutate = None
        self.senders = {}
        self.factory_calls = 0
        self.preparer = PairFixture(omit_projection=omit_projection, mutate=state_mutation)
        self.path = root/'usage.json'
        self.old = [{'status': 200, 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}} for _ in range(11)]
        self.path.write_text(json.dumps({'calls': self.old, 'failed': False}))
        self.plan = ComparisonPlan.capture(self.path, 'fabricated-live-test')
        reference = root/'reference'; reference.mkdir()
        apps = self.preparer(reference)
        snapshots = {label: input_snapshot(app, principal('researcher'), 'H', 'quick', QUESTION) for label, app in apps.items()}
        self.record = {'approval_id': 'FABRICATED-NO-LIVE-AUTHORIZATION', 'approved_by': 'test-only operator',
            'actual_execution_approved': True, 'model': 'gpt-4o-mini', 'endpoint': 'https://api.openai.com/v1',
            'max_new_calls': 12, 'max_reserved_usd': 1, 'approved_at': '2026-11-16T00:00:00+00:00',
            'expires_at': '2026-12-01T00:00:00+00:00', 'user_id': 'researcher', 'project_id': 'proj-H',
            'question_sha256': digest(QUESTION), 'comparison_plan': asdict(self.plan),
            'initial_inputs_sha256': digest(snapshots['v1'][0]),
            'personas_sha256': {label: digest(value[1]) for label, value in snapshots.items()},
            'response_model_ids': list(models), 'response_model_evidence_sha256': digest('FABRICATED evidence, not a verified provider response')}
        self.record['wire_options_sha256'] = dict.fromkeys(('research', 'analysis', 'verification'),
            digest({'model': 'gpt-4o-mini', 'max_tokens': 512, 'stream': False}))
        for app in apps.values():
            for connector in app.source_connectors.values(): connector.close()
        self.approval = LiveExecutionApproval(self.record, clock=lambda: self.now)

    def factory(self, root):
        self.factory_calls += 1
        apps = self.preparer(root)
        for label, app in apps.items():
            sender = PreferenceStub(self.response_model); self.senders[label] = sender
            app.public_real_adapter = ComparisonPublicAdapter(self.path, comparison_plan=self.plan, condition=label,
                approvals=app.public_real_adapter.approvals, public_processing_enabled=True,
                enabled=True, exclusive_ledger_owner=True, max_reserved_usd=1, transport=None,
                live_execution_approved=True, response_models=self.approval.response_models)
        if self.mutate: self.mutate(apps)
        return apps

    def patch_sender(self, monkeypatch, callback=None):
        def send(adapter, body):
            assert adapter.transport is None  # Observer must never turn the live path into an injected transport.
            if callback: callback(adapter, body)
            return self.senders[adapter.condition](body)
        monkeypatch.setattr(RealAdapter, '_network_send', send)

    def run(self, **kwargs):
        return PairedPublicComparison(self.factory, execution_approval=self.approval).run(
            principal('researcher'), QUESTION, enabled=True, execution_mode='live', live_enabled=True, **kwargs)


@pytest.mark.parametrize('models,response', [(('gpt-4o-mini',), 'gpt-4o-mini'),
    (('gpt-4o-mini', DATED), DATED)])
def test_live_branch_uses_network_method_but_tests_never_contact_network(tmp_path, monkeypatch, models, response):
    h = LiveHarness(tmp_path, models=models, response_model=response); h.patch_sender(monkeypatch)
    report = h.run()
    assert report['status'] == 'completed', report
    assert report['response_identity_consistent']
    assert report['wire']['initial_control_passed'] and not report['wire']['has_unexpected_differences']
    assert report['paid_calls'] == 12
    for arm in report['conditions'].values():
        assert arm['upstream_dispatches'] == arm['model_attempts'] == 6
        assert arm['actual_api_usage']['input_tokens'] == 60 and arm['actual_api_usage']['output_tokens'] == 30
        assert arm['actual_api_usage']['estimated_usd'] == pytest.approx(0.000027)
        assert arm['response_models'] == [response] and 'stub_protocol_this_condition' not in arm
    saved = json.loads(h.path.read_text())
    assert saved['calls'][:11] == h.old and len(saved['calls']) == 23
    assert all(c['transport_invoked'] for c in saved['calls'][11:])
    assert PRIVATE not in json.dumps(report)


def test_no_approval_or_live_enablement_never_calls_factory():
    def forbidden(root): pytest.fail('Must fail before preparing state')
    runner = PairedPublicComparison(forbidden)
    assert runner.run(principal('researcher'), QUESTION, execution_mode='live')['status'] == 'disabled'
    assert runner.run(principal('researcher'), QUESTION, enabled='false', execution_mode='live', live_enabled=True)['status'] == 'disabled'
    with pytest.raises(RealBlocked):
        runner.run(principal('researcher'), QUESTION, enabled=True, execution_mode='live', live_enabled=True)


@pytest.mark.parametrize('change', ['user', 'question', 'expiry', 'inputs', 'persona', 'plan', 'cost', 'flag'])
def test_scope_bindings_and_activation_are_not_inferred(tmp_path, monkeypatch, change):
    h = LiveHarness(tmp_path); h.patch_sender(monkeypatch)
    record = copy.deepcopy(h.record)
    updates = {
        'user': lambda: record.update(user_id='finance'), 'question': lambda: record.update(question_sha256=digest('other')),
        'expiry': lambda: record.update(expires_at='2026-11-17T00:00:00+00:00'),
        'inputs': lambda: record.update(initial_inputs_sha256='0'*64),
        'persona': lambda: record['personas_sha256'].update(v2='0'*64),
        'plan': lambda: record['comparison_plan'].update(campaign_id='unapproved'),
        'cost': lambda: record.update(max_reserved_usd=0.05),
        'flag': lambda: record.update(actual_execution_approved=False)}
    updates[change]()
    before = h.path.read_bytes()
    with pytest.raises((RealBlocked, ValueError)):
        h.approval = LiveExecutionApproval(record, clock=lambda: h.now)
        h.run()
    assert h.path.read_bytes() == before and all(not s.requests for s in h.senders.values())


def test_unreviewed_snapshot_response_stops_pair_without_retry(tmp_path, monkeypatch):
    h = LiveHarness(tmp_path, response_model=DATED); h.patch_sender(monkeypatch)
    report = h.run()
    assert report['status'] == 'stopped' and report['paid_calls'] == 1
    assert report['conditions']['v1']['actual_api_usage']['estimated_usd'] == pytest.approx(0.0000045)
    assert not h.senders['v2'].requests and len(h.senders['v1'].requests) == 1


def test_revoked_execution_approval_blocks_after_reservation_before_next_dispatch(tmp_path, monkeypatch):
    h = LiveHarness(tmp_path)
    h.patch_sender(monkeypatch, lambda a, b: h.approval.revoke())
    report = h.run()
    assert report['status'] == 'stopped' and report['paid_calls'] == 1
    arm = report['conditions']['v1']
    assert arm['model_attempts'] == 2 and arm['upstream_dispatches'] == 1
    assert arm['actual_api_usage']['estimated_usd'] is None
    assert not h.senders['v2'].requests


def test_execution_approval_cannot_replace_persona_export_approval(tmp_path, monkeypatch):
    h = LiveHarness(tmp_path, omit_projection=True); h.patch_sender(monkeypatch)
    before = h.path.read_bytes(); report = h.run()
    assert report['status'] == 'stopped' and report['paid_calls'] == 0
    assert h.path.read_bytes() == before and all(not s.requests for s in h.senders.values())


@pytest.mark.parametrize('identifier', ['gpt-4o-mini-*', 'gpt-4o-mini-unverified', 'gpt-4o-mini-2026-02-30', 'gpt-4o'])
def test_response_model_allowlist_never_uses_prefix_or_invalid_date(identifier):
    with pytest.raises(ValueError):
        ResponseModels((identifier,), 'test operator', '0'*64)


def test_observer_cannot_mutate_final_payload_after_approval(tmp_path, monkeypatch):
    h = LiveHarness(tmp_path); h.patch_sender(monkeypatch)
    def mutate(apps):
        def observer(body): body['model'] = 'unapproved-model'
        for app in apps.values(): app.public_real_adapter.request_observer = observer
    h.mutate = mutate
    assert h.run()['status'] == 'completed'
    assert all(body['model'] == 'gpt-4o-mini' for sender in h.senders.values() for body in sender.requests)


def test_unapproved_generation_options_block_before_dispatch(tmp_path, monkeypatch):
    h = LiveHarness(tmp_path); h.patch_sender(monkeypatch)
    h.record['wire_options_sha256']['research'] = digest({'model': 'other'})
    h.approval = LiveExecutionApproval(h.record, clock=lambda: h.now)
    report = h.run()
    assert report['status'] == 'stopped' and report['paid_calls'] == 0
    assert all(not sender.requests for sender in h.senders.values())


@pytest.mark.parametrize('variable,value', [('PERSONA_MODEL', 'other'), ('PERSONA_BASE_URL', 'https://other.invalid/v1'), ('PERSONA_API_KEY', '')])
def test_live_environment_must_match_before_factory_or_ledger_access(tmp_path, monkeypatch, variable, value):
    h = LiveHarness(tmp_path); before = h.path.read_bytes()
    monkeypatch.setenv(variable, value)
    with pytest.raises((RealBlocked, ValueError)):
        h.run()
    assert not h.factory_calls and h.path.read_bytes() == before


@pytest.mark.parametrize('kind', ['document', 'history'])
def test_execution_grant_does_not_authorize_unapproved_document_or_memory(tmp_path, monkeypatch, kind):
    from tech_research_agent.approvals import ApprovalRegistry
    def mutate(apps):
        for app in apps.values():
            if kind == 'document':
                app.public_real_adapter.approvals = ApprovalRegistry([])
            else:
                with app.store.connect() as db:
                    db.execute('UPDATE episodes SET response=?', (PRIVATE,))
    h = LiveHarness(tmp_path, state_mutation=mutate); h.patch_sender(monkeypatch)
    before = h.path.read_bytes(); report = h.run()
    assert report['status'] == 'stopped' and report['paid_calls'] == 0
    assert h.path.read_bytes() == before and all(not s.requests for s in h.senders.values())
    assert PRIVATE not in json.dumps(report)


def test_live_flag_and_reviewed_response_configuration_are_not_auto_applied(tmp_path, monkeypatch):
    h = LiveHarness(tmp_path, models=('gpt-4o-mini', DATED)); h.patch_sender(monkeypatch)
    def mutate(apps):
        apps['v1'].public_real_adapter.response_models = None
    h.mutate = mutate; before = h.path.read_bytes()
    with pytest.raises(RealBlocked): h.run()
    assert h.path.read_bytes() == before


def test_observer_revocation_stops_before_dispatch(tmp_path, monkeypatch):
    h = LiveHarness(tmp_path); h.patch_sender(monkeypatch)
    def mutate(apps):
        for app in apps.values():
            app.public_real_adapter.request_observer = lambda body: h.approval.revoke()
    h.mutate = mutate
    report = h.run()
    assert report['status'] == 'stopped' and report['paid_calls'] == 0
    assert report['conditions']['v1']['model_attempts'] == 1
    assert all(not sender.requests for sender in h.senders.values())


@pytest.mark.parametrize('usage', [None, {'prompt_tokens': 'bad', 'completion_tokens': 5}])
def test_live_missing_or_malformed_usage_stops_without_zero_cost_claim(tmp_path, monkeypatch, usage):
    h = LiveHarness(tmp_path)
    def send(adapter, body):
        status, payload = h.senders[adapter.condition](body)
        payload['usage'] = usage
        return status, payload
    monkeypatch.setattr(RealAdapter, '_network_send', send)
    report = h.run()
    assert report['status'] == 'stopped' and report['paid_calls'] == 1
    assert report['conditions']['v1']['actual_api_usage']['estimated_usd'] is None
    assert len(h.senders['v1'].requests) == 1 and not h.senders['v2'].requests


def test_second_condition_access_revocation_preserves_first_condition_accounting(tmp_path, monkeypatch):
    h = LiveHarness(tmp_path)
    prepared = {}
    h.mutate = lambda apps: prepared.update(apps)
    def revoke(adapter, body):
        if adapter.condition == 'v1' and adapter.role == 'verification' and h.senders['v1'].counts['verification'] == 1:
            prepared['v2'].personas.project_access = lambda *args: False
    h.patch_sender(monkeypatch, revoke)
    report = h.run()
    assert report['status'] == 'stopped' and report['paid_calls'] == 6
    assert report['conditions']['v1']['complete']
    assert report['conditions']['v2']['exception_type'] == 'PermissionError'
    assert not h.senders['v2'].requests


def test_different_reviewed_identities_between_conditions_are_reported_as_confounder(tmp_path, monkeypatch):
    h = LiveHarness(tmp_path, models=('gpt-4o-mini', DATED)); h.patch_sender(monkeypatch)
    h.mutate = lambda apps: setattr(h.senders['v2'], 'response_model', DATED)
    report = h.run()
    assert report['status'] == 'model_identity_changed' and report['paid_calls'] == 12
    assert not report['response_identity_consistent']


def test_model_identity_change_inside_condition_stops_immediately(tmp_path, monkeypatch):
    h = LiveHarness(tmp_path, models=('gpt-4o-mini', DATED))
    def change(adapter, body):
        if h.senders['v1'].requests:
            h.senders['v1'].response_model = DATED
    h.patch_sender(monkeypatch, change)
    report = h.run()
    assert report['status'] == 'stopped' and report['paid_calls'] == 2
    assert not h.senders['v2'].requests
