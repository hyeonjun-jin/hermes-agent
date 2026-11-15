"""Three Hermes AIAgents coordinated over a shared, policy-checked evidence ledger."""
from contextlib import contextmanager
import threading
import re
import uuid
from pathlib import Path
from agent.memory_manager import MemoryManager
from agent.runtime_scope import bind_profile_scope
from persona_prototype.domain import OwnerOnly, Principal
from persona_prototype.store import MemoryStore
from persona_prototype.runtime_config import ensure_runtime_config
from persona_prototype.mock_llm import mock_endpoint
from .config import runtime, PROFILES
from .provider import ResearchProvider
from .mock import respond
from .audit import review

SCOPES=frozenset({'memory:read','memory:write'})


class ResearchApplication:
    def __init__(self, root, *, real_adapter=None):
        self.real_adapter=real_adapter
        self.root=Path(root)
        self.store=MemoryStore(self.root/'memory.sqlite',OwnerOnly())
        self.lock=threading.RLock()

    def approve(self, actor, preference, *, public_synthetic=False):
        if actor.user_id not in PROFILES or preference not in ('science','strategy','finance','papers_only'):
            raise ValueError('Unsupported approved preference')
        self.store.save_semantic(actor,actor.user_id,{'source_focus':preference,'explicitly_approved':True,'data_policy':'PUBLIC_SYNTHETIC' if public_synthetic else 'PRIVATE'})

    def ask(self, actor, user_id, question, *, topic='H', mode='quick', execution_mode='mock'):
        self.store.authorizer.require(actor,user_id,'memory:read')
        self.store.authorizer.require(actor,user_id,'memory:write')
        if not question.strip() or len(question)>4000:
            raise ValueError('질문은 1~4000자로 입력하세요.')
        with self.lock:
            if execution_mode not in ('mock','real'):
                raise ValueError('Unknown model mode')
            if execution_mode=='real' and self.real_adapter is None:
                raise RuntimeError('Real mode requires server configuration of the existing usage ledger')
            return self._ask(actor,user_id,question,topic,mode,execution_mode)

    def _ask(self, actor, user_id, question, topic, mode, execution_mode):
        profile,environment,adapter=runtime(user_id,topic,mode)
        opposite=('NCM','LFP','양극재','이차전지') if topic=='H' else ('수소환원','제철','샤프트로','유동층')
        if any(word in question for word in opposite):
            return {'mode':execution_mode,'persona':profile,'environment':environment,'stages':[], 'trace':[],
                    'evidence':[],'model_calls':0,'tool_cost':0,'answer':'선택한 프로젝트와 질문 주제가 다릅니다. 프로젝트를 변경하거나 조사 범위를 명확히 해주세요.','complete':False}
        approved=self.store.semantic(actor,user_id)
        approved=approved if approved.get('explicitly_approved') else {}
        history=[{'memory_id':r['id'],'question':r['query'],'summary':r['response'][:500],'data_policy':'PUBLIC_SYNTHETIC' if r['response'].startswith('[PUBLIC_SYNTHETIC_RESEARCH]') else 'PRIVATE'} for r in
                 self.store.search(actor,user_id,question) if r['query'].startswith('[project='+environment['project_id']+']')
                 and all(sid in adapter.corpus and adapter.context.permits(adapter.corpus[sid])
                         for sid in re.findall(r'\[([HB]-[\w-]+)\]',r['response']))]
        stages=[];evidence=[];requests=[]
        home=self.root/'homes'/user_id
        home.mkdir(parents=True,exist_ok=True)
        ensure_runtime_config(home,limited=True,multi_agent=False)
        def observe(request):
            if len(requests)>=12:
                raise RuntimeError('Local Mock model-call budget exhausted')
            requests.append({'model':request['model'],'tool_names':[t['function']['name'] for t in request.get('tools',[])]})
        with bind_profile_scope(home,hydrate_secrets=False):
            from run_agent import AIAgent
            with self._endpoint(execution_mode,adapter.corpus,observe) as endpoint:
                for role in ('research','analysis','verification'):
                    context={'role':role,'profile':profile,'environment':environment,'question':question,
                             'approved_preferences':approved,'history':history,'evidence':evidence,
                             'previous_stages':stages,
                             'entity_catalog':[{'corp_code':code,'public_topic':value,'synthetic':True,'classification':'PUBLIC'} for code,value in adapter.context.entity_topics.items()],
                             'verification_audit':review(stages[-1]['raw_answer'],evidence) if stages else {}}
                    if execution_mode=='real':
                        from .real import public_context
                        context=public_context(context)
                        self.real_adapter.role=role
                    if not adapter.context.authorize_llm('local',[item['source_id'] for item in evidence],adapter.corpus):
                        raise PermissionError('현재 근거를 이 모델 경로로 전달할 수 없습니다.')
                    manager=MemoryManager()
                    provider=ResearchProvider(role,adapter,context)
                    provider.audit_memory_ids=[h['memory_id'] for h in history]
                    if execution_mode=='real':
                        self.real_adapter.system_prompt=provider.system_prompt_block()
                    manager.add_provider(provider)
                    manager.initialize_all(session_id=uuid.uuid4().hex,hermes_home=str(home),agent_context='primary')
                    agent=None
                    try:
                        agent=AIAgent(base_url=endpoint,api_key='local-mock-only',model='gpt-4o-mini' if execution_mode=='real' else 'technical-research-mock',
                                      provider='openai',api_mode='chat_completions',memory_manager=manager,
                                      enabled_toolsets=['memory'],skip_context_files=True,skip_background_review=True,
                                      quiet_mode=True,max_iterations=6,max_tokens=512 if execution_mode=='real' else 1024,run_budget_seconds=60,save_trajectories=False)
                        allowed={s['name'] for s in provider.get_tool_schemas()}
                        agent.tools=[t for t in agent.tools if t['function']['name'] in allowed]
                        agent.valid_tool_names=allowed
                        result=agent.run_conversation(question)
                    finally:
                        if agent is not None:
                            agent.close()
                        manager.shutdown_all()
                    error=bool(result.get('error') or result.get('failed') or result.get('partial') or (execution_mode=='real' and self.real_adapter.budget.failed))
                    stages.append({'role':role,'raw_answer':result['final_response'],'error':error})
                    # Only successful original reads, not search snippets, become report evidence.
                    original={i['source_id']:i for e in adapter.trace if e['executed'] and
                              e['plan']['api'].startswith('read_') and e['result']['status'] in ('ok','partial')
                              for i in e['result'].get('items',[]) if adapter.context.permits(adapter.corpus[i['source_id']])}
                    evidence=list(original.values())
                    if error:
                        break
        # Mechanical citation/number audit; semantic conclusions still require human review.
        checks={'original_ids':[i['source_id'] for i in evidence],
                'policy_denials':[e['reason'] for e in adapter.trace if not e['executed']],
                'human_review_required':True,'synthetic':True,
                'analysis_audit':review(stages[1]['raw_answer'],evidence) if len(stages)>1 else {},
                'verification_audit':review(stages[-1]['raw_answer'],evidence) if stages else {}}
        complete=len(stages)==3 and not any(s['error'] for s in stages) and bool(evidence) and not checks['policy_denials'] and not checks['analysis_audit'].get('unknown_citations') and not checks['analysis_audit'].get('unmatched_numeric_tokens') and not checks['verification_audit'].get('unknown_citations') and not checks['verification_audit'].get('unmatched_numeric_tokens')
        answer='## 기술조사 보고서 (SYNTHETIC / '+execution_mode+')\n조사 목적: '+environment['purpose']+'\n기준일: '+environment['as_of']+' / 마감: '+environment['deadline']+' / 보고 대상: '+environment['audience']+'\n'+ '\n'.join('### '+s['role']+'\n'+s['raw_answer'] for s in stages)
        if not complete:
            answer+='\n조사 미완료: 근거·실행 상태를 확인해 주세요.'
            if execution_mode=='real' and any(a.get('budget_blocked') for a in self.real_adapter.audit):
                answer+='\n기존 API/역할 호출 한도로 중단했습니다. 예산을 초기화하지 않았으며, 완주에는 별도 예산 승인이 필요합니다.'
        stored_answer=('[PUBLIC_SYNTHETIC_RESEARCH] ' if execution_mode=='real' and not any(a.get('status')=='egress_denied' for a in self.real_adapter.audit) else '')+answer
        self.store.append(actor,user_id,'technical-research','[project='+environment['project_id']+'] '+question,stored_answer)
        return {'mode':execution_mode,'real_audit':self.real_adapter.summary() if execution_mode=='real' else None,'persona':{**profile,'approved_preferences':approved},'environment':environment,
                'history_used':history,'input_snapshot':{'profile':profile,'environment':environment,'approved_preferences':approved,'history':history},'stages':stages,'trace':adapter.trace,'evidence':evidence,'answer':answer,
                'complete':complete,'checks':checks,'model_calls':self.real_adapter.summary()['this_run_attempts'] if execution_mode=='real' else len(requests),'tool_cost':adapter.context.spent}

    @contextmanager
    def _endpoint(self, mode, corpus, observe):
        if mode=='mock':
            with mock_endpoint(respond,request_observer=observe) as url:
                yield url
        else:
            with self.real_adapter.endpoint(corpus) as url:
                yield url


def principal(user_id):
    return Principal(user_id,SCOPES)
