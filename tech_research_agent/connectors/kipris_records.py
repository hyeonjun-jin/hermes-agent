"""Patent facts are reported assertions, not experiments, commercialization or legal clearance."""
import json
import re
from datetime import datetime

from .kipris_xml import fields, text

FIELDS = ('applicationNumber', 'applicationDate', 'inventionTitle', 'openNumber', 'openDate',
          'publicationNumber', 'publicationDate', 'registerNumber', 'registerDate', 'registerStatus')
IPC = re.compile(r'[A-H][0-9]{2}[A-Z](?:\s*[0-9]{1,4}/[0-9]{1,6})?\Z')


def application_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'10[0-9]{11}', value):
        raise ValueError('invalid_kr_patent_application_number')
    return value


def patent_date(value):
    if not value:
        return None
    if not re.fullmatch(r'(?:[0-9]{8}|[0-9]{4}/[0-9]{2}/[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})', value):
        raise ValueError('unsupported_patent_date_format')
    for fmt in ('%Y%m%d', '%Y/%m/%d %H:%M:%S'):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError('invalid_patent_date')


def normalize(raw, *, applicants, ipcs, abstract, now, url, cutoff):
    app = application_id(raw['applicationNumber'])
    opened = patent_date(raw.get('openDate'))
    applied = patent_date(raw.get('applicationDate'))
    registered = patent_date(raw.get('registerDate'))
    announced = patent_date(raw.get('publicationDate'))
    title = raw.get('inventionTitle')
    if not opened or not title or opened > cutoff or (applied and applied > opened):
        raise ValueError('missing_or_invalid_publication_metadata')
    if any(day and day > cutoff for day in (applied, registered, announced)):
        raise ValueError('record_contains_future_dated_event')
    numbers = {name: raw.get(name) or None for name in ('openNumber', 'publicationNumber', 'registerNumber')}
    if any(value is not None and not re.fullmatch(r'[0-9]{13}', value) for value in numbers.values()):
        raise ValueError('invalid_patent_number')
    bibliographic = {name: value for name, value in raw.items() if value is not None}
    item = {'source_id': app, 'application_id': app, 'application_number': app,
            'open_number': numbers['openNumber'], 'gazette_number': numbers['publicationNumber'],
            'registration_number': numbers['registerNumber'], 'title': title, 'jurisdiction': 'KR',
            'application_date': applied, 'open_date': opened, 'gazette_date': announced,
            'registration_date': registered, 'published_at': opened,
            'registration_status_as_reported': raw.get('registerStatus') or None,
            'rights_validity_verified': False, 'rights_status_as_of': None,
            'commercialization_verified': False, 'performance_verified': False, 'fto_verified': False,
            'applicants': applicants, 'ipc': ipcs, 'abstract': abstract or None,
            'origin_app': 'kipris_plus', 'classification': 'PUBLIC', 'synthetic': False,
            'data_origin': 'kipris_plus_public', 'content_trust': 'untrusted_external_data',
            'retrieved_at': now, 'request_url': url,
            'locator': url, 'full_text_read': False, 'full_text_available': None,
            'full_text_download_urls': [], 'full_text_download_metadata': 'not_requested_in_v1',
            'claims_read': False, 'claims_complete': False, 'original_verified': False,
            'evidence_coverage': 'metadata_only',
            'spans': [{'id': 'bibliography', 'kind': 'patent_bibliography',
                       'text': json.dumps(bibliographic, ensure_ascii=False, sort_keys=True)}]}
    if abstract:
        item['spans'].append({'id': 'abstract', 'kind': 'patent_abstract', 'text': abstract})
    return item


def search_item(node, now, url, cutoff):
    raw = fields(node, FIELDS)
    applicants = [text(node, 'applicantName')] if text(node, 'applicantName') else []
    ipcs = [code.strip() for code in (text(node, 'ipcNumber') or '').split('|') if code.strip()]
    return normalize(raw, applicants=applicants, ipcs=ipcs, abstract=text(node, 'astrtCont'), now=now, url=url, cutoff=cutoff)


def detail_item(node, params, now, url, cutoff):
    summaries = node.findall('biblioSummaryInfoArray/biblioSummaryInfo')
    if len(summaries) != 1:
        raise ValueError('missing_or_ambiguous_bibliography')
    raw = fields(summaries[0], FIELDS)
    item = normalize(raw, applicants=[text(n, 'name') for n in node.findall('applicantInfoArray/applicantInfo') if text(n, 'name')],
                     ipcs=[text(n, 'ipcNumber') for n in node.findall('ipcInfoArray/ipcInfo') if text(n, 'ipcNumber')],
                     abstract=text(node, 'abstractInfoArray/abstractInfo/astrtCont'), now=now, url=url, cutoff=cutoff)
    known = params['_patent']
    if item['source_id'] != params['application_id'] or item['published_at'] != known['published_at']:
        raise ValueError('search_detail_identity_or_publication_mismatch')
    if known.get('open_number') and item['open_number'] != known['open_number']:
        raise ValueError('publication_number_changed')
    warnings = []
    if params.get('include_claims', False):
        claims = [text(n, 'claim') for n in node.findall('claimInfoArray/claimInfo') if text(n, 'claim')]
        count = text(summaries[0], 'claimCount')
        item['claim_count_as_reported'] = count
        item['claims_read'] = bool(claims)
        item['claims_complete'] = bool(claims) and count is not None and count.isdigit() and int(count) == len(claims) and len(set(claims)) == len(claims)
        item['spans'].extend({'id': 'claim-'+str(i+1), 'kind': 'patent_claim', 'claim_number': None,
                              'sequence_in_response': i+1, 'text': claim} for i, claim in enumerate(claims))
        if not item['claims_complete']:
            warnings.append('claims_not_returned_or_completeness_unverified')
    item['evidence_coverage'] = 'patent_claims' if item['claims_read'] else 'patent_abstract' if item['abstract'] else 'metadata_only'
    item['original_verified'] = not warnings and item['evidence_coverage'] != 'metadata_only'
    if item['evidence_coverage'] == 'metadata_only':
        warnings.append('no_substantive_patent_text')
    return item, warnings
