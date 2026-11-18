"""Offline controls and existing budget gates; no remote transport may run."""
import json
import socket

import pytest

from tech_research_agent import controlled_comparison
from tech_research_agent.application import ResearchApplication, principal
from tech_research_agent.real import RealAdapter, RealBlocked
from tech_research_agent.stub_workflow import WorkflowStub


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original = socket.socket.connect
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in {'127.0.0.1', '::1'}:
            pytest.fail('Remote source/model access forbidden')
        return original(sock, address)
    def blocked(*args, **kwargs):
        pytest.fail('Actual OpenAI transport forbidden')
    monkeypatch.setattr(socket.socket, 'connect', connect)
    monkeypatch.setattr(RealAdapter, '_network_send', blocked)


def test_paired_mock_controls_initial_memory_metadata_and_records_each_stage():
    result = controlled_comparison.run()
    assert result['inputs_match'] and result['functional_check']
    assert len(set(result['fixed_input_sha256'].values())) == 1
    before, after = (result['outcomes'][key] for key in ('before', 'after'))
    assert len(before['input']['history']) == 1
    assert before['input']['history'] == after['input']['history']
    assert before['input']['persona_revision'] == after['input']['persona_revision'] == 2
    assert {e['plan']['app'] for e in before['trace']} == {'openalex'}
    assert {e['plan']['app'] for e in after['trace']} == {'kipris_plus'}
    for arm in (before, after):
        assert [s['role'] for s in arm['stages']] == ['research', 'analysis', 'verification']
        assert all(s['raw_answer'] for s in arm['stages'])
        assert arm['evidence'] and arm['report'] and arm['checks']['human_review_required']
        assert all('rp' in e['plan'] and 'op' in e['plan'] and 'result' in e for e in arm['trace'])
    assert result['actual_api_usage'] == {'input_tokens': 0, 'output_tokens': 0, 'estimated_usd': 0}
    assert result['paid_calls'] == result['external_source_calls'] == 0
    assert result['quality_verdict'] == 'not_evaluated' and not result['live_plan']['go']


@pytest.mark.parametrize('name', ['usage.json', 'existing-report.json'])
def test_cli_never_overwrites_existing_ledger_or_report(tmp_path, monkeypatch, name):
    path = tmp_path/name
    path.write_text('preserved bytes')
    monkeypatch.setattr('sys.argv', ['comparison', '--output', str(path)])
    def unexpected():
        pytest.fail('Output must be rejected before running')
    monkeypatch.setattr(controlled_comparison, 'run', unexpected)
    with pytest.raises((SystemExit, FileExistsError)):
        controlled_comparison.main()
    assert path.read_text() == 'preserved bytes'


def test_second_financial_condition_is_blocked_by_existing_eight_call_envelope(tmp_path):
    path = tmp_path/'usage.json'
    path.write_text(json.dumps({'calls': [], 'failed': False}))
    sender = WorkflowStub(direct_financial=True)
    adapter = RealAdapter(path, enabled=True, exclusive_ledger_owner=True, transport=sender)
    app = ResearchApplication(tmp_path/'app', real_adapter=adapter)
    result = app.ask(principal('researcher'), 'researcher', controlled_comparison.QUESTION, execution_mode='real')
    assert result['complete'] and result['model_calls'] == 5
    saved = path.read_bytes()
    with pytest.raises(RealBlocked, match='8-call'):
        adapter.preflight()
    assert path.read_bytes() == saved and len(sender.requests) == 5
