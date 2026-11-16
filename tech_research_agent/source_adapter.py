"""Reuse the P1 execution contract with server-selected backend configuration only."""
import copy

from .connectors import PublicConnector
from tech_research_benchmark.adapter import OfflineAdapter
from tech_research_benchmark.policy import validate


class SourceAdapter(OfflineAdapter):
    def __init__(self, context, corpus, registry, *, connectors: dict[str, PublicConnector]):
        super().__init__(context, corpus, registry)
        self.connectors = dict(connectors)

    def _execute(self, call):
        connector = self.connectors.get(call.get('app')) if isinstance(call, dict) else None
        if connector is None:
            return super()._execute(call)
        reason = validate(call, self.context, self.corpus, self.registry)
        if not reason and self.context.classification != 'PUBLIC':
            reason = 'public_connector_requires_public_environment'
        event = {'index': len(self.trace), 'plan': call, 'executed': False,
                 'execution_args': None, 'reason': reason, 'result': None}
        self.trace.append(event)
        if reason:
            result = {'status': 'denied', 'reason': reason, 'cost': {'mock_units': 0, 'source_requests': 0}}
        else:
            params = {**call['rp'], **call['op']}
            result = connector.execute(call['api'], params, self.context.cutoff)
            attempted = bool(result['cost']['source_requests'])
            self.context.spent += int(attempted)
            event.update(executed=attempted, execution_args={'rp': call['rp'], 'op': call['op']} if attempted else None,
                         reason=result.get('reason'))
            self._register(result, call['api'])
        event['result'] = copy.deepcopy(result)
        return copy.deepcopy(result)

    def _register(self, result, api):
        sources = {item['source_id']: self._source(item) for item in result.get('items', [])}
        if (self.context.classification != 'PUBLIC' or
                self.context.project_id not in self.context.allowed_projects or
                any(not self.context.permits(source) for source in sources.values())):
            # Recheck after I/O; a revocation must not become an empty search.
            result.update(status='denied', reason='access_denied', items=[], warnings=[])
            return
        self.corpus.update(sources)
        if api == 'search_works':
            self.context.seen.update(sources)

    @staticmethod
    def _source(item):
        return {'id': item['source_id'], 'app': item['origin_app'], 'title': item['title'],
                'published_at': item['published_at'], 'classification': 'PUBLIC',
                'project_id': None, 'locator': item['locator'], 'spans': copy.deepcopy(item['spans']),
                'synthetic': False, 'topic': None}
