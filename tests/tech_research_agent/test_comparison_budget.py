"""Authorized paired allowance on existing ledgers, tested with local Stub transports only."""
import copy
import json
import socket
from dataclasses import asdict

import pytest

from tech_research_agent.application import ResearchApplication, principal
from tech_research_agent.comparison_budget import ComparisonPlan, MAX_REQUEST_RESERVED_USD
from tech_research_agent.comparison_real import ComparisonRealAdapter
from tech_research_agent.real import RealAdapter, RealBlocked
from tech_research_agent.stub_workflow import WorkflowStub

QUESTION = '수소환원제철을 비교 조사해주세요.'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original = socket.socket.connect
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in {'127.0.0.1', '::1'}:
            pytest.fail('Remote API forbidden')
        return original(sock, address)
    def blocked(*args, **kwargs):
        pytest.fail('Actual OpenAI transport forbidden')
    monkeypatch.setattr(socket.socket, 'connect', connect)
    monkeypatch.setattr(RealAdapter, '_network_send', blocked)


def setup(tmp_path):
    old = [{'attempt': i+1, 'status': 200, 'actor': 'old-main',
            'usage': {'prompt_tokens': 100, 'completion_tokens': 10}} for i in range(11)]
    path = tmp_path/'usage.json'
    path.write_text(json.dumps({'calls': old, 'failed': False}))
    return path, ComparisonPlan.capture(path, 'authorized-pair'), old


def adapter(path, plan, condition, sender, **kwargs):
    return ComparisonRealAdapter(path, comparison_plan=plan, condition=condition, transport=sender,
                                 enabled=True, exclusive_ledger_owner=True, **kwargs)


def execute(tmp_path, path, plan, condition, **stub_options):
    sender = WorkflowStub(**stub_options)
    real = adapter(path, plan, condition, sender, max_reserved_usd=1)
    app = ResearchApplication(tmp_path/condition, real_adapter=real)
    return app.ask(principal('researcher'), 'researcher', QUESTION, execution_mode='real'), real, sender


@pytest.mark.parametrize('direct,expected', [(False, 12), (True, 10)])
def test_two_conditions_append_without_reset_and_restart_cannot_regrant(tmp_path, direct, expected):
    path, plan, old = setup(tmp_path)
    plan_snapshot = copy.deepcopy(plan)
    for condition in ('v1', 'v2'):
        result, real, sender = execute(tmp_path, path, plan, condition, direct_financial=direct)
        assert result['complete'] and result['model_calls'] == (5 if direct else 6)
        assert sender.counts == {'research': 2 if direct else 3, 'analysis': 1, 'verification': 2}
        assert all(request['max_tokens'] == 512 and request['model'] == 'gpt-4o-mini' for request in sender.requests)
        before = path.read_bytes()
        with pytest.raises(RealBlocked):
            adapter(path, plan, condition, WorkflowStub(), max_reserved_usd=1).preflight()
        assert path.read_bytes() == before
        with pytest.raises(RealBlocked, match='original pinned plan'):
            ComparisonPlan.capture(path, 'another-id')
        plan = ComparisonPlan(**json.loads(json.dumps(asdict(plan))))  # Reload pinned server configuration.
    saved = json.loads(path.read_text())
    assert saved['calls'][:11] == old and len(saved['calls']) == 11+expected
    assert all(c['comparison_campaign'] == plan.campaign_id for c in saved['calls'][11:])
    assert real.summary()['comparison_totals']['upstream_attempts'] == expected
    assert plan == plan_snapshot and not saved['failed']
    calls = len(real.budget.calls)
    status, _ = real.budget.forward(sender.requests[-1])  # No retry/13th call after a completed condition.
    assert status == 429 and len(real.budget.calls) == calls


@pytest.mark.parametrize('change', ['history', 'foreign', 'pending', 'failed'])
def test_preflight_rejects_changed_or_unreconciled_history_read_only(tmp_path, change):
    path, plan, _ = setup(tmp_path)
    saved = json.loads(path.read_text())
    changes = {
        'history': lambda: saved['calls'][0].update(status=500),
        'foreign': lambda: saved['calls'].append({'status': 200, 'actor': 'another-backend'}),
        'pending': lambda: saved['calls'].append({'status': 'pending'}),
        'failed': lambda: saved.update(failed=True),
    }
    changes[change]()
    path.write_text(json.dumps(saved)); before = path.read_bytes()
    with pytest.raises(RealBlocked):
        adapter(path, plan, 'v1', WorkflowStub(), max_reserved_usd=1).preflight()
    assert path.read_bytes() == before


@pytest.mark.parametrize('ceiling', [0, 6*MAX_REQUEST_RESERVED_USD])
def test_no_pair_starts_with_zero_or_only_single_condition_cost_budget(tmp_path, ceiling):
    path, plan, _ = setup(tmp_path); before = path.read_bytes()
    with pytest.raises(RealBlocked):
        adapter(path, plan, 'v1', WorkflowStub(), max_reserved_usd=ceiling).preflight()
    assert path.read_bytes() == before


def test_call_approval_is_not_actual_network_execution_approval(tmp_path):
    path, plan, _ = setup(tmp_path); before = path.read_bytes()
    with pytest.raises(RealBlocked, match='actual API execution approval'):
        adapter(path, plan, 'v1', None, max_reserved_usd=1).preflight()
    assert path.read_bytes() == before


def test_pending_attempt_is_durable_and_first_error_stops_campaign(tmp_path):
    path, plan, old = setup(tmp_path)
    sent = []
    def fail(body):
        saved = json.loads(path.read_text())
        assert saved['calls'][:11] == old
        pending = saved['calls'][-1]
        assert pending['status'] == 'pending' and pending['comparison_condition'] == 'v1'
        assert pending['actor'] == plan.case('v1')+':research' and pending['reserved_usd_upper_bound'] > 0
        sent.append(body)
        return 503, {}
    real = adapter(path, plan, 'v1', fail, max_reserved_usd=1)
    result = ResearchApplication(tmp_path/'app', real_adapter=real).ask(
        principal('researcher'), 'researcher', QUESTION, execution_mode='real')
    assert not result['complete'] and len(sent) == 1
    saved = path.read_bytes()
    with pytest.raises(RealBlocked):
        adapter(path, plan, 'v2', WorkflowStub(), max_reserved_usd=1).preflight()
    assert path.read_bytes() == saved


@pytest.mark.parametrize('role,cap', [('research', 3), ('analysis', 2), ('verification', 2)])
def test_specialist_limits_block_before_transport_and_survive_reload(tmp_path, role, cap):
    from tech_research_agent.comparison_budget import ComparisonBudget
    path, plan, old = setup(tmp_path)
    sent = []
    def send(body):
        sent.append(body)
        return 200, {'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
    budget = ComparisonBudget(send, path, plan, 'v1', 1)
    budget.case = plan.case('v1')
    budget.payload_hash = 'stub-policy-approved-payload'
    body = {'messages': [{'role': 'user', 'content': '[PERSONA_ROLE='+role+']\nPUBLIC SYNTHETIC'}]}
    for _ in range(cap):
        assert budget.forward(body)[0] == 200
    budget = ComparisonBudget(send, path, plan, 'v1', 1)
    budget.case = plan.case('v1')
    budget.payload_hash = 'stub-policy-approved-payload'
    assert budget.forward(body)[0] == 429 and len(sent) == cap
    assert json.loads(path.read_text())['calls'][:11] == old


def test_uncoordinated_ledger_writer_is_not_overwritten(tmp_path):
    from tech_research_agent.comparison_budget import ComparisonBudget
    path, plan, _ = setup(tmp_path)
    budget = ComparisonBudget(lambda body: pytest.fail('Must not send'), path, plan, 'v1', 1)
    budget.case = plan.case('v1')
    changed = json.loads(path.read_text())
    changed['calls'][0]['usage']['prompt_tokens'] = 999
    path.write_text(json.dumps(changed)); before = path.read_bytes()
    body = {'messages': [{'role': 'user', 'content': '[PERSONA_ROLE=research]\nPUBLIC SYNTHETIC'}]}
    assert budget.forward(body)[0] == 429
    assert path.read_bytes() == before
