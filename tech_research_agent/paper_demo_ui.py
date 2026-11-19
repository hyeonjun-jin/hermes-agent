"""Real API demonstration inside the existing Streamlit chatbot; no scripted fallback."""
from pathlib import Path

import streamlit as st

from .approvals import digest
from .environment_resources import environment_source_overview
from .evidence_ui import render_evidence
from .paper_demo import run_demo
from .paper_demo_approval import PaperDemoApproval, PROFILES_PUBLIC, QUESTION, public_environment, review_scope
from .paper_demo_real import connection_readiness
from .paper_ui import render_recommendations


def render():
    st.info('실제 API 시연: GPT-4o mini Research → Analysis → Verification + 실제 OpenAlex. Mock 자동 대체 없음.')
    st.caption('가상 공개 시연 Profile만 사용합니다. 프로젝트·기준일은 검수된 개발 Environment이며 실제 사내 업무 정보가 아닙니다.')
    profile = st.sidebar.selectbox('시연 사용자', ['A', 'B'], format_func=lambda value: '연구원 '+value)
    st.sidebar.selectbox('시연 프로젝트', ['수소환원제철'])
    with st.sidebar.expander('현재 시연 Profile', expanded=True):
        st.json(PROFILES_PUBLIC[profile])
    with st.sidebar.expander('현재 시연 Persona'):
        st.json({'version': 1, 'approved_preferences': {}, 'memory': '독립된 빈 초기 상태; 운영 Persona/Memory 미사용'})
    env = public_environment()
    with st.expander('Environment · 정보 자원'):
        st.json(env)
        resources = environment_source_overview(env, {})
        resources[0]['외부 Connector'] = '시연 서비스 전용 — 실행 시 생성'
        st.table(resources)
        st.caption('실행 승인 후 OpenAlex만 연결합니다. 현재 구성 확인은 실제 네트워크 성공 확인이 아닙니다.')
    try:
        settings = dict(st.secrets['technical_paper_demo'])
    except (KeyError, FileNotFoundError):
        settings = {}
    ready = False
    try:
        if settings.get('enabled') is True:
            approval = PaperDemoApproval(settings['approval_path'])
            connection_readiness()
            ready = True
            st.caption('서버 승인·키·네트워크 정책 설정 확인. 실제 API 연결은 이번 화면에서 아직 미검증입니다.')
            st.json({'호출 상한': approval.record['max_new_calls'], 'Profile별 상한': 6,
                     '응답 토큰 상한': 512, 'OpenAI 비용 예약 상한 USD': approval.record['max_reserved_usd'],
                     '자동 외부 재시도': 0})
        else:
            st.warning('실제 API 시연은 기본 비활성입니다. 관리자의 별도 실행 승인과 서버 활성화가 필요합니다.')
    except (RuntimeError, ValueError, KeyError, TypeError, OSError):
        st.error('승인·설정이 유효하지 않습니다. 관리자 승인 파일·키·모델·네트워크 정책을 확인하세요. API는 호출하지 않았습니다.')
    with st.expander('관리자 검수용 공개 전송 범위 (승인서 아님)'):
        scope = review_scope()
        st.code(digest(scope), language=None)
        st.json(scope)
    consent = st.sidebar.checkbox('이번 공개 Profile·논문 초록 외부 처리와 실제 API 과금에 동의합니다', key='demo-consent-'+profile)
    st.caption('채팅창 허용 질문: '+QUESTION)
    threads = st.session_state.setdefault('paper_demo_threads', {})
    turns = threads.setdefault(profile, [])
    question = st.chat_input('공개 논문 실제 API 시연 질문', disabled=not (ready and consent))
    if question:
        with st.spinner('실제 GPT-4o mini + OpenAlex 실행 중 — 자동 외부 재시도 없음'):
            try:
                result = run_demo(Path(__file__).resolve().parents[1], profile, question,
                    enabled=settings.get('enabled'), consent=consent, approval_path=settings.get('approval_path'))
                turns.append({'question': question, 'result': result})
            except (RuntimeError, ValueError, KeyError, TypeError, OSError) as exc:
                st.error('실제 API 시연이 중단됐습니다. 원장은 보존하며 Mock으로 대체하지 않습니다. ('+type(exc).__name__+')')
    for turn in turns:
        with st.chat_message('user'):
            st.write(turn['question'])
        with st.chat_message('assistant'):
            result = turn['result']
            st.caption('실제 API 시연 결과 · 연구원 '+result['demo_profile']+' · 실행 모드 '+result['mode'])
            if result['complete']:
                st.success('이 실행에서 모델 응답과 OpenAlex 검색·Read 근거를 확보했습니다. 상세 HTTP 상태와 사용량은 실행 기록에서 확인하세요.')
            st.markdown(result['answer'])
            render_recommendations(result)
            if not result['complete']:
                st.warning('실제 조사가 미완료입니다. 실패·누락된 초록·근거·예산 상태를 확인하세요. 자동 재시도하지 않습니다.')
            render_evidence(result)
            with st.expander('Research / Analysis / Verification 원응답'):
                st.json(result['stages'])
            with st.expander('실제 Tool Calling · 검색어 · DOI · 초록'):
                st.json(result['trace'])
                for item in result['evidence']:
                    st.text(item['source_id']+' — '+item['title'])
                    st.text(item.get('abstract') or '초록 미확인 — 메타데이터만 반환됨')
            with st.expander('실제 API 연결 결과 · 호출 · 토큰 · 비용 · Payload 해시'):
                st.json(result['real_audit'])
                st.caption('this_run_usage는 이번 질문, totals는 시연 원장 누적입니다. OpenAI 요율은 기존 잠정 요율이며 OpenAlex 요금은 별도 미검증입니다.')
