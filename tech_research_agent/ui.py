"""Streamlit development UI; every model endpoint is an internally created loopback Mock."""
from pathlib import Path
import streamlit as st
from tech_research_agent.application import ResearchApplication, principal
from tech_research_agent.config import PROFILES, runtime
from persona_prototype.ui_output import render_answer

st.set_page_config(page_title='개인화 기술조사',layout='wide')
st.title('개인화 기술조사 Agent')
st.caption('합성 업무 환경 기준일: 2026-10-01. 실제 현재 업무 정보가 아닙니다.')
st.warning('개발 전용 사용자 선택입니다. 실제 SSO 인증이 아닙니다. 모든 자료는 SYNTHETIC이며 모델은 Mock입니다.')


@st.cache_resource
def application():
    return ResearchApplication(Path.cwd()/'.technical-research-state')


app=application()
user=st.sidebar.selectbox('사용자',list(PROFILES),format_func=lambda u:PROFILES[u]['department']+' / '+PROFILES[u]['job'])
topic=st.sidebar.selectbox('현재 프로젝트',['H','B'],format_func=lambda t:'수소환원제철' if t=='H' else '이차전지 양극재')
mode=st.sidebar.selectbox('현재 환경',['quick','deep','restricted'])
profile,env,_=runtime(user,topic,mode)
with st.sidebar.expander('현재 Persona와 승인 선호',expanded=True):
    st.json({**profile,'approved_preferences':app.store.semantic(principal(user),user)})
with st.sidebar.expander('현재 Environment'):
    st.json(env)
if 'research_threads' not in st.session_state:
    st.session_state.research_threads={}
key=user+':'+topic+':'+mode
turns=st.session_state.research_threads.setdefault(key,[])
question=st.chat_input('기술조사 요청')
if question:
    with st.spinner('Research → Analysis → Verification (Mock)'):
        try:
            result=app.ask(principal(user),user,question,topic=topic,mode=mode)
            turns.append({'question':question,'result':result})
        except (ValueError,PermissionError) as exc:
            st.error(str(exc))
for i,turn in enumerate(turns):
    with st.chat_message('user'):
        st.write(turn['question'])
    with st.chat_message('assistant'):
        result=turn['result']
        render_answer({**result,'raw_answer':result['stages'][-1]['raw_answer'] if result['stages'] else result['answer']})
        if not result['complete']:
            st.warning('조사가 완료되지 않았습니다.')
        with st.expander('정보원·검색 조건·실행 결과'):
            st.json(result['trace'])
        with st.expander('Research·Analysis·Verification'):
            st.caption('보고서는 세 역할 결과를 묶은 것입니다. 원응답 패널에는 마지막 역할의 응답을 표시합니다.')
            st.json(result['stages'])
        with st.expander('원문 근거·출처·기억'):
            st.json({'evidence':result['evidence'],'history_used':result.get('history_used',[])})
        with st.form('feedback-'+key+'-'+str(i)):
            feedback=st.text_input('사용자 피드백')
            preference=st.selectbox('명시적으로 승인할 조사 선호',['science','strategy','finance','papers_only'])
            if st.form_submit_button('피드백 저장 및 선호 승인'):
                actor=principal(user)
                app.store.append(actor,user,'feedback',turn['question'],feedback)
                app.approve(actor,preference)
                st.success('현재 사용자의 선호만 승인했습니다. 현재 요청·Environment·권한보다 우선하지 않습니다.')
