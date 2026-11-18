"""Redacted comparison records. Free text, raw Memory and source bodies are hash-only."""
import re
import json
from pathlib import Path

from persona_prototype.mini_validation import Budget

from .wire_comparison import opaque, safe_key

PARAMETERS = {'query', 'from_date', 'to_date', 'limit', 'sort', 'work_id', 'include_abstract',
              'application_id', 'jurisdiction', 'corp_code', 'bsns_year', 'reprt_code', 'fs_div',
              'receipt_no', 'material_id', 'keyword', 'report_type', 'kind', 'language', 'pages', 'ipc'}


def result_record(result, version, allowed_tools, protocol_calls, *, execution_mode='stub'):
    protocol = Budget(None)
    protocol.calls = protocol_calls
    evidence = [item for item in result.get('evidence', []) if item.get('classification') == 'PUBLIC']
    identifiers = {item['source_id'] for item in evidence}
    selections = []
    for event in result.get('trace', []):
        plan = event['plan']
        tool = plan['app']+'__'+plan['api']
        selections.append({'tool': tool if tool in allowed_tools else opaque(tool),
            'rp': {safe_key(k, PARAMETERS): opaque(v) for k, v in plan['rp'].items()},
            'op': {safe_key(k, PARAMETERS): opaque(v) for k, v in plan['op'].items()},
            'executed': event['executed'], 'retrieval_result': opaque(event['result'])})
    stages = [{'role': stage['role'], 'response': opaque(stage['raw_answer']), 'error': stage['error'],
               'verified_citations': sorted(identifiers & set(re.findall(r'\[([^\[\]\n]+)\]', stage['raw_answer'])))}
              for stage in result.get('stages', [])]
    record = {'persona_version': version, 'stages': stages, 'tool_selections': selections,
            'connector_reported_requests': sum(event.get('result', {}).get('cost', {}).get('source_requests', 0)
                                               for event in result.get('trace', [])),
            'status': 'completed' if result.get('complete') else 'stopped',
            'evidence': [{'document_id': item['source_id'], 'record': opaque(item),
                          'quotations': opaque(item.get('spans', []))} for item in evidence],
            'final_report': opaque(result.get('answer')), 'checks': opaque(result.get('checks')),
            'complete': bool(result.get('complete')), 'model_attempts': result.get('model_calls', 0),
            'actual_api_usage': {'input_tokens': 0, 'output_tokens': 0, 'estimated_usd': 0},
            'stub_protocol_this_condition': protocol.totals(),
            'stub_protocol_campaign_cumulative': result.get('real_audit', {}).get('comparison_totals'),
            'note': 'Protocol accounting/reservations are fabricated Stub values, not paid usage.'}
    if execution_mode == 'live':
        totals = protocol.totals()
        record['actual_api_usage'] = {'input_tokens': totals['reported_input_tokens'], 'output_tokens': totals['reported_output_tokens'],
            'estimated_usd': totals['estimated_usd'], 'usage_complete': totals['usage_complete']}
        record['upstream_dispatches'] = sum(c.get('transport_invoked') is True for c in protocol_calls)
        record['usage_this_condition'] = record.pop('stub_protocol_this_condition')
        record['campaign_cumulative_usage'] = record.pop('stub_protocol_campaign_cumulative')
        record['response_models'] = sorted({row['response_model'] for row in result.get('real_audit', {}).get(
            'public_processing_audit', []) if row.get('status') == 'response_approved'})
        record['note'] = 'Reserved attempts and transport dispatches differ. Missing reported usage remains unknown, never zero-cost.'
    return record


def write_report(report, path):
    """Export only runner-produced redacted records, without replacing an existing artifact or ledger."""
    path = Path(path)
    if path.resolve().name == 'usage.json':
        raise ValueError('A usage ledger is never a report destination')
    with path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def live_summary(report):
    if report['mode'] != 'live':
        return
    report['paid_calls'] = sum(row.get('upstream_dispatches', 0) for row in report['conditions'].values())
    if report['status'] == 'completed':
        identities = [row.get('response_models', []) for row in report['conditions'].values()]
        report['response_identity_consistent'] = len(identities[0]) == 1 and identities[0] == identities[1]
        if not report['response_identity_consistent']:
            report['status'] = 'model_identity_changed'
