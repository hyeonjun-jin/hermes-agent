"""Smoke workflow counts and safe interruption; no model evaluation or scoring."""
import json
import pytest
from tech_research_agent.application import ResearchApplication,principal
from tech_research_agent.stub_workflow import WorkflowStub,StubWorkflowAdapter
from tech_research_agent.real import RealAdapter


def execute(tmp_path,sender,*,legacy=False,cost=0.11):
    path=tmp_path/'usage.json';path.write_text(json.dumps({'calls':[],'failed':False}))
    adapter=RealAdapter(path,enabled=True,exclusive_ledger_owner=True,transport=sender) if legacy else StubWorkflowAdapter(path,sender,cost_ceiling=cost)
    result=ResearchApplication(tmp_path/'app',real_adapter=adapter).ask(principal('researcher'),'researcher',
                    '수소환원제철을 비교 조사해주세요.',execution_mode='real')
    return result,json.loads(path.read_text())


@pytest.mark.parametrize('retry,repeat,expected',[(False,False,{'research':3,'analysis':1,'verification':2}),
    (True,False,{'research':4,'analysis':1,'verification':2}),(True,True,{'research':4,'analysis':1,'verification':3}),
    (2,True,{'research':5,'analysis':1,'verification':3})])
def test_complete_stub_workflows(tmp_path,retry,repeat,expected):
    sender=WorkflowStub(retry_search=retry,repeat_reads=repeat)
    result,saved=execute(tmp_path,sender)
    assert result['complete'] and sender.counts==expected
    assert result['progress']['calls_by_role']==expected and result['progress']['remaining_work']==[]
    assert len(saved['calls'])==sum(expected.values())
    assert result['real_audit']['transport_mode']=='stub'
    assert result['real_audit']['audit'][0]['raw_tool_calls']
    assert result['stages'][-1]['raw_answer'] in result['answer']
    assert all(e['executed'] for e in result['trace'])


def test_legacy_stops_before_third_research_request(tmp_path):
    sender=WorkflowStub();result,saved=execute(tmp_path,sender,legacy=True)
    assert not result['complete'] and sender.counts=={'research':2,'analysis':0,'verification':0}
    assert result['progress']['stopped_role']=='research'
    assert 'Research 최종 응답' in result['progress']['remaining_work']
    assert len(saved['calls'])==2 and saved['failed']


@pytest.mark.parametrize('missing,cost',[(True,0.11),(False,0)])
def test_missing_evidence_and_cost_stop(tmp_path,missing,cost):
    sender=WorkflowStub(missing=missing);result,saved=execute(tmp_path,sender,cost=cost)
    assert not result['complete']
    if cost==0:
        assert not sender.requests and not saved['calls'] and saved['failed']
        assert result['progress']['stop_reason']=='Stub cost ceiling reached'
        assert '비용 예약 상한' in result['answer']
    else:assert not result['evidence']


def test_direct_financial_minimum_five_fits_legacy_limit(tmp_path):
    sender=WorkflowStub(direct_financial=True)
    result,saved=execute(tmp_path,sender,legacy=True)
    assert result['complete'] and sender.counts=={'research':2,'analysis':1,'verification':2}
    assert len(saved['calls'])==5


def test_task_ten_call_ceiling_and_ledger_reload(tmp_path):
    import httpx
    from tech_research_agent.config import runtime
    path=tmp_path/'usage.json';path.write_text(json.dumps({'calls':[],'failed':False}))
    _,_,tools=runtime('researcher','H','quick')
    adapter=StubWorkflowAdapter(path,WorkflowStub())
    with adapter.endpoint(tools.corpus) as url:
        for role,count in [('research',5),('analysis',2),('verification',3)]:
            adapter.role=role
            for _ in range(count):
                assert httpx.post(url+'/chat/completions',json={'messages':[{'role':'user','content':'PUBLIC SYNTHETIC'}]}).status_code==200
        assert httpx.post(url+'/chat/completions',json={'messages':[{'role':'user','content':'PUBLIC SYNTHETIC'}]}).status_code==429
    saved=json.loads(path.read_text())
    assert len(saved['calls'])==10 and saved['failed']
    from tech_research_agent.real import RealBlocked
    with pytest.raises(RealBlocked):StubWorkflowAdapter(path,WorkflowStub()).preflight()


def test_shared_backend_lease_blocks_then_releases_without_changing_ledger(tmp_path):
    from persona_prototype.usage_lock import claim_usage_lock
    from tech_research_agent.config import runtime
    path=tmp_path/'usage.json';path.write_text(json.dumps({'calls':[],'failed':False}))
    before=path.read_bytes();_,_,tools=runtime('researcher','H','quick')
    adapter=StubWorkflowAdapter(path,WorkflowStub())
    with claim_usage_lock(path):
        with pytest.raises(RuntimeError,match='already owned'):
            with adapter.endpoint(tools.corpus):pass
    assert path.read_bytes()==before
    with adapter.endpoint(tools.corpus):pass
    assert path.read_bytes()==before


def test_legacy_real_backend_startup_participates_in_lease(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from persona_prototype import web_backend
    from persona_prototype.usage_lock import claim_usage_lock
    path=tmp_path/'usage.json';path.write_text(json.dumps({'calls':[],'failed':False}))
    monkeypatch.setattr(web_backend,'real_settings',lambda env:('https://api.openai.com/v1','stub-key','gpt-4o-mini'))
    monkeypatch.setattr(web_backend,'check_real_network',lambda env:None)
    before=path.read_bytes()
    with claim_usage_lock(path):
        with pytest.raises(RuntimeError,match='already owned'):
            with TestClient(web_backend.create_app(tmp_path,mode='real',dev_mode=True)):pass
    assert path.read_bytes()==before
