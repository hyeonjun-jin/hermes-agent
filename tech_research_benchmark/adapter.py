"""Local corpus execution. No Gold, model client, HTTP client or Hermes integration."""
import copy
import re
import json
import uuid
from .policy import validate

READ_KEYS = {'read_work':'work_id','read_patent':'application_id','read_disclosure':'receipt_no',
             'read_material':'material_id','read_document':'document_id'}
TOPICS = {'H': {'hydrogen','iron','수소환원','수소환원제철','유동층','샤프트로'},
          'B': {'ncm','lfp','cathode','양극재','고니켈'}}


class OfflineAdapter:
    def __init__(self, context, corpus, registry, *, faults=None):
        self.context = context
        self.corpus = copy.deepcopy(corpus)
        self.registry = copy.deepcopy(registry)
        self.faults = dict(faults or {})  # Trusted fault injection, never model-supplied.
        self.trace = []
        self.cursors = {}

    def execute(self, call):
        with self.context.lock:
            return self._execute(copy.deepcopy(call))

    def _execute(self, call):
        reason = validate(call, self.context, self.corpus, self.registry)
        event = {'index':len(self.trace), 'plan':call, 'executed':False, 'execution_args':None,
                 'reason':reason, 'result':None}
        self.trace.append(event)
        if reason:
            result = {'status':'denied','reason':reason,'cost':{'mock_units':0}}
            event['result'] = result
            return copy.deepcopy(result)
        self.context.spent += 1
        event.update(executed=True, execution_args={'rp':call['rp'],'op':call['op']})
        status = self.faults.get(call['app']+'/'+call['api'])
        if status == 'unavailable':
            result = self._result('unavailable', [], warnings=['fixture_backend_unavailable'])
        elif call['api'] in READ_KEYS:
            source = self.corpus[call['rp'][READ_KEYS[call['api']]]]
            result = self._read(call, source)
        elif call['api'] == 'read_financials':
            result = self._financials(call)
        else:
            result = self._search(call)
        if status == 'partial':
            result['status'] = 'partial'
            result['warnings'].append('injected_partial_coverage')
        event['result'] = copy.deepcopy(result)
        return copy.deepcopy(result)

    def _result(self, status, sources, *, warnings=()):
        return {'status':status, 'items':[{'source_id':s['id'],'title':s['title'],'origin_app':s['app'],
                'retrieved_at':self.context.observed_at,
                'published_at':s['published_at'],'classification':s['classification'],
                'locator':s['locator'],'synthetic':True,'spans':copy.deepcopy(s['spans'])} for s in sources],
                'cost':{'mock_units':1}, 'warnings':list(warnings), 'next_cursor':None}

    def _search(self, call):
        params = {**call['rp'], **call['op']}
        unsupported = set(params) & {'applicant','ipc','open_access'}
        if params.get('language','ko') != 'ko':
            unsupported.add('language')
        if unsupported:
            return self._result('partial',[],warnings=['filter_metadata_unavailable:' + ','.join(sorted(unsupported))])
        query = params.get('query',params.get('keyword',''))
        terms = set(re.findall(r'\w+',query.casefold()))
        topic = self.context.entity_topics.get(params.get('corp_code'))
        candidates = []
        for source in self.corpus.values():
            if call['api'] == 'list_disclosures' and not source['id'].endswith('D01'):
                continue
            if source['app'] != call['app'] or not self.context.permits(source):
                continue
            text = source['title']+' '+' '.join(s['text'] for s in source['spans'])
            indexed = set(re.findall(r'\w+',text.casefold()))
            if 'NOISE' not in source['id']:
                indexed |= TOPICS.get(source['topic'],set())
            if topic and source['topic'] != topic:
                continue
            if terms and not terms & indexed:
                continue
            if not params.get('from_date','') <= source['published_at'] <= params.get('to_date',self.context.cutoff):
                continue
            if not self._filters(source,params):
                continue
            candidates.append(source)
        candidates.sort(key=lambda s:(s['published_at'],s['id']),reverse=params.get('sort')=='date_desc')
        binding = json.dumps([self.context.user_id,self.context.project_id,call['app'],call['api'],
                              {k:v for k,v in params.items() if k!='cursor'}],sort_keys=True)
        cursor = params.get('cursor')
        offset = 0
        if cursor:
            previous = self.cursors.get(cursor)
            if not previous or previous[0] != binding:
                return self._result('partial',[],warnings=['invalid_or_mismatched_cursor'])
            offset = previous[1]
        limit = params.get('limit',3)
        selected = candidates[offset:offset+limit]
        self.context.seen.update(s['id'] for s in selected)
        result = self._result('ok' if selected else 'empty',selected)
        if offset+limit < len(candidates):
            token = uuid.uuid4().hex
            self.cursors[token] = (binding,offset+limit)
            result['next_cursor'] = token
        return result

    @staticmethod
    def _filters(source, params):
        sid = source['id']
        if source['app']=='opendart' and params.get('report_type','all') not in ('all','material'):
            return False
        if 'evidence_kind' in params and params['evidence_kind'] != 'all':
            suffix = {'experiment':'R','strategy':'S','financial':'F'}[params['evidence_kind']]
            if not sid.endswith(suffix):
                return False
        if params.get('kind','all') != 'all':
            if ('IS01' if params['kind']=='strategy' else 'IF01') not in sid:
                return False
        if params.get('types') and 'article' not in params['types']:
            return False
        return True

    def _read(self, call, source):
        op = call['op']
        if (call['api']=='read_patent' and not op.get('include_claims',False)) or (call['api']=='read_work' and op.get('include_abstract') is False):
            return self._result('partial',[],warnings=['requested_metadata_only_not_available'])
        pages = op.get('pages')
        if pages and pages != [2 if 'IS01' in source['id'] else 3]:
            return self._result('partial',[],warnings=['requested_pages_unavailable'])
        sections = op.get('sections') or ([op['section']] if 'section' in op else [])
        if sections and not set(sections) <= {'conditions','decision','assumptions','technology_project'}:
            return self._result('partial',[],warnings=['requested_sections_unavailable'])
        return self._result('ok',[source])

    def _financials(self, call):
        params = {**call['rp'], **call['op']}
        topic = self.context.entity_topics[params['corp_code']]
        sources = [s for s in self.corpus.values() if s['topic']==topic and s['app']=='opendart' and s['id'].rsplit('-',1)[-1]=='F01'
                   and self.context.permits(s)]
        rows = []
        for source in sources:
            payload = source.get('payload',{})
            if payload.get('bsns_year') == params['bsns_year'] and payload.get('fs_div') == params['fs_div'] and params['reprt_code']=='11011':
                rows.extend(r for r in payload.get('rows',[]) if not params.get('account_ids') or r['account_id'] in params['account_ids'])
        result = self._result('ok' if rows else 'partial',sources if rows else [],warnings=[] if rows else ['financial_rows_not_available'])
        if params.get('account_ids') and set(params['account_ids']) - {r['account_id'] for r in rows}:
            result['status'] = 'partial'
            result['warnings'].append('requested_accounts_incomplete')
        result['rows'] = copy.deepcopy(rows)
        return result

    def replay(self, calls):
        for call in calls:
            self.execute(call)
        return copy.deepcopy(self.trace)

    def scorer_inputs(self):
        """Completed read evidence only. Denied attempts stay in the policy audit."""
        calls = [e['plan'] for e in self.trace if e['executed'] and e['result']['status'] in ('ok','empty','partial')]
        evidence = [{'document_id':item['source_id'],'span_id':span['id']}
                    for e in self.trace if e['executed'] and e['plan']['api'].startswith('read_')
                    and e['result']['status'] in ('ok','partial')
                    for item in e['result']['items'] for span in item['spans']]
        return {'predicted':calls,'evidence':evidence,
                'policy_audit':[{'index':e['index'],'reason':e['reason']} for e in self.trace if not e['executed']],
                'mock_units':self.context.spent,
                'attempts':len(self.trace),
                'execution_failures':[e['index'] for e in self.trace if e['executed'] and e['result']['status']=='unavailable']}
