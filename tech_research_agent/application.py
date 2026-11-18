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
from .config import runtime, PROFILES, entity_catalog, source_label
from .provider import ResearchProvider
from .mock import respond
from .audit import review
from .progress import progress
from .source_adapter import source_issues, source_limit_text, is_original_evidence
from .persona_store import ResearchPersonaStore
from .persona_alignment import ResearchPreferenceAligner
from .persona_preferences import memory_record, combine, resolve
from .paper_fixtures import paper_request, fixture_adapter
from .paper_recommendations import recommend_from_trace

SCOPES=frozenset({'memory:read','memory:write','persona:read','persona:propose','persona:approve','persona:rollback'})


class ResearchApplication:
    def __init__(self, root, *, real_adapter=None, source_connectors=None, public_real_adapter=None):
        self.real_adapter=real_adapter
        self.public_real_adapter=public_real_adapter
        self.source_connectors=dict(source_connectors or {})
        self.root=Path(root)
        self.store=MemoryStore(self.root/'memory.sqlite',OwnerOnly())
        self.lock=threading.RLock()
        self.personas=ResearchPersonaStore(self.store,self._project_access)
        self.aligner=ResearchPreferenceAligner(self.personas)

    def _project_access(self, actor, project):
        if project not in {'proj-H','proj-B'}:
            return False
        _,_,adapter=runtime(actor.user_id,project[-1],'quick',connectors=self.source_connectors)
        return project in adapter.context.allowed_projects

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
            if execution_mode not in ('mock','real','approved_public'):
                raise ValueError('Unknown model mode')
            if execution_mode=='real' and self.source_connectors:
                raise PermissionError('공개 Connector 자료의 외부 LLM 반출은 아직 승인되지 않았습니다. 기존 Real 합성 데이터 제한을 유지합니다.')
            if execution_mode=='real' and self.real_adapter is None:
                raise RuntimeError('Real mode requires server configuration of the existing usage ledger')
            if execution_mode=='approved_public' and (self.public_real_adapter is None or not self.source_connectors):
                raise PermissionError('승인 공개자료 경로에는 서버 전용 Adapter와 Connector 설정이 필요합니다.')
            return self._ask(actor,user_id,question,topic,mode,execution_mode)

    def _ask(self, actor, user_id, question, topic, mode, execution_mode):
        profile,environment,adapter=runtime(user_id,topic,mode,connectors=self.source_connectors)
        if execution_mode == 'mock' and not self.source_connectors and paper_request(question):
            adapter = fixture_adapter(adapter, environment)
        persona_version=self.personas.current(actor,environment['project_id'])
        persona_memory=memory_record(persona_version)
        real_adapter=self.public_real_adapter if execution_mode=='approved_public' else self.real_adapter
        is_real=execution_mode!='mock'
        public_policy=real_adapter.prepare(adapter) if execution_mode=='approved_public' else None
        opposite=('NCM','LFP','양극재','이차전지') if topic=='H' else ('수소환원','제철','샤프트로','유동층')
        if any(word in question for word in opposite):
            return {'mode':execution_mode,'persona':profile,'environment':environment,'stages':[], 'trace':[],
                    'evidence':[],'model_calls':0,'tool_cost':0,'answer':'선택한 프로젝트와 질문 주제가 다릅니다. 프로젝트를 변경하거나 조사 범위를 명확히 해주세요.','complete':False}
        approved=self.store.semantic(actor,user_id)
        approved=approved if approved.get('explicitly_approved') else {}
        history=[{'memory_id':r['id'],'question':r['query'],'summary':r['response'][:500],'data_policy':'PUBLIC_SYNTHETIC' if r['response'].startswith('[PUBLIC_SYNTHETIC_RESEARCH]') else 'PRIVATE'} for r in
                 self.store.search(actor,user_id,question,project_id=environment['project_id'])
                 if all(sid in adapter.corpus and adapter.context.permits(adapter.corpus[sid])
                         for sid in re.findall(r'\[([HB]-[\w-]+)\]',r['response']))]
        if public_policy is not None:
            from .approved_memory import load_memory
            approved,history=load_memory(self.store,actor,user_id,question,environment,public_policy,
                persona_record=persona_memory,persona_reader=lambda:memory_record(self.personas.current(actor,environment['project_id'])))
        else:
            approved=combine(approved,persona_memory)
        approved,guidance=resolve(approved,environment,question,profile)
        if public_policy is None and self.source_connectors and (approved.get('data_policy') == 'PRIVATE' or
                                       any(h['data_policy'] == 'PRIVATE' for h in history)):
            raise PermissionError('공개 Connector 실행에는 비공개 Memory를 함께 사용할 수 없습니다.')
        data_label = source_label(self.source_connectors)
        stages=[];evidence=[];requests=[]
        home=self.root/'homes'/user_id
        home.mkdir(parents=True,exist_ok=True)
        ensure_runtime_config(home,limited=True,multi_agent=False)
        def observe(request):
            if len(requests)>=12:
                raise RuntimeError('Local Mock model-call budget exhausted')
            requests.append({'role':role,'model':request['model'],'tool_names':[t['function']['name'] for t in request.get('tools',[])]})
        with bind_profile_scope(home,hydrate_secrets=False):
            from run_agent import AIAgent
            with self._endpoint(execution_mode,adapter.corpus,observe,real_adapter) as endpoint:
                for role in ('research','analysis','verification'):
                    context={'data_label':data_label,'role':role,'profile':profile,'environment':environment,'question':question,
                             'persona_revision':persona_version['revision'],
                             'persona_guidance':guidance,
                             'approved_preferences':approved,'history':history,'evidence':evidence,
                             'previous_stages':stages,'retrieval_limits':source_issues(adapter.trace),
                             'entity_catalog':entity_catalog(adapter),
                             'verification_audit':review(stages[-1]['raw_answer'],evidence) if stages else {}}
                    if is_real:
                        from .real import public_context
                        context=public_policy.context(context) if public_policy is not None else public_context(context)
                        real_adapter.role=role
                    if not adapter.context.authorize_llm('local',[item['source_id'] for item in evidence],adapter.corpus):
                        raise PermissionError('현재 근거를 이 모델 경로로 전달할 수 없습니다.')
                    manager=MemoryManager()
                    provider=ResearchProvider(role,adapter,context)
                    provider.audit_memory_ids=[h['memory_id'] for h in history]
                    if is_real:
                        real_adapter.system_prompt=provider.system_prompt_block()
                    manager.add_provider(provider)
                    manager.initialize_all(session_id=uuid.uuid4().hex,hermes_home=str(home),agent_context='primary')
                    agent=None
                    try:
                        agent=AIAgent(base_url=endpoint,api_key='local-mock-only',model='gpt-4o-mini' if is_real else 'technical-research-mock',
                                      provider='openai',api_mode='chat_completions',memory_manager=manager,
                                      enabled_toolsets=['memory'],skip_context_files=True,skip_background_review=True,
                                      quiet_mode=True,max_iterations=6,max_tokens=512 if is_real else 1024,run_budget_seconds=60,save_trajectories=False)
                        allowed={s['name'] for s in provider.get_tool_schemas()}
                        agent.tools=[t for t in agent.tools if t['function']['name'] in allowed]
                        agent.valid_tool_names=allowed
                        if public_policy is not None:
                            import copy
                            public_policy.expected_tools=copy.deepcopy(agent.tools)
                        result=agent.run_conversation(question)
                    finally:
                        if agent is not None:
                            agent.close()
                        manager.shutdown_all()
                    error=bool(result.get('error') or result.get('failed') or result.get('partial') or (is_real and real_adapter.budget.failed))
                    stages.append({'role':role,'raw_answer':result['final_response'],'error':error})
                    # Only successful original reads, not search snippets, become report evidence.
                    original={i['source_id']:i for e in adapter.trace if e['executed'] and
                              e['plan']['api'].startswith('read_') and e['result']['status'] in ('ok','partial')
                              and e.get('egress_policy',{}).get('status','approved')=='approved'
                              for i in e['result'].get('items',[]) if adapter.context.permits(adapter.corpus[i['source_id']]) and is_original_evidence(i)}
                    evidence=list(original.values())
                    if error:
                        break
        # Mechanical citation/number audit; semantic conclusions still require human review.
        checks={'original_ids':[i['source_id'] for i in evidence],
                'policy_denials':[e['reason'] for e in adapter.trace if not e['executed']],
                'human_review_required':True,'synthetic':not bool(self.source_connectors),
                'data_label':data_label,
                'analysis_audit':review(stages[1]['raw_answer'],evidence) if len(stages)>1 else {},
                'verification_audit':review(stages[-1]['raw_answer'],evidence) if stages else {}}
        verification_read=any(e['plan']['id'].startswith('verification-') and e['plan']['api'].startswith('read_') and e['executed'] and e['result']['status']=='ok' for e in adapter.trace)
        checks['verification_read']=verification_read
        checks['incomplete_reads']=[e['plan']['id'] for e in adapter.trace if e['plan']['api'].startswith('read_') and e['result']['status']=='partial']
        checks['source_failures']=[issue for issue in source_issues(adapter.trace) if issue['status'] in {'denied','unavailable'}]
        checks['metadata_only_ids']=[i['source_id'] for i in evidence if i.get('evidence_coverage')=='metadata_only']
        checks['unverified_original_ids']=[i['source_id'] for i in evidence if i.get('original_verified') is False]
        complete=(not is_real or verification_read) and len(stages)==3 and not any(s['error'] for s in stages) and bool(evidence) and not checks['source_failures'] and not checks['incomplete_reads'] and not checks['metadata_only_ids'] and not checks['unverified_original_ids'] and not checks['policy_denials'] and not checks['analysis_audit'].get('unknown_citations') and not checks['analysis_audit'].get('unmatched_numeric_tokens') and not checks['verification_audit'].get('unknown_citations') and not checks['verification_audit'].get('unmatched_numeric_tokens')
        answer='## 기술조사 보고서 ('+data_label+' / '+execution_mode+')\n조사 목적: '+environment['purpose']+'\n기준일: '+environment['as_of']+' / 마감: '+environment['deadline']+' / 보고 대상: '+environment['audience']+'\n'+ '\n'.join('### '+s['role']+'\n'+(s['raw_answer'] if not s['error'] else '이 역할은 실행 한도·정책·통신 오류로 중단됐습니다. 원응답은 감사 기록에 보존하며 자동 재시도나 모델 전환을 하지 않습니다.') for s in stages)
        if source_issues(adapter.trace):
            answer+='\n조회 범위·실행 제한: '+source_limit_text(adapter.trace)
        if not complete:
            answer+='\n조사 미완료: 근거·실행 상태를 확인해 주세요.'
            if is_real and any(a.get('budget_blocked') for a in real_adapter.audit):
                reason=next((a.get('block_reason') or '' for a in reversed(real_adapter.audit) if a.get('budget_blocked')),'')
                boundary='비용 예약 상한' if 'cost' in reason.lower() else '기존 API/역할 호출 한도'
                answer+='\n'+boundary+'로 중단했습니다. 예산을 초기화하지 않았으며, 완주에는 별도 예산 승인이 필요합니다.'
        progress_audit=real_adapter.audit if is_real else [{'role':r['role'],'status':200,'reserved_attempt':True} for r in requests]
        execution_progress=progress(stages,adapter.trace,progress_audit)
        if not complete:
            answer+='\n현재 단계: '+str(execution_progress['stopped_role'] or 'verification')+' / 역할별 사용 호출: '+str(execution_progress['calls_by_role'])+'\n남은 작업: '+', '.join(execution_progress['remaining_work'])
        stored_answer=('[PUBLIC_SYNTHETIC_RESEARCH] ' if execution_mode=='real' and not any(a.get('status')=='egress_denied' for a in real_adapter.audit) else '')+answer
        self.store.append(actor,user_id,'technical-research','[project='+environment['project_id']+'] '+question,stored_answer)
        output={'mode':execution_mode,'real_audit':real_adapter.summary() if is_real else None,'persona':{**profile,'version':persona_version['revision'],'approved_preferences':approved},'environment':environment,
                'question':question,'persona_revision':persona_version['revision'],
                'history_used':history,'input_snapshot':{'profile':profile,'environment':environment,'approved_preferences':approved,'history':history,
                    'persona_revision':persona_version['revision'],'persona_guidance':guidance},
                'stages':stages,'trace':adapter.trace,'evidence':evidence,'answer':answer,
                'progress':execution_progress,'complete':complete,'checks':checks,'model_calls':real_adapter.summary()['this_run_attempts'] if is_real else len(requests),'tool_cost':adapter.context.spent}
        # Ranking uses approved PRIVATE preferences locally, after all model exchanges; never add them to wire context.
        output['paper_recommendations'] = recommend_from_trace(adapter, profile, combine({}, persona_memory), environment, question)
        output['alignment_turn_id']=self.personas.record_turn(actor,environment['project_id'],output)
        return output

    @contextmanager
    def _endpoint(self, mode, corpus, observe, real_adapter=None):
        if mode=='mock':
            with mock_endpoint(respond,request_observer=observe) as url:
                yield url
        else:
            with (real_adapter or self.real_adapter).endpoint(corpus) as url:
                yield url


def principal(user_id):
    return Principal(user_id,SCOPES)
