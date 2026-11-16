"""Reviewed POSCO Holdings public IR catalog and bounded PDF reads; no website scraping."""
import copy
import hashlib
import json
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

import httpx

from .ir_catalog import IRCatalog, official_url
from .ir_pdf import PDFParser, PDFRejected, local_pdf
from .ir_pdf_worker import MAX_PDF_BYTES


def result(status, *, items=(), warnings=(), reason=None, executed=True, requests=0, local_reads=0, parser_runs=0, cache_hit=False):
    return {'status': status, 'items': list(items), 'warnings': list(warnings), 'reason': reason, 'next_cursor': None,
            'cost': {'mock_units': 0, 'tool_units': int(executed), 'source_requests': requests,
                     'local_reads': local_reads, 'parser_runs': parser_runs, 'cache_hit': cache_hit,
                     'usd': None, 'billing_verified': False, 'quota_units': None, 'quota_verified': False}}


class SourceRejected(ValueError):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason
        super().__init__(reason)


class POSCOIRConnector:
    def __init__(self, *, enabled=False, catalog=(), local_root=None, allow_downloads=False,
                 pdf_python=None, transport=None, clock=None):
        self.enabled, self.allow_downloads = enabled, allow_downloads
        self.catalog = catalog if isinstance(catalog, IRCatalog) else IRCatalog(catalog)
        self.local_root = Path(local_root) if local_root is not None else None
        self.parser = PDFParser(python=pdf_python)
        self.clock = clock or (lambda: datetime.now(UTC).isoformat())
        self.client = httpx.Client(transport=transport, timeout=15, follow_redirects=False, trust_env=False)
        self._cache = OrderedDict()
        self._cache_lock = RLock()

    def close(self):
        self.client.close()

    def register_material(self, entry):
        self.catalog.register(entry)
        self.invalidate(entry['id'])

    def withdraw_material(self, identifier):
        self.catalog.withdraw(identifier)
        self.invalidate(identifier)

    def invalidate(self, identifier):
        with self._cache_lock:
            for key in list(self._cache):
                if key[0] == identifier:
                    del self._cache[key]

    def permits_material(self, identifier, context, known=None):
        permitted = self.catalog.permits(identifier, context, binding=known.get('catalog_binding') if known else None)
        if not permitted:
            self.invalidate(identifier)
        return permitted

    def execute(self, api, params, cutoff):
        ctx = params.get('_context')
        if self.enabled is not True or ctx is None or ctx.classification != 'PUBLIC':
            return result('denied', reason='ir_connector_or_context_not_enabled', executed=False)
        try:
            if api == 'search_materials':
                return self._search(params, cutoff, ctx)
            if api != 'read_material':
                raise SourceRejected('denied', 'unsupported_ir_api')
            identifier = params['material_id']
            known = params.get('_material')
            if known is None or not self.permits_material(identifier, ctx, known):
                raise SourceRejected('denied', 'access_denied')
            pages = params.get('pages')
            if pages is not None and (not pages or len(pages) > 100 or len(pages) != len(set(pages)) or any(type(n) is not int or n < 1 for n in pages)):
                raise SourceRejected('denied', 'invalid_pages')
            return self._read(self.catalog.get(identifier), params, ctx)
        except SourceRejected as exc:
            return result(exc.status, reason=exc.reason, executed=False)
        except (KeyError, TypeError, ValueError):
            return result('denied', reason='invalid_ir_parameters', executed=False)

    def _search(self, params, cutoff, ctx):
        if params.get('cursor') or params.get('sort', 'date_desc') not in {'date_desc','relevance'}:
            raise SourceRejected('denied', 'unsupported_ir_sort_or_cursor')
        words = set(params['query'].casefold().split())
        if not words:
            raise SourceRejected('denied', 'empty_catalog_query')
        selected = []
        for entry in self.catalog.entries():
            if not self.permits_material(entry['id'], ctx, {'catalog_binding': self.catalog.binding(entry)}):
                continue
            if not params.get('from_date', '') <= entry['published_at'] <= params.get('to_date', cutoff):
                continue
            if entry['language'] != params.get('language', 'ko') or params.get('kind', 'all') not in {'all', entry['kind']}:
                continue
            haystack = (entry['title']+' '+' '.join(entry.get('keywords', []))).casefold()
            score = sum(word in haystack for word in words)
            if score:
                selected.append((entry, score))
        selected.sort(key=lambda row: (row[0]['published_at'], row[0]['id']), reverse=True)
        if params.get('sort') == 'relevance':
            selected.sort(key=lambda row: row[1], reverse=True)
        items = [self._item(entry) for entry, _ in selected[:params.get('limit', 3)]]
        warnings = ['catalog_result_limit'] if len(selected) > params.get('limit', 3) else []
        return result('partial' if warnings else 'ok' if items else 'empty', items=items, warnings=warnings)

    def _item(self, entry):
        return {'source_id': entry['id'], 'title': entry['title'], 'origin_app': 'posco_ir',
                'published_at': entry['published_at'], 'retrieved_at': self.clock(),
                'classification': 'PUBLIC', 'synthetic': False, 'data_origin': 'posco_holdings_public_ir',
                'content_trust': 'untrusted_external_data', 'locator': entry['source_url'],
                'source_url': entry['source_url'], 'pdf_url': entry.get('pdf_url'),
                'material_type': entry['material_type'], 'kind': entry['kind'], 'language': entry['language'],
                'version': entry['version'], 'sha256': entry['sha256'], 'hash_verified': False,
                'registered_at': entry['registered_at'], 'verified_at': entry['verified_at'],
                'catalog_binding': self.catalog.binding(entry),
                'reporting_period_as_catalogued': entry.get('reporting_period'), 'reporting_period_verified': False,
                'entity_scope_as_catalogued': entry.get('entity_scope'),
                'related_disclosures_as_catalogued': entry.get('related_disclosures', []),
                'disclosure_consistency': 'not_checked', 'independent_market_validation': False,
                'evidence_coverage': 'metadata_only', 'original_verified': False, 'full_text_read': False,
                'spans': [{'id': 'metadata', 'kind': 'ir_catalog_metadata', 'text': entry['title']}]}

    def _download(self, entry):
        official_url(entry['pdf_url'], pdf=True)
        try:
            with self.client.stream('GET', entry['pdf_url']) as response:
                if response.status_code in (401, 403):
                    raise SourceRejected('denied', 'ir_source_access_denied')
                if response.status_code != 200:
                    raise SourceRejected('unavailable', 'ir_source_http_'+str(response.status_code))
                if response.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/pdf':
                    raise SourceRejected('unavailable', 'ir_source_not_pdf')
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    body.extend(chunk)
                    if len(body) > MAX_PDF_BYTES:
                        raise SourceRejected('unavailable', 'ir_pdf_download_limit')
                return bytes(body)
        except httpx.HTTPError as exc:
            raise SourceRejected('unavailable', 'ir_source_transport_error') from exc

    def _read(self, entry, params, ctx):
        if (entry is None or self.catalog.binding(entry) != params['_material'].get('catalog_binding') or
                not self.permits_material(entry['id'], ctx, params['_material'])):
            raise SourceRejected('denied', 'access_denied')
        remote = bool(entry.get('pdf_url'))
        if remote and self.allow_downloads is not True:
            raise SourceRejected('denied', 'ir_download_not_enabled')
        costs = {'requests': int(remote), 'local_reads': int(not remote), 'parser_runs': 0, 'cache_hit': False}
        try:
            data = self._download(entry) if remote else local_pdf(self.local_root, entry['local_path'])
            if hashlib.sha256(data).hexdigest() != entry['sha256']:
                self.invalidate(entry['id'])
                raise PDFRejected('ir_pdf_hash_mismatch')
            key = (entry['id'], entry['version'], entry['sha256'], self.catalog.binding(entry), tuple(params.get('pages') or []))
            parsed = self._parsed(data, key, params.get('pages'), entry, costs)
            if not self.permits_material(entry['id'], ctx, params['_material']):
                return result('denied', reason='access_denied', **costs)
            item, warnings = self._extraction(entry, parsed)
            return result('partial' if warnings else 'ok', items=[item], warnings=warnings, **costs)
        except SourceRejected as exc:
            return result(exc.status, reason=exc.reason, **costs)
        except (PDFRejected, KeyError, TypeError, ValueError):
            self.invalidate(entry['id'])
            return result('unavailable', reason='ir_pdf_unavailable_hash_or_parser', **costs)

    def _parsed(self, data, key, pages, entry, costs):
        with self._cache_lock:
            if key in self._cache:
                costs['cache_hit'] = True
                self._cache.move_to_end(key)
                return copy.deepcopy(self._cache[key])
        costs['parser_runs'] = 1
        parsed = self.parser.parse(data, pages)
        if parsed['source_sha256'] != entry['sha256']:
            raise PDFRejected('extraction_source_mismatch')
        with self._cache_lock:
            self._cache[key] = copy.deepcopy(parsed)
            if len(self._cache) > 8:
                self._cache.popitem(last=False)
        return parsed

    def _extraction(self, entry, parsed):
        item = self._item(entry)
        extracted = [row for row in parsed['pages'] if row.get('text')]
        covered = {row['page'] for row in parsed['pages'] if row['status'] == 'ok'}
        all_pages = set(range(1, parsed['page_count']+1))
        requested = {row['page'] for row in parsed['pages']}
        complete = covered == all_pages
        warnings = [] if complete else ['ir_pdf_pages_or_visuals_not_fully_read']
        spans = []
        for row in extracted:
            for offset in range(0, len(row['text']), 3000):
                spans.append({'id': f"{entry['sha256'][:12]}:p{row['page']}:s{offset}",
                              'kind': 'ir_pdf_text', 'text': row['text'][offset:offset+3000], 'page': row['page'],
                              'source_url': entry['source_url'], 'pdf_url': entry.get('pdf_url'),
                              'document_sha256': entry['sha256'], 'document_version': entry['version'],
                              'text_offset': offset})
        item.update(hash_verified=True, spans=spans, evidence_coverage='ir_pdf_text' if spans else 'none',
                    original_verified=complete, full_text_read=complete, page_count=parsed['page_count'],
                    page_statuses=[{k: v for k, v in row.items() if k != 'text'} for row in parsed['pages']],
                    read_pages=sorted(covered), text_extracted_pages=sorted(row['page'] for row in extracted),
                    unread_pages=sorted(all_pages-covered),
                    not_requested_pages=sorted(all_pages-requested), tables_charts_parsed=False,
                    layout_semantics_verified=False, parser=parsed['parser'], parser_version=parsed['parser_version'],
                    extraction_sha256=hashlib.sha256(json.dumps(parsed, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
        return item, warnings
