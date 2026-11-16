"""Scripted model fixture. Decisions here are not evidence of learned personalization."""
import json


def tool_calls(entries):
    return {'role':'assistant','content':None,'tool_calls':[
        {'id':f'tech-{i}','type':'function','function':{'name':name,'arguments':json.dumps(args,ensure_ascii=False)}}
        for i,(name,args) in enumerate(entries)]},'tool_calls'


def search_plan(context):
    env=context['environment'];topic=env['topic'];q='hydrogen 수소환원제철' if topic=='H' else 'NCM LFP 양극재'
    focus=context['profile']['focus']
    approved=context['approved_preferences'].get('source_focus')
    if approved:
        focus=approved
    if '논문만' in context['question']:
        focus='papers_only'
    elif '재무 중심' in context['question']:
        focus='finance'
    params={'from_date':'2025-10-01' if env['depth']=='quick' else '2022-01-01',
            'to_date':env['cutoff'],'sort':'date_desc' if env['depth']=='quick' else 'relevance',
            'limit':3 if env['depth']=='quick' else 5}
    if env['depth']=='restricted':
        return [('internal_mock__search_documents',{'rp':{'query':q,'project_id':env['project_id']},
                  'op':{'evidence_kind':{'science':'experiment','papers_only':'experiment','strategy':'strategy','finance':'financial'}[focus],
                        'sort':'date_desc','limit':3}})]
    plans=[]
    company=next((item['corp_code'] for item in context.get('entity_catalog',[])),None)
    if focus in ('science','papers_only'):
        plans.append(('openalex__search_works',{'rp':{'query':q+' 실험 조건'},'op':{**params,'types':['article','review']}}))
        if focus=='science':
            plans.append(('kipris_plus__search_patents',{'rp':{'query':q,'jurisdiction':'KR'},'op':params}))
    elif focus=='strategy':
        plans=[('opendart__list_disclosures',{'rp':{'corp_code':company,
                 'from_date':params['from_date'],'to_date':params['to_date']},'op':{'report_type':'material','keyword':q,'limit':params['limit']}}),
               ('posco_ir__search_materials',{'rp':{'query':q},'op':{**params,'kind':'strategy','language':'ko'}})]
    else:
        plans=[('opendart__read_financials',{'rp':{'corp_code':company,'bsns_year':'2025','reprt_code':'11011','fs_div':'CFS'},
                 'op':{'account_ids':['cash_flow_investing','operating_profit']}}),
               ('posco_ir__search_materials',{'rp':{'query':q},'op':{**params,'kind':'earnings','language':'ko'}})]
    if env['depth']=='deep' and focus!='papers_only':
        plans.append(('internal_mock__search_documents',{'rp':{'query':q,'project_id':env['project_id']},
                      'op':{**params,'evidence_kind':{'science':'experiment','strategy':'strategy','finance':'financial'}[focus]}}))
    return [(n,a) for n,a in plans if n.split('__')[0] in env['allowed_sources'] and
            (n.split('__')[0]!='opendart' or company is not None)]


def reads(items):
    mapping={'openalex':('read_work','work_id',{'include_abstract':True}),
             'kipris_plus':('read_patent','application_id',{'include_claims':True}),
             'opendart':('read_disclosure','receipt_no',{}),
             'posco_ir':('read_material','material_id',{}),'internal_mock':('read_document','document_id',{})}
    result=[]
    for item in items:
        if item.get('financial_request'):
            result.append(('opendart__read_financials',{'rp':item['financial_request'],
                           'op':{'account_ids':sorted({row['account_id'] for row in item['rows']})}}))
            continue
        if item['origin_app']=='opendart' and item['source_id'].rsplit('-',1)[-1]=='F01':
            continue  # Financial API already returns original rows.
        api,key,op=mapping[item['origin_app']]
        result.append((item['origin_app']+'__'+api,{'rp':{key:item['source_id']},'op':op}))
    return result


def respond(messages):
    marker=next(m['content'].split('TECH_CONTEXT=',1)[1] for m in messages if m['role']=='system' and 'TECH_CONTEXT=' in str(m['content']))
    ctx=json.JSONDecoder().raw_decode(marker)[0];role=ctx['role']
    results=[json.loads(m['content']) for m in messages if m['role']=='tool']
    if role=='research' and not results:
        plan=search_plan(ctx)
        if plan:
            return tool_calls(plan)
    if role=='research' and results and not any('__read_' in t['function']['name'] for m in messages if m['role']=='assistant' for t in m.get('tool_calls',[]) if t['function']['name']!='opendart__read_financials'):
        plan=reads([r['items'][0] for r in results if r.get('items') and not r['items'][0].get('financial_request')])
        if plan:
            return tool_calls(plan)
    if role=='verification' and not results:
        plan=reads(ctx['evidence'])
        if plan:
            return tool_calls(plan)
    items=ctx.get('evidence',[]) if role!='research' else [i for r in results for i in r.get('items',[])]
    text=(ctx.get('data_label','SYNTHETIC')+' / Mock — '+role+'\n판단 기준: '+ctx['profile']['criteria']+'\n')
    if role=='analysis':
        alternatives='유동층과 샤프트로' if ctx['environment']['topic']=='H' else '고니켈 NCM과 LFP'
        text+='비교 대상: '+alternatives+'. 실험 조건·공개 계획·연결 실적은 증거의 성격이 다르므로 직접적인 우열/수익성 결론을 보류합니다.\n'
    if role=='verification':
        text+='원문 재조회 및 분석 초안 대조: '+json.dumps(ctx.get('verification_audit',{}),ensure_ascii=False)+'\n'
    text+='\n'.join('['+i['source_id']+'] '+' '.join(s['text'] for s in i['spans']) for i in items)
    text+='\n미확인: 실제 기술 우열·상업 성능·시장 규모·기술별 ROI는 확정하지 않습니다. 현재 Environment 기준 조사이며 이전 이력은 현재 사실의 근거가 아닙니다.'
    return {'role':'assistant','content':text},'stop'
