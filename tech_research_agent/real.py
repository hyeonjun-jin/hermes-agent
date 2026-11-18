"""Explicit opt-in gateway. No network at import/construction; shared legacy limits."""
import copy
import hashlib
import json
import os
import uuid
from pathlib import Path
from contextlib import contextmanager
from persona_prototype.usage_lock import claim_usage_lock

from persona_prototype.web_backend import PersistentBudget, check_real_network
from persona_prototype.mini_validation import ENDPOINT, MODEL, RATES, gateway

PUBLIC_QUESTIONS = frozenset({'수소환원제철을 비교 조사해주세요.','NCM LFP 양극재를 비교 조사해주세요.'})


class RealBlocked(RuntimeError):
    pass


class PayloadPolicy:
    def __init__(self, corpus):
        self.public = {s['id']:s for s in corpus.values() if s['classification']=='PUBLIC' and s['synthetic']}
        self.private = {s['id'] for s in corpus.values() if s['classification']!='PUBLIC'}
        self.private |= {span['text'] for s in corpus.values() if s['classification']!='PUBLIC' for span in s['spans']}

    def check(self, payload):
        inspect_labels(payload,self.public)
        text=json.dumps(payload,ensure_ascii=False,sort_keys=True)
        if len(text.encode())>64000:
            raise RealBlocked('Payload size limit exceeded')
        if 'proj-' in text.casefold() or any(value.casefold() in text.casefold() for value in self.private):
            raise RealBlocked('Non-public information in outbound payload')
        key=os.environ.get('PERSONA_API_KEY','')
        if (key and key in text) or any(marker in text for marker in ('/workspace/','/home/','sk-proj-','sk-test-secret','PRIVATE_MEMORY')):
            raise RealBlocked('Private path, credential or Memory in outbound payload')
        # Inspect the actual serialized provider context, not only the top-level request.
        for message in payload.get('messages',[]):
            content=message.get('content','')
            if isinstance(content,str) and 'TECH_CONTEXT=' in content:
                context=json.JSONDecoder().raw_decode(content.split('TECH_CONTEXT=',1)[1])[0]
                inspect_labels(context,self.public)
                if context['environment']['classification']!='PUBLIC' or any(h.get('data_policy')!='PUBLIC_SYNTHETIC' for h in context['history']) or (context['approved_preferences'] and context['approved_preferences'].get('data_policy')!='PUBLIC_SYNTHETIC'):
                    raise RealBlocked('Only PUBLIC synthetic context can leave this application')
        return hashlib.sha256(text.encode()).hexdigest()


def inspect_labels(value, public=None):
    if isinstance(value,dict):
        level=value.get('classification')
        if (level is not None and not isinstance(level,dict) and level!='PUBLIC') or value.get('data_policy')=='PRIVATE' or value.get('synthetic') is False:
            raise RealBlocked('Non-public/non-synthetic data in outbound payload')
        if 'source_id' in value:
            source=(public or {}).get(value['source_id'])
            if not source or level!='PUBLIC' or value.get('synthetic') is not True or value.get('spans')!=source['spans']:
                raise RealBlocked('Unapproved source or modified original text')
        for child in value.values():
            inspect_labels(child,public)
    elif isinstance(value,list):
        for child in value:
            inspect_labels(child,public)
    elif isinstance(value,str) and value.lstrip().startswith(('{','[')):
        try:
            child=json.loads(value)
        except ValueError:
            return
        inspect_labels(child,public)


def public_context(context):
    """Allow only current synthetic server fixtures, never unclassified persisted Memory."""
    if context['environment']['classification']!='PUBLIC' or any(h.get('data_policy')!='PUBLIC_SYNTHETIC' for h in context['history']) or (context['approved_preferences'] and context['approved_preferences'].get('data_policy')!='PUBLIC_SYNTHETIC'):
        raise RealBlocked('Real mode blocks INTERNAL/RESTRICTED and unclassified Memory/preferences')
    if context['question'] not in PUBLIC_QUESTIONS:
        raise RealBlocked('Real v1 permits only the server-approved PUBLIC synthetic requests')
    value=copy.deepcopy(context)
    value['environment'].pop('project_id',None)
    value['environment']['public_project']=value['environment']['topic']
    for history in value['history']:
        history.pop('memory_id',None)
        history['question']=history['question'].split('] ',1)[-1]
    value['execution_mode']='real'
    return value


class ReservedBudget(PersistentBudget):
    def _send(self, body):
        # A byte upper bound is conservative for token reservation; this is not actual billing.
        self.calls[-1]['reserved_usd_upper_bound']=reservation_upper_bound(body)
        self.calls[-1]['payload_sha256']=self.payload_hash
        return super()._send(body)  # Durable pending attempt before any upstream send.


def reservation_upper_bound(body):
    return (len(json.dumps(body,ensure_ascii=False).encode())*0.15+512*0.60)/1_000_000


class RealAdapter:
    def __init__(self, usage_path, *, enabled=False, exclusive_ledger_owner=False, transport=None):
        self.path=Path(usage_path).resolve()
        self.enabled=enabled
        self.exclusive=exclusive_ledger_owner
        self.transport=transport
        self.role='research'
        self.system_prompt=None
        self.audit=[]
        self.budget=None
        self.start_attempts=0

    def preflight(self):
        if not self.enabled or not self.exclusive or self.path.name!='usage.json' or not self.path.is_file():
            raise RealBlocked('Explicit Real enablement and exclusive ownership of the EXISTING usage.json are required')
        saved=json.loads(self.path.read_text())
        self._check_saved_usage(saved)
        if self.transport is None:
            if not os.environ.get('PERSONA_API_KEY','').strip():
                raise RealBlocked('Server API key not configured; no attempt reserved')
            check_real_network(os.environ)

    def _check_saved_usage(self, saved):
        if saved.get('failed',True) or len(saved.get('calls',[]))>4:
            raise RealBlocked('Existing budget cannot reserve the 8-call workflow envelope; separate budget approval required')
        if any(c.get('status')=='pending' for c in saved['calls']):
            raise RealBlocked('Unresolved pending usage; manual reconciliation required, no budget reset')

    def _budget_case(self):
        return 'technical-'+uuid.uuid4().hex

    def _network_send(self, body):
        import httpx
        key=os.environ.get('PERSONA_API_KEY','').strip()
        if not key:
            raise RealBlocked('Server API key not configured')
        check_real_network(os.environ)
        with httpx.Client(timeout=20,follow_redirects=False,trust_env=False) as client:
            response=client.post(ENDPOINT+'/chat/completions',json=body,headers={'Authorization':'Bearer '+key})
        if key in response.text:
            raise RealBlocked('Credential-like upstream response rejected')
        return response.status_code,response.json() if response.status_code==200 else {}

    @contextmanager
    def endpoint(self, corpus):
        self.preflight()
        with claim_usage_lock(self.path):
            self.preflight()
            policy=self._payload_policy(corpus)
            adapter=self
            class Guard:
                def forward(self, body):
                    prepared=dict(body,model=MODEL,stream=False,max_tokens=512)
                    for key in ('stream_options','max_completion_tokens'):
                        prepared.pop(key,None)
                    prepared['messages']=copy.deepcopy(body['messages'])
                    if adapter.system_prompt is not None:
                        # Explicit public role prompt; host framework paths are never part of the external prompt.
                        prepared['messages']=[{'role':'system','content':adapter.system_prompt}]+[m for m in prepared['messages'] if m['role']!='system']
                    first=next(m for m in prepared['messages'] if m['role']=='user')
                    first['content']='[PERSONA_ROLE='+adapter.role+']\n'+str(first['content'])
                    try:
                        digest=policy.check(prepared)
                    except (RealBlocked,ValueError,KeyError,TypeError) as exc:
                        adapter.audit.append({'role':adapter.role,'status':'egress_denied','reason':str(exc) if isinstance(exc,RealBlocked) else 'Invalid context encoding'})
                        adapter.budget.failed=True
                        adapter.budget.persist()
                        return 403,{'error':{'message':'Outbound policy blocked; execution stopped'}}
                    adapter.budget.payload_hash=digest
                    before=len(adapter.budget.calls)
                    status,payload=adapter.budget.forward(prepared)
                    adapter.audit.append({'role':adapter.role,'status':status,'payload_sha256':digest,
                                          'budget_blocked':status==429 and len(adapter.budget.calls)==before,
                                          'reserved_attempt':len(adapter.budget.calls)>before,
                                          'block_reason':payload.get('error',{}).get('message') if status==429 and len(adapter.budget.calls)==before else None,
                                          'provenance':'context supplied; model explanations are not causal proof',
                                          'tool_result_ids':[m.get('tool_call_id') for m in prepared['messages'] if m['role']=='tool'],
                                          'raw_tool_calls':copy.deepcopy(payload.get('choices',[{}])[0].get('message',{}).get('tool_calls',[]))})
                    return status,payload
            def safe_send(body):
                if hasattr(policy,'before_send'):
                    policy.before_send(body)
                status,payload=(self.transport or self._network_send)(body)
                if status==200:
                    if not payload.get('choices') or not isinstance(payload['choices'][0].get('message'),dict):
                        raise RealBlocked('Invalid upstream response shape')
                    policy.check({'messages':[{'role':'assistant','content':json.dumps(payload,ensure_ascii=False)}]})
                    if hasattr(policy,'remember_response'):
                        policy.remember_response(payload)
                return status,payload
            self.budget=self._make_budget(safe_send)
            self.budget.case=self._budget_case()
            self.start_attempts=len(self.budget.calls)
            self.audit=[]
            # Reconstruct persisted per-role accounting; fresh instance cannot reset role limits.
            self.budget.by_actor={}
            for call in self.budget.calls:
                actor=call.get('actor','')
                self.budget.by_actor[actor]=self.budget.by_actor.get(actor,0)+1
            with gateway(Guard()) as url:
                yield url

    def _make_budget(self, send):
        return ReservedBudget(send,self.path)

    def _payload_policy(self, corpus):
        return PayloadPolicy(corpus)

    def summary(self):
        return {'model':MODEL,'transport_mode':'stub' if self.transport is not None else 'openai','pricing':RATES,'audit':self.audit,
                'totals':self.budget.totals() if self.budget else None,
                'this_run_attempts':len(self.budget.calls)-self.start_attempts if self.budget else 0,
                'reserved_usd_upper_bound':sum(c.get('reserved_usd_upper_bound',0) for c in self.budget.calls[self.start_attempts:]) if self.budget else 0,
                'limitation':'Legacy specialist cap is 2; search/read/final may require separate budget approval'}
