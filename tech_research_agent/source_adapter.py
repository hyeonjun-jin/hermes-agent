"""Reuse the P1 execution contract with server-selected backend configuration only."""
import copy

from .connectors import PublicConnector
from tech_research_benchmark.adapter import OfflineAdapter
from tech_research_benchmark.policy import validate


class SourceAdapter(OfflineAdapter):
    def __init__(self, context, corpus, registry, *, connectors: dict[str, PublicConnector]):
        super().__init__(context, corpus, registry)
        self.connectors = dict(connectors)
        dart = self.connectors.get('opendart')
        if dart is not None:
            context.entity_topics = {code: None for code in dart.company_catalog.entries
                                     if dart.company_catalog.permits(code, context)}

    def _execute(self, call):
        connector = self.connectors.get(call.get('app')) if isinstance(call, dict) else None
        if connector is None:
            return super()._execute(call)
        reason = validate(call, self.context, self.corpus, self.registry)
        if not reason and self.context.classification != 'PUBLIC':
            reason = 'public_connector_requires_public_environment'
        if not reason and call['app'] == 'opendart' and not self._company_permitted(call):
            reason = 'access_denied'
        event = {'index': len(self.trace), 'plan': call, 'executed': False,
                 'execution_args': None, 'reason': reason, 'result': None}
        self.trace.append(event)
        if reason:
            result = {'status': 'denied', 'reason': reason, 'cost': {'mock_units': 0, 'source_requests': 0}}
        else:
            params = {**call['rp'], **call['op']}
            if call['api'] == 'read_disclosure':
                params['_document'] = copy.deepcopy(self.corpus[params['receipt_no']])
            if call['api'] == 'read_patent':
                params['_patent'] = copy.deepcopy(self.corpus[params['application_id']])
            if call['app'] == 'posco_ir':
                params['_context'] = self.context
                if call['api'] == 'read_material':
                    params['_material'] = copy.deepcopy(self.corpus[params['material_id']])
            result = connector.execute(call['api'], params, self.context.cutoff)
            units = result['cost'].get('tool_units', int(bool(result['cost']['source_requests'])))
            attempted = bool(units)
            self.context.spent += units
            event.update(executed=attempted, execution_args={'rp': call['rp'], 'op': call['op']} if attempted else None,
                         reason=result.get('reason'))
            self._register(result, call['api'])
        event['result'] = copy.deepcopy(result)
        return copy.deepcopy(result)

    def _register(self, result, api):
        sources = {item['source_id']: self._source(item) for item in result.get('items', [])}
        if (self.context.classification != 'PUBLIC' or
                self.context.project_id not in self.context.allowed_projects or
                any(not self.context.permits(source) or not self._source_company_permitted(source)
                    for source in sources.values())):
            # Recheck after I/O; a revocation must not become an empty search.
            result.update(status='denied', reason='access_denied', items=[], warnings=[])
            if 'rows' in result:
                result['rows'] = []
            return
        self.corpus.update(sources)
        if api in {'search_works', 'list_disclosures', 'search_patents', 'search_materials'}:
            self.context.seen.update(sources)

    @staticmethod
    def _source(item):
        return {'id': item['source_id'], 'app': item['origin_app'], 'title': item['title'],
                'published_at': item['published_at'], 'classification': 'PUBLIC',
                'project_id': None, 'locator': item['locator'], 'spans': copy.deepcopy(item['spans']),
                'synthetic': False, 'topic': None, 'corp_code': item.get('corp_code'),
                'open_number': item.get('open_number'), 'catalog_binding': item.get('catalog_binding')}

    def _company_permitted(self, call):
        code = call['rp'].get('corp_code')
        if call['api'] == 'read_disclosure':
            code = self.corpus[call['rp']['receipt_no']].get('corp_code')
        return self.connectors['opendart'].company_catalog.permits(code, self.context)

    def _source_company_permitted(self, source):
        if source['app'] == 'posco_ir':
            return self.connectors['posco_ir'].permits_material(source['id'], self.context, source)
        if source['app'] != 'opendart':
            return True
        return self.connectors['opendart'].company_catalog.permits(source.get('corp_code'), self.context)


def source_issues(trace):
    """Carry bounded retrieval and execution failures across role boundaries."""
    return [{'app': e['plan']['app'], 'api': e['plan']['api'], 'status': e['result']['status'],
             'reason': e['result'].get('reason') or e.get('reason'), 'warnings': e['result'].get('warnings', [])}
            for e in trace if e['result']['status'] not in {'ok', 'empty'} or e['result'].get('warnings')]


def source_limit_text(trace):
    statuses = {'partial': '일부 범위만 확인', 'denied': '접근 거부', 'unavailable': '조회 실패'}
    names = {'opendart': 'OpenDART', 'openalex': 'OpenAlex', 'kipris_plus': 'KIPRIS',
             'posco_ir': 'POSCO IR', 'internal_mock': '사내 Mock'}
    limits = sorted({names.get(issue['app'], issue['app'])+': '+statuses.get(issue['status'], '조회 제한')
                     for issue in source_issues(trace)})
    return '; '.join(limits)+'. 상세 사유는 실행 기록을 확인하세요.'


def is_original_evidence(item):
    if item['origin_app'] != 'posco_ir' or item.get('synthetic') is True:
        return True
    return item.get('evidence_coverage') == 'ir_pdf_text' and any(s['kind'] == 'ir_pdf_text' and s['text'] for s in item['spans'])
