"""OpenDART provenance and status normalization. No upstream error bodies in audit."""
from datetime import datetime
import re

AUTH_ERRORS = {'010', '011', '012', '101', '901'}


def receipt_date(receipt):
    if not isinstance(receipt, str) or not re.fullmatch(r'[0-9]{14}', receipt):
        raise ValueError('invalid_receipt')
    return datetime.strptime(receipt[:8], '%Y%m%d').date().isoformat()


def result(status, *, items=(), rows=(), warnings=(), reason=None, attempted=True):
    return {'status': status, 'items': list(items), 'rows': list(rows), 'warnings': list(warnings),
            'reason': reason, 'next_cursor': None,
            'cost': {'mock_units': 0, 'source_requests': int(attempted), 'usd': None,
                     'billing_verified': False, 'quota_units': None, 'quota_verified': False}}


def api_error(code, *, search=False):
    if not isinstance(code, str) or not re.fullmatch(r'[0-9]{3}', code):
        return result('unavailable', reason='invalid_source_status')
    if code == '000':
        return None
    status = 'denied' if code in AUTH_ERRORS else 'empty' if search and code == '013' else 'unavailable'
    reason = 'source_quota_exceeded' if code == '020' else 'source_status_'+str(code)
    return result(status, reason=reason)


def base_item(receipt, company, code, now, request_url):
    return {'source_id': receipt, 'receipt_no': receipt, 'corp_code': code,
            'company': company['name'], 'title': '', 'origin_app': 'opendart',
            'published_at': receipt_date(receipt), 'retrieved_at': now,
            'locator': 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+receipt,
            'request_url': request_url, 'classification': 'PUBLIC', 'synthetic': False,
            'data_origin': 'opendart_public', 'content_trust': 'untrusted_external_data',
            'spans': [], 'full_text_read': False, 'original_verified': False}
