"""Operational Stub simulation only. Cannot use the OpenAI transport or UI paid configuration."""
import json
from persona_prototype.mini_validation import Budget
from .real import RealAdapter, ReservedBudget

CAPS={'research':5,'analysis':2,'verification':3}


class StubBudget(ReservedBudget):
    def __init__(self, send, path, *, cost_ceiling):
        super().__init__(send,path)
        self.cost_ceiling=cost_ceiling

    def forward(self, body):
        role=next(m['content'].split(']',1)[0].split('=')[-1] for m in body['messages'] if m['role']=='user')
        actor=self.case+':'+role
        reserve=(len(json.dumps(body,ensure_ascii=False).encode())*0.15+512*0.60)/1_000_000
        used=sum(c.get('reserved_usd_upper_bound',0) for c in self.calls)
        reason=None
        if len(self.calls)>=10 or self.by_actor.get(actor,0)>=CAPS[role]:reason='Stub task/role limit reached'
        if used+reserve>self.cost_ceiling:reason='Stub cost ceiling reached'
        if reason:
            self.failed=True;self.persist()
            return 429,{'error':{'message':reason}}
        before=len(self.calls)
        result=Budget.forward(self,body)
        if len(self.calls)>before:
            self.by_actor[actor]=self.by_actor.get(actor,0)+1
            self.calls[-1]['actor']=actor
        self.persist()
        return result


class StubWorkflowAdapter(RealAdapter):
    """Requires an in-process scripted sender. Not selectable from server settings."""
    def __init__(self, path, sender, *, cost_ceiling=0.11):
        if not isinstance(sender,WorkflowStub):raise TypeError('Only WorkflowStub is accepted')
        super().__init__(path,enabled=True,exclusive_ledger_owner=True,transport=sender)
        self.cost_ceiling=cost_ceiling

    def _make_budget(self, send):
        return StubBudget(send,self.path,cost_ceiling=self.cost_ceiling)

    def _network_send(self, body):
        raise RuntimeError('Network forbidden in Stub workflow')


class WorkflowStub:
    def __init__(self, *, retry_search=False, missing=False, repeat_reads=False, direct_financial=False):
        self.retry_search=retry_search;self.missing=missing;self.repeat_reads=repeat_reads
        self.direct_financial=direct_financial
        self.requests=[];self.counts={r:0 for r in CAPS}

    def __call__(self, body):
        role=next(m['content'].split(']',1)[0].split('=')[-1] for m in body['messages'] if m['role']=='user')
        self.counts[role]+=1;self.requests.append(body)
        step=self.counts[role]
        actions=[]
        financial=('opendart__read_financials',{'rp':{'corp_code':'00000001','bsns_year':'2025','reprt_code':'11011','fs_div':'CFS'},'op':{}})
        if role=='research' and self.direct_financial and step==1:
            actions=[financial]
        elif role=='research' and not self.direct_financial:
            if step<=int(self.retry_search)+1:
                query='no-matching-token' if step<=int(self.retry_search) else 'hydrogen'
                actions=[('openalex__search_works',{'rp':{'query':query},'op':{'limit':3}})]
            elif step==int(self.retry_search)+2 and not self.missing:
                actions=[('openalex__read_work',{'rp':{'work_id':'H-A01'},'op':{'include_abstract':True}})]
        if role=='verification' and not self.missing and (step==1 or (self.repeat_reads and step==2)):
            actions=[financial] if self.direct_financial else [('openalex__read_work',{'rp':{'work_id':'H-A01'},'op':{'include_abstract':True}})]
        message={'role':'assistant','content':'SYNTHETIC [H-F01] 기술별 수익성은 미확인입니다.' if self.direct_financial else 'SYNTHETIC [H-A01] 실험실 결과는 상업 성능을 보장하지 않는다.'}
        if actions:
            message={'role':'assistant','content':None,'tool_calls':[{'id':f'{role}-{step}-{i}','type':'function',
                'function':{'name':n,'arguments':json.dumps(a)}} for i,(n,a) in enumerate(actions)]}
        return 200,{'id':'workflow-stub','created':1,'model':'gpt-4o-mini','choices':[{'message':message,'finish_reason':'tool_calls' if actions else 'stop'}],
                   'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}}


def examples():
    """Ephemeral STUB ledgers only. Never uses or initializes an operating budget."""
    import tempfile
    from pathlib import Path
    from .application import ResearchApplication,principal
    results=[]
    scenarios=[('direct-financial',{'direct_financial':True},True,0.11),
               ('search-read',{},False,0.11),('one-search-retry',{'retry_search':True},False,0.11),
               ('bounded-expanded',{'retry_search':2,'repeat_reads':True},False,0.11),
               ('legacy-block',{},True,0.11),('missing-evidence',{'missing':True},False,0.11),
               ('cost-block',{},False,0)]
    for name,options,legacy,ceiling in scenarios:
        with tempfile.TemporaryDirectory(prefix='stub-research-') as directory:
            root=Path(directory);path=root/'usage.json'
            path.write_text(json.dumps({'calls':[],'failed':False}))
            sender=WorkflowStub(**options)
            adapter=RealAdapter(path,enabled=True,exclusive_ledger_owner=True,transport=sender) if legacy else StubWorkflowAdapter(path,sender,cost_ceiling=ceiling)
            result=ResearchApplication(root/'app',real_adapter=adapter).ask(principal('researcher'),'researcher',
                           '수소환원제철을 비교 조사해주세요.',execution_mode='real')
            results.append({'scenario':name,'transport':'stub-only','paid_budget_activated':False,
                            'calls_by_role':sender.counts,'request_roles':[next(m['content'].split(']',1)[0].split('=')[-1]
                                for m in body['messages'] if m['role']=='user') for body in sender.requests],
                            'complete':result['complete'],'progress':result['progress'],
                            'trace':result['trace'],'raw_stages':result['stages'],
                            'raw_tool_calls':[a['raw_tool_calls'] for a in result['real_audit']['audit']],
                            'report':result['answer']})
    return results


if __name__=='__main__':
    print(json.dumps(examples(),ensure_ascii=False,indent=2))
