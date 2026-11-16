"""Streamlit development UI; every model endpoint is an internally created loopback Mock."""
from pathlib import Path
import streamlit as st
from tech_research_agent.application import ResearchApplication, principal
from tech_research_agent.config import PROFILES, runtime, source_label, entity_catalog
from persona_prototype.ui_output import render_answer

st.set_page_config(page_title='개인화 기술조사',layout='wide')
st.title('개인화 기술조사 Agent')
st.caption('합성 업무 환경 기준일: 2026-10-01. 실제 현재 업무 정보가 아닙니다.')
st.warning('개발 전용 사용자 선택입니다. 실제 SSO 인증이 아닙니다. 기본 정보원은 SYNTHETIC이며 공개 Connector 설정은 서버에서만 변경합니다.')


@st.cache_resource
def application():
    app=ResearchApplication(Path.cwd()/'.technical-research-state')
    try:
        settings=st.secrets['technical_research_real']
    except (KeyError,FileNotFoundError):
        settings={}
    if settings:
        from tech_research_agent.real import RealAdapter
        app.real_adapter=RealAdapter(settings['usage_path'],enabled=settings.get('enabled',False),
                                     exclusive_ledger_owner=settings.get('exclusive_ledger_owner',False))
    try:
        sources=st.secrets['technical_research_sources']
    except (KeyError,FileNotFoundError):
        sources={}
    if sources.get('openalex_enabled',False):
        from tech_research_agent.connectors.openalex import OpenAlexConnector
        app.source_connectors={'openalex':OpenAlexConnector(enabled=True,api_key=sources.get('openalex_api_key'))}
    if sources.get('opendart_enabled',False):
        from tech_research_agent.connectors.opendart import OpenDARTConnector
        app.source_connectors['opendart']=OpenDARTConnector(enabled=True,api_key=sources.get('opendart_api_key'),
                                                         company_catalog=dict(sources.get('opendart_companies',{})))
    if sources.get('kipris_enabled',False):
        from tech_research_agent.connectors.kipris_plus import KIPRISPlusConnector
        app.source_connectors['kipris_plus']=KIPRISPlusConnector(enabled=True,
            service_approved=sources.get('kipris_service_approved',False),api_key=sources.get('kipris_api_key'))
    if sources.get('posco_ir_enabled',False):
        import json
        from tech_research_agent.connectors.posco_ir import POSCOIRConnector
        entries=json.loads(Path(sources['posco_ir_catalog_path']).read_text())
        app.source_connectors['posco_ir']=POSCOIRConnector(enabled=True,catalog=entries,
            local_root=sources.get('posco_ir_local_root'),allow_downloads=sources.get('posco_ir_allow_downloads',False),
            pdf_python=sources.get('posco_ir_pdf_python'))
    try:
        processing=st.secrets['technical_research_public_processing']
    except (KeyError,FileNotFoundError):
        processing={}
    if processing.get('enabled',False):
        import json
        from tech_research_agent.approvals import ApprovalRegistry
        from tech_research_agent.approved_real import ApprovedPublicAdapter
        grants=ApprovalRegistry(json.loads(Path(processing['approval_registry_path']).read_text()))
        # The same existing ledger and lock as legacy Real; no separate paid budget is created.
        app.public_real_adapter=ApprovedPublicAdapter(settings['usage_path'],approvals=grants,
            public_processing_enabled=True,enabled=settings.get('enabled',False),
            max_reserved_usd=processing.get('max_reserved_usd',0),
            exclusive_ledger_owner=settings.get('exclusive_ledger_owner',False))
    return app


app=application()
st.caption('정보원: '+source_label(app.source_connectors) if app.source_connectors else '정보원: Offline SYNTHETIC (외부 검색 없음)')
user=st.sidebar.selectbox('사용자',list(PROFILES),format_func=lambda u:PROFILES[u]['department']+' / '+PROFILES[u]['job'])
topic=st.sidebar.selectbox('현재 프로젝트',['H','B'],format_func=lambda t:'수소환원제철' if t=='H' else '이차전지 양극재')
mode=st.sidebar.selectbox('현재 환경',['quick','deep','restricted'])
execution_mode=st.sidebar.radio('모델 실행 모드',['mock','real','approved_public'],index=0)
real_ready=True
if execution_mode=='real':
    st.warning('Real은 GPT-4o mini의 실제 비용이 발생할 수 있습니다. PUBLIC 합성 요청만 허용합니다.')
    st.caption('현재 허용 요청: 수소환원제철을 비교 조사해주세요. / NCM LFP 양극재를 비교 조사해주세요.')
    consent=st.sidebar.checkbox('PUBLIC 합성 데이터 전송과 비용 발생 가능성을 확인했습니다')
    real_ready=bool(consent and app.real_adapter and app.real_adapter.enabled and not app.source_connectors)
    if app.source_connectors:
        st.info("공개 Connector와 Real의 동시 사용은 반출 승인 전까지 차단됩니다.")
    if not app.real_adapter:
        st.info('서버에 기존 usage.json의 소유권과 Real 활성화 설정이 필요합니다. 새 예산은 생성하지 않습니다.')
elif execution_mode=='approved_public':
    st.warning('승인 공개자료 모드: 외부 모델 처리와 실제 비용이 발생할 수 있습니다. 문서·Memory 승인은 서버에서만 관리합니다.')
    consent=st.sidebar.checkbox('서버 승인 범위의 외부 처리와 기존 비용 한도를 확인했습니다')
    configured=app.public_real_adapter
    real_ready=bool(consent and configured and configured.enabled and configured.public_processing_enabled and
                    configured.max_reserved_usd>0 and configured.approvals.configured and app.source_connectors)
    st.caption('기존 두 공개 합성 질문 제한을 유지합니다. UI 동의는 문서 반출 승인이나 예산 승인이 아닙니다.')
    if not real_ready:
        st.info('별도 관리자 opt-in·문서별 승인·기존 Real 원장 설정이 필요합니다. 현재 UI에서 이를 승인할 수 없습니다.')
else:
    st.info('Mock 실행: 스크립트형 응답이며 실제 모델의 개인화 판단 검증이 아닙니다.')
profile,env,_=runtime(user,topic,mode)
with st.sidebar.expander('현재 Persona와 승인 선호',expanded=True):
    st.json({**profile,'approved_preferences':app.store.semantic(principal(user),user)})
with st.sidebar.expander('현재 Environment'):
    st.json(env)
if 'opendart' in app.source_connectors:
    with st.sidebar.expander('서버가 허용한 회사 Catalog'):
        st.json(entity_catalog(runtime(user,topic,mode,connectors=app.source_connectors)[2]))
if 'research_threads' not in st.session_state:
    st.session_state.research_threads={}
key=user+':'+topic+':'+mode+':'+execution_mode
turns=st.session_state.research_threads.setdefault(key,[])
question=st.chat_input('기술조사 요청',disabled=not real_ready)
if question:
    with st.spinner('Research → Analysis → Verification ('+execution_mode+')'):
        try:
            result=app.ask(principal(user),user,question,topic=topic,mode=mode,execution_mode=execution_mode)
            turns.append({'question':question,'result':result})
        except (ValueError,PermissionError,RuntimeError) as exc:
            st.error(str(exc))
for i,turn in enumerate(turns):
    with st.chat_message('user'):
        st.write(turn['question'])
    with st.chat_message('assistant'):
        result=turn['result']
        render_answer({**result,'raw_answer':result['stages'][-1]['raw_answer'] if result['stages'] else result['answer']})
        if not result['complete']:
            st.warning('조사가 완료되지 않았습니다.')
            st.json(result.get('progress',{}))
            st.caption('중단된 역할의 원응답에는 실행기 오류 안내가 포함될 수 있습니다. 한도 확인 전 재시도·모델 전환으로 우회하지 않습니다.')
        with st.expander('정보원·검색 조건·실행 결과'):
            st.caption('입력 근거는 모델에 제공된 컨텍스트입니다. 모델의 선택 이유나 사후 설명을 인과관계의 증명으로 해석하지 않습니다.')
            st.json(result['trace'])
            st.json({'model_calls':result.get('model_calls'), 'real_audit':result.get('real_audit')})
        with st.expander('Research·Analysis·Verification'):
            st.caption('보고서는 세 역할 결과를 묶은 것입니다. 원응답 패널에는 마지막 역할의 응답을 표시합니다.')
            st.json(result['stages'])
        with st.expander('원문 근거·출처·기억'):
            st.json({'evidence':result['evidence'],'history_used':result.get('history_used',[]),'applied_inputs':result.get('input_snapshot',{})})
        with st.form('feedback-'+key+'-'+str(i)):
            feedback=st.text_input('사용자 피드백')
            public_preference=st.checkbox('이 선호는 PUBLIC 합성 테스트용임을 확인',key='public-'+key+'-'+str(i))
            preference=st.selectbox('명시적으로 승인할 조사 선호',['science','strategy','finance','papers_only'])
            if st.form_submit_button('피드백 저장 및 선호 승인'):
                actor=principal(user)
                app.store.append(actor,user,'feedback',turn['question'],feedback)
                app.approve(actor,preference,public_synthetic=public_preference)
                st.success('현재 사용자의 선호만 승인했습니다. 현재 요청·Environment·권한보다 우선하지 않습니다.')
