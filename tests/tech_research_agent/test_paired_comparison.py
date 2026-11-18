"""Different approved-shaped Personas through the actual public gateway, entirely offline."""
import json
import socket

import pytest

from tech_research_agent.application import principal
from tech_research_agent.paired_comparison import PairedPublicComparison
from tech_research_agent.real import RealAdapter, RealBlocked
from tech_research_agent.wire_comparison import WireComparison
from tech_research_agent.paired_records import write_report
from tests.tech_research_agent.paired_fixtures import PairFixture, PRIVATE, QUESTION


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original = socket.socket.connect
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in {'127.0.0.1', '::1'}:
            pytest.fail('External source/model network forbidden')
        return original(sock, address)
    def blocked(*args, **kwargs):
        pytest.fail('Actual OpenAI transport forbidden')
    monkeypatch.setattr(socket.socket, 'connect', connect)
    monkeypatch.setattr(RealAdapter, '_network_send', blocked)


def test_disabled_by_default_never_prepares_state_or_approvals():
    def forbidden(root):
        pytest.fail('Disabled runner must not touch state')
    report = PairedPublicComparison(forbidden).run(principal('researcher'), QUESTION)
    assert report['status'] == 'disabled' and report['paid_calls'] == 0


def test_different_personas_keep_fixed_inputs_and_explain_all_wire_differences():
    fixture = PairFixture()
    report = PairedPublicComparison(fixture).run(principal('researcher'), QUESTION, enabled=True)
    assert report['status'] == 'completed', report
    assert report['fixed_inputs']['v1'] == report['fixed_inputs']['v2']
    assert report['source_personas']['v1']['version'] == 2
    assert report['source_personas']['v2']['version'] == 3
    wire = report['wire']
    assert wire['initial_control_passed'] and not wire['has_unexpected_differences']
    assert len(wire['records']['v1']) == len(wire['records']['v2']) == 6
    initial = next(row for row in wire['comparisons'] if row['initial_request'])
    assert {d['classification'] for d in initial['differences']} == {'persona_preferences', 'persona_version_metadata'}
    assert any(d['classification'] == 'downstream_results' for row in wire['comparisons'][1:] for d in row['differences'])
    assert not wire['unmatched_requests']
    for condition, document in (('v1', 'W123'), ('v2', 'W456')):
        arm = report['conditions'][condition]
        assert arm['complete'] and arm['model_attempts'] == 6
        assert arm['persona_source_unchanged']
        assert [row['role'] for row in arm['stages']] == ['research', 'analysis', 'verification']
        assert [row['document_id'] for row in arm['evidence']] == [document]
        assert arm['actual_api_usage'] == {'input_tokens': 0, 'output_tokens': 0, 'estimated_usd': 0}
        assert arm['stub_protocol_this_condition']['upstream_attempts'] == 6
        assert arm['stub_protocol_this_condition']['reported_input_tokens'] == 60
        assert arm['stub_protocol_this_condition']['reported_output_tokens'] == 30
        assert fixture.senders[condition].counts == {'research': 3, 'analysis': 1, 'verification': 2}
        actual_wire = json.dumps(fixture.senders[condition].requests)
        assert PRIVATE not in actual_wire and 'financial_detail' not in actual_wire
    text = json.dumps(report)
    assert PRIVATE not in text and 'STUB_RAW_RESPONSE_ONLY' not in text
    assert 'fixed-initial-session' not in text and 'FABRICATED 수소환원제철' not in text
    assert report['paid_calls'] == report['external_source_calls'] == 0
    assert report['live_execution_approved'] is False and not report['actual_execution_go']


def test_initial_memory_mismatch_blocks_both_conditions_without_model_requests():
    def mutate(apps):
        actor = principal('researcher')
        apps['v2'].store.append(actor, actor.user_id, 'different', '[project=proj-H] '+QUESTION, PRIVATE)
    fixture = PairFixture(mutate=mutate)
    report = PairedPublicComparison(fixture).run(principal('researcher'), QUESTION, enabled=True)
    assert report['status'] == 'blocked_initial_inputs'
    assert all(not sender.requests for sender in fixture.senders.values())
    assert PRIVATE not in json.dumps(report)


def test_missing_projection_does_not_automatically_approve_or_publish_private_persona():
    fixture = PairFixture(omit_projection=True)
    report = PairedPublicComparison(fixture).run(principal('researcher'), QUESTION, enabled=True)
    assert report['status'] == 'stopped' and not report['conditions']['v1']['complete']
    assert all(not sender.requests for sender in fixture.senders.values())
    assert PRIVATE not in json.dumps(report)


@pytest.mark.parametrize('kind', ['legacy', 'history'])
def test_private_or_changed_memory_is_not_automatically_reapproved(kind):
    def mutate(apps):
        for app in apps.values():
            if kind == 'legacy':
                app.store.save_semantic(principal('researcher'), 'researcher',
                    {'explicitly_approved': True, 'source_focus': 'science', 'data_policy': 'PRIVATE', 'comment': PRIVATE})
            else:
                with app.store.connect() as db:
                    db.execute('UPDATE episodes SET response=?', (PRIVATE,))
    fixture = PairFixture(mutate=mutate)
    report = PairedPublicComparison(fixture).run(principal('researcher'), QUESTION, enabled=True)
    assert report['status'] == 'stopped'
    assert all(not sender.requests for sender in fixture.senders.values())
    assert PRIVATE not in json.dumps(report)


@pytest.mark.parametrize('model', ['gpt-4o-mini-2024-07-18', 'gpt-4o-mini-unreviewed', 'gpt-4o'])
def test_unconfirmed_response_identifiers_remain_blocked_without_prefix_allowance(model):
    fixture = PairFixture(response_model=model)
    report = PairedPublicComparison(fixture).run(principal('researcher'), QUESTION, enabled=True)
    assert report['status'] == 'stopped' and not report['conditions']['v1']['complete']
    assert len(fixture.senders['v1'].requests) == 1 and not fixture.senders['v2'].requests
    assert report['paid_calls'] == 0


def body(preference, version):
    context = {'role': 'research', 'profile': {'job': 'fixture'}, 'environment': {'depth': 'quick'},
               'history': [], 'persona_revision': version, 'approved_preferences': {'research_persona': {
                   'version': version, 'preferences': {'result_limit': preference}}},
               'persona_guidance': {'preferences': {'result_limit': preference}, 'priority': ['server_policy']}}
    return {'model': 'gpt-4o-mini', 'max_tokens': 512, 'tools': [], 'messages': [
        {'role': 'system', 'content': 'Fixed instructions TECH_CONTEXT='+json.dumps(context)},
        {'role': 'user', 'content': '[PERSONA_ROLE=research]\nfixed'}]}


@pytest.mark.parametrize('component', ['generation', 'schema', 'system', 'environment'])
def test_full_wire_catches_nonpersona_changes_and_exports_no_raw_payload(component):
    a, b = body(3, 2), body(2, 3)
    def environment():
        ctx = json.loads(b['messages'][0]['content'].split('TECH_CONTEXT=', 1)[1])
        ctx['environment']['depth'] = PRIVATE
        b['messages'][0]['content'] = 'Fixed instructions TECH_CONTEXT='+json.dumps(ctx)
    changes = {'generation': lambda: b.update(temperature=0.5), 'schema': lambda: b.update(tools=[{'description': PRIVATE}]),
               'system': lambda: b['messages'][0].update(content=PRIVATE+' '+b['messages'][0]['content']),
               'environment': environment}
    changes[component]()
    audit = WireComparison(); audit.capture('v1', a)
    with pytest.raises(RealBlocked):
        audit.capture('v2', b)
    report = audit.report()
    assert not report['initial_control_passed'] and report['has_unexpected_differences']
    assert PRIVATE not in json.dumps(report)
    assert any(c['classification'] == 'unexpected_control_difference' for c in report['comparisons'][0]['differences'])


def test_identical_exported_preferences_are_rejected_even_if_versions_differ():
    audit = WireComparison(); audit.capture('v1', body(3, 2))
    with pytest.raises(RealBlocked):
        audit.capture('v2', body(3, 3))
    assert not audit.report()['initial_control_passed']


def test_fixed_context_key_order_is_not_silently_masked():
    a, b = body(3, 2), body(2, 3)
    prefix, text = b['messages'][0]['content'].split('TECH_CONTEXT=', 1)
    context = json.loads(text)
    context = dict(reversed(list(context.items())))
    b['messages'][0]['content'] = prefix+'TECH_CONTEXT='+json.dumps(context)
    audit = WireComparison(); audit.capture('v1', a)
    with pytest.raises(RealBlocked):
        audit.capture('v2', b)
    assert any(row['component'] == 'context.field_order' for row in audit.report()['comparisons'][0]['differences'])


def test_report_export_never_overwrites_usage_or_existing_files(tmp_path):
    report = {'mode': 'stub', 'paid_calls': 0}
    path = tmp_path/'report.json'
    write_report(report, path)
    assert json.loads(path.read_text()) == report
    with pytest.raises(FileExistsError):
        write_report(report, path)
    with pytest.raises(ValueError):
        write_report(report, tmp_path/'usage.json')


def test_other_user_cannot_reuse_researcher_personas_or_memories():
    fixture = PairFixture()
    report = PairedPublicComparison(fixture).run(principal('finance'), QUESTION, enabled=True)
    assert report['status'] == 'blocked_identical_personas'
    assert all(not sender.requests for sender in fixture.senders.values())


@pytest.mark.parametrize('setting', ['live', 'network_model', 'outside_ledger', 'network_source'])
def test_stub_rehearsal_cannot_activate_live_or_operating_resources(tmp_path, setting):
    from tech_research_agent.connectors.openalex import OpenAlexConnector
    outside = tmp_path/'usage.json'; outside.write_text('operating bytes must remain unchanged')
    def mutate(apps):
        adapter = apps['v1'].public_real_adapter
        def replace_source():
            apps['v1'].source_connectors['openalex'].close()
            apps['v1'].source_connectors['openalex'] = OpenAlexConnector(enabled=True)
        changes = {'live': lambda: setattr(adapter, 'live_execution_approved', True),
                   'network_model': lambda: setattr(adapter, 'transport', None),
                   'outside_ledger': lambda: setattr(adapter, 'path', outside.resolve()), 'network_source': replace_source}
        changes[setting]()
    fixture = PairFixture(mutate=mutate)
    with pytest.raises(RealBlocked):
        PairedPublicComparison(fixture).run(principal('researcher'), QUESTION, enabled=True)
    assert all(not sender.requests for sender in fixture.senders.values())
    assert outside.read_text() == 'operating bytes must remain unchanged'
