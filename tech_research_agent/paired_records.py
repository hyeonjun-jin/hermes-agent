"""Redacted comparison records. Free text, raw Memory and source bodies are hash-only."""
import re
import json
from pathlib import Path

from persona_prototype.mini_validation import Budget

from .wire_comparison import opaque, safe_key

PARAMETERS = {'query', 'from_date', 'to_date', 'limit', 'sort', 'work_id', 'include_abstract',
              'application_id', 'jurisdiction', 'corp_code', 'bsns_year', 'reprt_code', 'fs_div',
              'receipt_no', 'material_id', 'keyword', 'report_type', 'kind', 'language', 'pages', 'ipc'}


def result_record(result, version, allowed_tools, protocol_calls):
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
    return {'persona_version': version, 'stages': stages, 'tool_selections': selections,
            'status': 'completed' if result.get('complete') else 'stopped',
            'evidence': [{'document_id': item['source_id'], 'record': opaque(item),
                          'quotations': opaque(item.get('spans', []))} for item in evidence],
            'final_report': opaque(result.get('answer')), 'checks': opaque(result.get('checks')),
            'complete': bool(result.get('complete')), 'model_attempts': result.get('model_calls', 0),
            'actual_api_usage': {'input_tokens': 0, 'output_tokens': 0, 'estimated_usd': 0},
            'stub_protocol_this_condition': protocol.totals(),
            'stub_protocol_campaign_cumulative': result.get('real_audit', {}).get('comparison_totals'),
            'note': 'Protocol accounting/reservations are fabricated Stub values, not paid usage.'}


def write_report(report, path):
    """Export only runner-produced redacted records, without replacing an existing artifact or ledger."""
    path = Path(path)
    if path.resolve().name == 'usage.json':
        raise ValueError('A usage ledger is never a report destination')
    with path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
