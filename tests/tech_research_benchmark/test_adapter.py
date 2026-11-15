"""P1 tests use DEV corpus only; no evaluation input or Gold routing."""
import copy
import pytest
from tech_research_benchmark.offline import DATA, load, score
from tech_research_benchmark.adapter import OfflineAdapter
from tech_research_benchmark.policy import ServerContext


@pytest.fixture
def adapter():
    corpus=load(DATA/'development/corpus.json')
    ctx=ServerContext('dev-user','proj-B',{'proj-B'},{'openalex','kipris_plus','opendart','posco_ir','internal_mock'},
                      'RESTRICTED','2026-09-30',12,{sid:{'dev-user'} for sid in corpus}, {'00000002':'B'})
    ctx.classification='INTERNAL'
    return OfflineAdapter(ctx,corpus,load(DATA/'registry.json'))


def call(app,api,rp,op=None):
    return {'id':'dev-call','app':app,'api':api,'rp':rp,'op':op or {},'after':[]}


SEARCHES=[('openalex','search_works',{'query':'NCM'}),
          ('kipris_plus','search_patents',{'query':'NCM','jurisdiction':'KR'}),
          ('opendart','list_disclosures',{'corp_code':'00000002','from_date':'2022-01-01','to_date':'2026-09-30'}),
          ('posco_ir','search_materials',{'query':'NCM'}),
          ('internal_mock','search_documents',{'query':'NCM','project_id':'proj-B'})]
READS=[('openalex','read_work','work_id','DEV-B-A01'),('kipris_plus','read_patent','application_id','DEV-B-P01'),
       ('opendart','read_disclosure','receipt_no','DEV-B-D01'),('posco_ir','read_material','material_id','DEV-B-IF01'),
       ('internal_mock','read_document','document_id','DEV-B-N2F')]


@pytest.mark.parametrize('search,read',zip(SEARCHES,READS))
def test_search_then_read(adapter,search,read):
    app,api,rp=search
    result=adapter.execute(call(app,api,rp,{'limit':10}))
    assert result['status']=='ok'
    assert all(i['synthetic'] and i['spans'] for i in result['items'])
    app,api,key,sid=read
    result=adapter.execute(call(app,api,{key:sid},{'include_claims':True} if api=='read_patent' else {}))
    assert result['status']=='ok' and result['items'][0]['source_id']==sid
    assert adapter.context.spent==2


@pytest.mark.parametrize('problem',['op','rp','future','project','unseen','revoke','user','restricted','leak','budget','unknown'])
def test_pre_execution_denial(adapter,problem):
    c=call('internal_mock','search_documents',{'query':'NCM','project_id':'proj-B'})
    if problem=='op':c['op']={'limit':99}
    if problem=='rp':c['rp'].pop('query')
    if problem=='future':c['op']={'to_date':'2030-01-01'}
    if problem=='project':c['rp']['project_id']='proj-H'
    if problem in ('unseen','revoke','user'):
        c=call('internal_mock','read_document',{'document_id':'DEV-B-N2F'})
        if problem!='unseen':adapter.context.seen.add('DEV-B-N2F')
        if problem=='revoke':adapter.context.revoked.add('DEV-B-N2F')
        if problem=='user':adapter.context.user_id='other-user'
    if problem=='restricted':
        adapter.context.classification='RESTRICTED';c=call('openalex','search_works',{'query':'NCM'})
    if problem=='leak':c=call('openalex','search_works',{'query':'NCM proj-B'})
    if problem=='budget':adapter.context.budget=0
    if problem=='unknown':c['api']='upload'
    before=adapter.context.spent
    result=adapter.execute(c)
    assert result['status']=='denied' and 'items' not in result
    assert adapter.context.spent==before
    assert not adapter.trace[-1]['executed'] and adapter.trace[-1]['execution_args'] is None


def test_revoke_between_search_read(adapter):
    adapter.execute(call('internal_mock','search_documents',{'query':'NCM','project_id':'proj-B'},{'limit':10}))
    adapter.context.document_acl['DEV-B-N2F'].clear()
    assert adapter.execute(call('internal_mock','read_document',{'document_id':'DEV-B-N2F'}))['status']=='denied'


def test_states_duplicates_and_snapshots(adapter):
    c=call('openalex','search_works',{'query':'NCM'})
    adapter.execute(c);adapter.execute(c)
    assert adapter.context.spent==2
    c['rp']['query']='no-matching-token'
    assert adapter.execute(c)['status']=='empty'
    adapter.faults['openalex/search_works']='unavailable'
    assert adapter.execute(c)['status']=='unavailable'
    adapter.faults['openalex/search_works']='partial'
    assert adapter.execute(c)['status']=='partial'
    assert adapter.trace[0]['plan']['rp']['query']=='NCM'


def test_financials_and_egress(adapter):
    c=call('opendart','read_financials',{'corp_code':'00000002','bsns_year':'2025','reprt_code':'11011','fs_div':'CFS'})
    assert adapter.execute(c)['status']=='partial'  # DEV corpus deliberately has no invented finance rows.
    assert not adapter.context.authorize_llm('external',['DEV-B-N2F'],adapter.corpus)
    adapter.context.classification='RESTRICTED'
    assert not adapter.context.authorize_llm('external',[],adapter.corpus)
    assert adapter.context.authorize_llm('local',['DEV-B-N3F'],adapter.corpus)


def test_replay_scorer_bridge(adapter):
    case=load(DATA/'development/input.json');gold=load(DATA/'development/gold.json')
    # Explicit DEV sequence, not obtained from Gold.
    calls=[call('internal_mock','search_documents',{'query':'NCM','project_id':'proj-B'}, {'evidence_kind':'financial','sort':'date_desc','limit':3}),
           call('internal_mock','read_document',{'document_id':'DEV-B-N3F'},{'sections':['assumptions']})]
    adapter.context.classification='RESTRICTED'
    adapter.context.allowed_sources={'internal_mock'}
    trace=adapter.replay(calls)
    inputs=adapter.scorer_inputs()
    result=score(case,gold,inputs['predicted'],inputs['evidence'],adapter.corpus,adapter.registry)
    assert trace[-1]['result']['status']=='ok' and result['required_evidence']==1
    assert inputs['policy_audit']==[] and inputs['mock_units']==2


def test_denial_cannot_disappear_in_scorer(adapter):
    from tech_research_benchmark.replay_score import score_replay
    adapter.context.allowed_sources={'internal_mock'}
    adapter.execute(call('openalex','search_works',{'query':'NCM'}))
    report=score_replay(load(DATA/'development/input.json'),load(DATA/'development/gold.json'),
                        adapter.scorer_inputs(),adapter.corpus,adapter.registry)
    assert report['business_success'] is False and not report['structural_success']
    assert report['attempts']==1 and report['mock_units']==0


def test_valid_schema_but_unsupported_filter_is_partial(adapter):
    assert adapter.execute(call('openalex','search_works',{'query':'NCM'},{'open_access':True}))['status']=='partial'


def test_budget_is_consumed_by_duplicates(adapter):
    adapter.context.budget=2
    c=call('openalex','search_works',{'query':'NCM'})
    assert adapter.execute(c)['status']=='ok'
    assert adapter.execute(c)['status']=='ok'
    assert adapter.execute(c)=={'status':'denied','reason':'budget_exhausted','cost':{'mock_units':0}}


def test_denied_response_does_not_disclose_hidden_metadata(adapter):
    adapter.context.revoked.update(adapter.corpus)
    adapter.context.seen.update(adapter.corpus)
    result=adapter.execute(call('internal_mock','read_document',{'document_id':'DEV-B-N2F'}))
    assert set(result)=={'status','reason','cost'}
    assert 'DEV-B-N2F' not in str(result)


def test_pagination_is_bound_to_query_and_charged(adapter):
    c=call('openalex','search_works',{'query':'NCM'},{'limit':1})
    first=adapter.execute(c)
    # DEV topic-B has a single relevant paper; add a different DEV-only paper for paging.
    extra=copy.deepcopy(adapter.corpus['DEV-B-A01']);extra['id']='DEV-B-PAPER2'
    adapter.corpus[extra['id']]=extra
    first=adapter.execute(c)
    assert first['next_cursor']
    second=adapter.execute({**c,'op':{'limit':1,'cursor':first['next_cursor']}})
    assert second['items'][0]['source_id']!=first['items'][0]['source_id']
    assert adapter.context.spent==3
    wrong=adapter.execute({**c,'rp':{'query':'hydrogen'},'op':{'limit':1,'cursor':first['next_cursor']}})
    assert wrong['status']=='partial' and not wrong['items']


def test_financial_rows_are_selected_by_period_and_accounts(adapter):
    # Values already specified in BENCHMARK_DESIGN; DEV-only in-memory materialization.
    adapter.corpus['DEV-B-F01']['payload']={'bsns_year':'2025','fs_div':'CFS',
        'rows':[{'account_id':'operating_profit','value':'40','unit':'가상 크레딧','span_id':'s1'},
                {'account_id':'cash_flow_investing','value':'-80','unit':'가상 크레딧','span_id':'s2'}]}
    c=call('opendart','read_financials',{'corp_code':'00000002','bsns_year':'2025','reprt_code':'11011','fs_div':'CFS'},
           {'account_ids':['operating_profit']})
    result=adapter.execute(c)
    assert result['status']=='ok' and [r['value'] for r in result['rows']]==['40']
    assert [i['source_id'] for i in result['items']]==['DEV-B-F01']
    c['op']['account_ids'].append('net_debt')
    assert adapter.execute(c)['status']=='partial'
    c['rp']['bsns_year']='2024'
    result=adapter.execute(c)
    assert result['status']=='partial' and result['rows']==[] and result['items']==[]
