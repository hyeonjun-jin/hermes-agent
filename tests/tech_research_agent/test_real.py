"""Stub-only Real gateway tests. No OpenAI transport is ever used."""
import copy
import json
import pytest
from tech_research_agent.real import RealAdapter,RealBlocked,PayloadPolicy,public_context
from tech_research_agent.config import runtime
from tech_research_agent.application import ResearchApplication,principal


def ledger(tmp_path,calls=None):
    path=tmp_path/'usage.json'
    path.write_text(json.dumps({'calls':calls or [],'failed':False}))
    return path


def payload(content='PUBLIC SYNTHETIC'):
    return {'messages':[{'role':'user','content':content}],'tools':[]}


def response(message,reason='stop'):
    return 200,{'id':'stub','created':1,'model':'gpt-4o-mini','choices':[{'message':message,'finish_reason':reason}],
                'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}}


def test_reservation_precedes_transport_and_survives_restart(tmp_path):
    path=ledger(tmp_path);sent=[]
    def send(body):
        saved=json.loads(path.read_text())
        assert saved['calls'][-1]['status']=='pending'
        assert saved['calls'][-1]['reserved_usd_upper_bound']>0
        sent.append(body)
        return response({'role':'assistant','content':'SYNTHETIC'})
    real=RealAdapter(path,enabled=True,exclusive_ledger_owner=True,transport=send)
    _,_,adapter=runtime('researcher','H','quick')
    with real.endpoint(adapter.corpus) as url:
        import httpx
        assert httpx.post(url+'/chat/completions',json=payload()).status_code==200
    assert len(sent)==1 and len(json.loads(path.read_text())['calls'])==1
    assert 'raw_tool_calls' in real.audit[-1]
    first=json.loads(path.read_text())['calls'][0]
    restarted=RealAdapter(path,enabled=True,exclusive_ledger_owner=True,transport=send)
    with restarted.endpoint(adapter.corpus) as url:
        assert httpx.post(url+'/chat/completions',json=payload()).status_code==200
    saved=json.loads(path.read_text())
    assert len(saved['calls'])==2 and saved['calls'][0]==first


@pytest.mark.parametrize('content',['proj-H private','/home/secret','H-N2F','PRIVATE_MEMORY'])
def test_whole_payload_blocked_before_reservation(tmp_path,content):
    path=ledger(tmp_path);sent=[]
    real=RealAdapter(path,enabled=True,exclusive_ledger_owner=True,transport=lambda b:sent.append(b))
    _,_,adapter=runtime('researcher','H','quick')
    with real.endpoint(adapter.corpus) as url:
        import httpx
        body=payload();body['tools']=[{'description':content}]
        assert httpx.post(url+'/chat/completions',json=body).status_code==403
    assert not sent and json.loads(path.read_text())['calls']==[]
    assert json.loads(path.read_text())['failed']


def test_existing_exhausted_missing_and_pending_ledgers_do_not_reset(tmp_path):
    for saved in ({'calls':[{}]*5,'failed':False},{'calls':[],'failed':True},{'calls':[{'status':'pending'}],'failed':False}):
        path=tmp_path/'usage.json';path.write_text(json.dumps(saved));before=path.read_bytes()
        with pytest.raises(RealBlocked):RealAdapter(path,enabled=True,exclusive_ledger_owner=True).preflight()
        assert path.read_bytes()==before
    with pytest.raises(RealBlocked):RealAdapter(tmp_path/'absent/usage.json',enabled=True,exclusive_ledger_owner=True).preflight()


def test_public_context_rejects_private_memory_and_security_levels():
    ctx={'environment':{'classification':'PUBLIC','topic':'H','project_id':'proj-H'},'profile':{},
         'history':[],'approved_preferences':{},'question':'수소환원제철을 비교 조사해주세요.'}
    assert 'project_id' not in public_context(ctx)['environment']
    for field,value in [('history',[{'summary':'secret'}]),('approved_preferences',{'source_focus':'science'}),
                        ('environment',{'classification':'RESTRICTED'})]:
        bad=copy.deepcopy(ctx);bad[field]=value
        with pytest.raises(RealBlocked):public_context(bad)


def test_real_hermes_uses_stub_choice_not_mock_rules(tmp_path):
    path=ledger(tmp_path);requests=[]
    def send(body):
        requests.append(copy.deepcopy(body))
        text='\n'.join(m.get('content','') or '' for m in body['messages'] if m['role']=='user')
        if '[PERSONA_ROLE=research]' in text and not any(m['role']=='tool' for m in body['messages']):
            return response({'role':'assistant','content':None,'tool_calls':[{'id':'independent-choice','type':'function',
               'function':{'name':'opendart__read_financials','arguments':json.dumps({'rp':{'corp_code':'00000001','bsns_year':'2025','reprt_code':'11011','fs_div':'CFS'},'op':{}})}}]},'tool_calls')
        return response({'role':'assistant','content':'SYNTHETIC 검토 결과. 실제 기술 우열은 미확인.'})
    real=RealAdapter(path,enabled=True,exclusive_ledger_owner=True,transport=send)
    app=ResearchApplication(tmp_path/'app',real_adapter=real)
    result=app.ask(principal('researcher'),'researcher','수소환원제철을 비교 조사해주세요.',execution_mode='real')
    assert result['trace'],real.audit
    assert result['mode']=='real' and result['trace'][0]['plan']['app']=='opendart'
    assert len(requests)==4 and all(b['model']=='gpt-4o-mini' for b in requests)
    assert not result['complete'] and not result['checks']['verification_read']
    assert result['trace'][0]['input_provenance']['causal_proof'] is False
    assert len(requests[0]['tools'])==11
    assert not any('proj-' in json.dumps(b) for b in requests)


def test_nested_tool_result_and_schema_cannot_leak_labels():
    _,_,adapter=runtime('researcher','H','quick')
    guard=PayloadPolicy(adapter.corpus)
    for body in [dict(payload(),messages=[{'role':'tool','content':json.dumps({'items':[{'classification':'INTERNAL','text':'secret'}]})}]),
                 dict(payload(),tools=[{'description':'proj-H'}])]:
        with pytest.raises(RealBlocked):guard.check(body)


def test_specialist_cap_and_failed_transport_never_refund(tmp_path):
    import httpx
    path=ledger(tmp_path);sent=[]
    real=RealAdapter(path,enabled=True,exclusive_ledger_owner=True,
                     transport=lambda b:(sent.append(b) or response({'role':'assistant','content':'PUBLIC SYNTHETIC'})))
    _,_,adapter=runtime('researcher','H','quick')
    with real.endpoint(adapter.corpus) as url:
        for _ in range(2):assert httpx.post(url+'/chat/completions',json=payload()).status_code==200
        assert httpx.post(url+'/chat/completions',json=payload()).status_code==429
    assert len(sent)==2 and len(json.loads(path.read_text())['calls'])==2
    assert json.loads(path.read_text())['failed']
    with pytest.raises(RealBlocked):real.preflight()


def test_transport_error_remains_reserved(tmp_path):
    import httpx
    path=ledger(tmp_path)
    def broken(body):raise RuntimeError('secret-key-must-not-leak')
    real=RealAdapter(path,enabled=True,exclusive_ledger_owner=True,transport=broken)
    _,_,adapter=runtime('researcher','H','quick')
    with real.endpoint(adapter.corpus) as url:
        result=httpx.post(url+'/chat/completions',json=payload())
    assert result.status_code==502 and 'secret-key' not in result.text
    saved=json.loads(path.read_text())
    assert len(saved['calls'])==1 and saved['failed'] and saved['calls'][0]['status']=='transport_error'
    assert saved['calls'][0]['reserved_usd_upper_bound']>0


def test_public_synthetic_preferences_supported_but_private_default_blocked(tmp_path):
    ctx={'environment':{'classification':'PUBLIC','topic':'H','project_id':'proj-H'},'profile':{},
         'history':[{'question':'[project=proj-H] public question','summary':'SYNTHETIC','data_policy':'PUBLIC_SYNTHETIC'}],
         'approved_preferences':{'source_focus':'finance','data_policy':'PUBLIC_SYNTHETIC'},'question':'수소환원제철을 비교 조사해주세요.'}
    result=public_context(ctx)
    assert result['history'][0]['question']=='public question'
    assert result['approved_preferences']['source_focus']=='finance'


def test_real_specialist_stops_at_existing_two_calls(tmp_path):
    from tech_research_agent.mock import tool_calls
    path=ledger(tmp_path);sent=[]
    def sender(body):
        sent.append(body)
        message,_=tool_calls([('openalex__search_works',{'rp':{'query':'hydrogen'},'op':{}})])
        return response(message,'tool_calls')
    real=RealAdapter(path,enabled=True,exclusive_ledger_owner=True,transport=sender)
    result=ResearchApplication(tmp_path/'app',real_adapter=real).ask(principal('researcher'),'researcher',
                  '수소환원제철을 비교 조사해주세요.',execution_mode='real')
    assert not result['complete'] and len(result['stages'])==1
    assert len(sent)==2 and result['model_calls']==2
    assert json.loads(path.read_text())['failed']
    assert 'separate budget approval' in result['real_audit']['limitation']
    assert '별도 예산 승인' in result['answer']


def test_modified_original_and_internal_context_are_blocked(monkeypatch):
    _,_,adapter=runtime('researcher','H','quick');policy=PayloadPolicy(adapter.corpus)
    item={'source_id':'H-A01','classification':'PUBLIC','synthetic':True,'spans':[{'id':'s1','text':'changed confidential text'}]}
    with pytest.raises(RealBlocked):policy.check({'messages':[{'role':'tool','content':json.dumps({'items':[item]})}]})
    with pytest.raises(RealBlocked):policy.check({'messages':[{'role':'tool','content':json.dumps({'classification':'internal','text':'unknown'})}]})
    monkeypatch.setenv('PERSONA_API_KEY','unit-test-credential-not-real')
    with pytest.raises(RealBlocked) as error:
        policy.check(payload('unit-test-credential-not-real'))
    assert 'unit-test-credential-not-real' not in str(error.value)
