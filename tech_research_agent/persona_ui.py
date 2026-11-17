"""Owner/project scoped Streamlit controls. User preference approval is not egress approval."""
import streamlit as st

from .persona_preferences import APIS, CRITERIA, DIMENSIONS

LABELS = {'sources': '정보원 적절성', 'scope_recency': '검색 범위·최신성', 'depth': '조사 깊이',
          'technical_detail': '기술적 세부 분석', 'business_detail': '경쟁사·사업화 분석',
          'financial_detail': '투자·재무 위험 분석', 'report': '보고서 구성·설명'}


def perform(action, key, status):
    try:
        result = action()
    except (ValueError, PermissionError, RuntimeError) as exc:
        st.error(str(exc))
        return
    st.session_state['persona-message-'+key] = result.get('status', status) if isinstance(result, dict) else status
    st.rerun()


def panel(app, actor, project):
    state = app.personas.inspect(actor, project)
    key = actor.user_id+'-'+project
    with st.expander('기술조사 Persona 버전·후보·이력'):
        st.write('현재 활성 Persona v'+str(state['active']['revision']))
        st.json(state['active'])
        st.caption('승인은 다음 조사 입력에 적용됩니다. 문서 접근 권한·반출 승인은 변경하지 않습니다. 새 버전은 기본 PRIVATE입니다.')
        if st.button('Persona 변경 후보 생성 · Offline Replay', key='propose-'+key):
            with st.spinner('격리된 SYNTHETIC Mock 흐름 비교 중'):
                perform(lambda:app.aligner.propose(actor, project),key,'proposed')
        if 'persona-message-'+key in st.session_state:
            st.info('후보 상태: '+st.session_state['persona-message-'+key])
        st.caption('최소 네 개의 서로 다른 완료 조사에서 확인·동의한 선호가 필요합니다. 세 개 이상 일치와 별도 확인 사례를 사용합니다.')
        for proposal in state['proposals']:
            with st.expander('후보 '+proposal['proposal_id'][:8]+' · '+proposal['status']):
                st.json({'기존': proposal['baseline'], '후보 선호': proposal['candidate_preferences']})
                st.json(proposal['replay'])
                st.caption('Offline Replay는 기능 확인입니다. 실제 모델의 개인화 효과나 조사 품질 향상을 뜻하지 않습니다.')
                if proposal['status'] == 'proposed':
                    if st.button('후보 승인', key='accept-'+key+'-'+proposal['proposal_id']):
                        perform(lambda:app.personas.activate(actor, project, proposal_id=proposal['proposal_id']),key,'applied')
                    if st.button('후보 거절', key='reject-'+key+'-'+proposal['proposal_id']):
                        perform(lambda:app.personas.reject(actor, project, proposal['proposal_id']),key,'rejected')
        versions = [version['revision'] for version in state['versions'] if version['revision'] != state['active']['revision']]
        if versions:
            target = st.selectbox('복원할 Persona 버전', versions, key='rollback-target-'+key)
            if st.button('이전 버전으로 롤백', key='rollback-'+key):
                perform(lambda:app.personas.activate(actor, project, rollback_revision=target),key,'rolled_back')
        st.json({'변경 이력': state['versions'], '감사 이벤트': state['events']})


def feedback_form(app, actor, project, result, key):
    if not result.get('alignment_turn_id'):
        return
    with st.form('research-feedback-'+key):
        st.caption('자유 의견은 PRIVATE로 보관합니다. 아래 구조화 선호만 별도 확인·동의 후 후보 생성에 사용합니다.')
        dimensions = {dimension: st.selectbox(LABELS[dimension], ['not_assessed', 'helpful', 'needs_change'],
                                              key=key+'-rating-'+dimension) for dimension in DIMENSIONS}
        comment = st.text_area('자유 피드백', max_chars=4000)
        apps = st.multiselect('선호 정보원 변경', list(APIS))
        apis = st.multiselect('선호 검색 API 변경', [app+'/'+api for app, api in APIS.items()])
        criteria = st.multiselect('주요 분석 기준 변경', sorted(CRITERIA))
        lookback = st.selectbox('조사 기간 선호 · 개월', [None, 6, 12, 36, 60], format_func=lambda v: '변경 안 함' if v is None else str(v))
        limit = st.selectbox('검색 결과 수 선호', [None, *range(1, 11)], format_func=lambda v: '변경 안 함' if v is None else str(v))
        levels = {field: st.selectbox(label+' 선호', [None, 'brief', 'detailed'], format_func=lambda v: '변경 안 함' if v is None else v)
                  for field, label in [('depth', '조사 깊이'), ('technical_detail', '기술 분석'),
                                       ('business_detail', '사업 분석'), ('financial_detail', '재무 분석')]}
        report = st.selectbox('보고서 형식 선호 · Tool OP와 별개', [None, 'bullets', 'table', 'explanation'], format_func=lambda v: '변경 안 함' if v is None else v)
        sort_app = st.selectbox('정렬 선호 정보원', [None, 'openalex', 'kipris_plus', 'posco_ir'])
        sort = st.selectbox('정렬 선호', ['date_desc', 'relevance', 'citations_desc'])
        confirmed = st.checkbox('피드백 내용을 확인했습니다')
        consent = st.checkbox('구조화 선호를 Persona 후보 생성에 사용하도록 동의합니다')
        if st.form_submit_button('기술조사 피드백 저장'):
            changes = {name: value for name, value in {**levels, 'lookback_months': lookback, 'result_limit': limit,
                                                      'report_format': report}.items() if value is not None}
            changes.update({name: value for name, value in {'preferred_apps': apps, 'preferred_apis': apis, 'criteria': criteria}.items() if value})
            if sort_app:
                changes['sort'] = {sort_app: sort}
            try:
                app.personas.feedback(actor, project, result['alignment_turn_id'], dimensions, changes, comment,
                                      confirmed=confirmed, consent=consent)
                st.success('피드백을 저장했습니다. Persona는 자동 변경되지 않았습니다.')
            except (ValueError, PermissionError) as exc:
                st.error(str(exc))
