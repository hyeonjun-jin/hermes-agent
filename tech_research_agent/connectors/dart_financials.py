"""Exact-ID account mapping; never infer technology profitability or fiscal dates."""
import json
import re
from .dart_records import base_item, receipt_date, result

ACCOUNTS = {
    'operating_profit': {'dart_OperatingIncomeLoss': {'IS', 'CIS'}},
    'cash_flow_investing': {'ifrs-full_CashFlowsFromUsedInInvestingActivities': {'CF'},
                            'ifrs_CashFlowsFromUsedInInvestingActivities': {'CF'}},
}


def amount(value):
    if value in (None, '', '-'):
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?', value):
        raise ValueError('invalid_amount')
    return value.replace(',', '')


def normalize_row(raw, params, cutoff):
    for key in ('corp_code', 'bsns_year', 'reprt_code'):
        if raw[key] != params[key]:
            raise ValueError('financial_identity_or_period_mismatch')
    if raw.get('fs_div', params['fs_div']) != params['fs_div']:
        raise ValueError('financial_basis_mismatch')
    if receipt_date(raw['rcept_no']) > cutoff:
        raise ValueError('future_filing')
    canonical = next((name for name, ids in ACCOUNTS.items()
                      if raw['account_id'] in ids and raw['sj_div'] in ids[raw['account_id']]), None)
    if canonical is None or canonical not in params.get('account_ids', ACCOUNTS):
        return None
    if not isinstance(raw.get('currency'), str) or not raw['currency'].strip():
        raise ValueError('currency_missing')
    return {'account_id': canonical, 'official_account_id': raw['account_id'],
            'account_name': raw.get('account_nm'), 'statement': raw['sj_div'],
            'receipt_no': raw['rcept_no'], 'corp_code': raw['corp_code'],
            'bsns_year': raw['bsns_year'], 'reprt_code': raw['reprt_code'], 'fs_div': params['fs_div'],
            'period_name': raw.get('thstrm_nm'), 'period_label_raw': raw.get('thstrm_dt'), 'period_start': None,
            'period_end': None, 'period_dates_verified': False,
            'amount_raw': raw.get('thstrm_amount'), 'amount': amount(raw.get('thstrm_amount')),
            'cumulative_amount_raw': raw.get('thstrm_add_amount'), 'cumulative_amount': amount(raw.get('thstrm_add_amount')),
            'current_amount_scope': 'three_months' if params['reprt_code'] != '11011' and raw['sj_div'] in {'IS', 'CIS'} else 'as_reported',
            'currency': raw['currency'], 'unit': raw['currency'], 'scaling_applied': False,
            'previous_period_name': raw.get('frmtrm_nm'), 'previous_amount_raw': raw.get('frmtrm_amount'),
            'previous_cumulative_amount_raw': raw.get('frmtrm_add_amount'),
            'scope': 'company_consolidated' if params['fs_div'] == 'CFS' else 'company_standalone',
            'technology_profitability': 'not_established', 'source_row': raw}


def financial_result(raw_rows, params, cutoff, company, now, url):
    if not raw_rows:
        return result('empty', warnings=['financial_data_not_returned'])
    rows, warnings = [], []
    for raw in raw_rows:
        try:
            row = normalize_row(raw, params, cutoff)
            if row:
                rows.append(row)
        except (KeyError, TypeError, ValueError, AttributeError):
            warnings.append('unusable_financial_row')
    requested = set(params.get('account_ids', ACCOUNTS))
    if requested - {row['account_id'] for row in rows}:
        warnings.append('requested_accounts_incomplete')
    if any(row['amount'] is None for row in rows):
        warnings.append('amount_unavailable')
    # Repeated IS/CIS and amended filings remain separate; never choose or sum silently.
    if len(rows) != len({(row['receipt_no'], row['account_id']) for row in rows}):
        warnings.append('ambiguous_account_rows')
    if len({row['receipt_no'] for row in rows}) > 1:
        warnings.append('multiple_financial_filings')
    items = []
    for receipt in sorted({row['receipt_no'] for row in rows}):
        item = base_item(receipt, company, params['corp_code'], now, url)
        selected = [row for row in rows if row['receipt_no'] == receipt]
        item.update(source_id='dart-fin:'+':'.join([params['corp_code'], params['bsns_year'], params['reprt_code'], params['fs_div'], receipt, ','.join(sorted({row['account_id'] for row in selected}))]),
                    title=company['name']+' 재무 '+params['bsns_year']+' '+params['reprt_code']+' '+params['fs_div'],
                    rows=selected, financial_request={k: params[k] for k in ('corp_code', 'bsns_year', 'reprt_code', 'fs_div')},
                    evidence_coverage='financial_rows', original_verified=not warnings,
                    spans=[{'id': 'financial-row-'+str(i), 'kind': 'financial_row', 'text': json.dumps(row, ensure_ascii=False, sort_keys=True)}
                           for i, row in enumerate(selected)])
        items.append(item)
    return result('partial' if warnings else 'ok' if items else 'empty', items=items, rows=rows, warnings=warnings)
