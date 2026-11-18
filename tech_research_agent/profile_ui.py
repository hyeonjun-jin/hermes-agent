"""Explicit owner edits for the development process only; never Persona approval."""
import streamlit as st


def panel(app, actor):
    profile = app.profile(actor, actor.user_id)
    def reset():
        app.reset_profile(actor, actor.user_id)
        for field in ('business_unit', 'department', 'job', 'expertise', 'criteria', 'interests'):
            st.session_state.pop('profile-'+actor.user_id+'-'+field, None)
    with st.expander('개발 Profile 수정 · 사용자별 관심사'):
        st.caption('Profile 편집은 프로세스 메모리에만 적용되고 서버 재시작 시 초기화됩니다. 조사 실행 시 입력 스냅샷은 기존 사용자별 조사 이력에 기록됩니다. Persona 자동 변경은 없으며 편집 값의 외부 전송은 차단합니다.')
        with st.form('profile-edit-'+actor.user_id):
            values = {field: st.text_input(label, value=profile[field], key='profile-'+actor.user_id+'-'+field)
                      for field, label in (('business_unit', '사업부서'), ('department', '부서'), ('job', '직무'),
                                           ('expertise', '전문 분야'), ('criteria', '평가 기준'))}
            raw = st.text_area('관심 기술 (한 줄에 하나)', value='\n'.join(profile['interests']), key='profile-'+actor.user_id+'-interests')
            if st.form_submit_button('이 사용자 Profile 적용'):
                try:
                    app.update_profile(actor, actor.user_id, {**values, 'interests': [s.strip() for s in raw.splitlines() if s.strip()]})
                    st.rerun()
                except (ValueError, PermissionError) as exc:
                    st.error(str(exc))
        st.button('이 사용자 Profile 기본값 복원', key='profile-reset-'+actor.user_id, on_click=reset)
    with st.expander('동일 직무 · 서로 다른 관심사 비교 (SYNTHETIC Mock)'):
        st.caption('운영 입력과 분리된 임시 상태입니다. 동일 질문·Environment·초기 Memory·후보집합에서 비교하며 실제 LLM 성능 검증이 아닙니다.')
        if st.button('직무별 / 관심사별 통제 비교 실행', key='profile-offline-comparison'):
            from .profile_experiments import run_offline_comparison
            with st.spinner('격리된 Mock 3-Agent 비교 중'):
                st.session_state.profile_comparison = run_offline_comparison()
        if st.session_state.get('profile_comparison'):
            data = st.session_state.profile_comparison
            for name, group in data['experiments'].items():
                st.write(name)
                st.table([{'조건': label, '순위': p['rank'], '논문': p['title'], '점수': p['score'],
                           '관심사 점수': p['score_components']['personal_interests'],
                           '추천 근거': '; '.join(p['reasons'])}
                          for label, arm in group.items() for p in arm['recommendations']])
            with st.expander('분석 관점·검색 인자·입력 통제·실제 실행 준비 상태'):
                st.json(data)
