"""Local owner-facing recommendation display, separate from the model-generated report."""
import streamlit as st


def render_recommendations(result):
    data = result.get('paper_recommendations', {})
    st.subheader('맞춤 논문 추천 TOP 3')
    st.caption('확인된 적합 후보만 최대 3개 표시합니다. 로컬 결정론적 정렬이며 학습 효과·기술 우수성·PDF 본문 검증을 의미하지 않습니다.')
    if not data.get('items'):
        st.caption('검색과 read_work로 확인한 적합 후보가 없습니다. Mock에서 논문 추천 요청을 실행할 수 있습니다.')
        return
    for paper in data['items']:
        st.text(str(paper['rank'])+'. '+paper['title'])
        st.caption('발행 연도: '+str(paper['publication_year'])+' / 적합도: '+str(paper['score'])+
                   ' / 초록: '+('확인' if paper['abstract_checked'] else '미확인 — 메타데이터만 확인'))
        scores=paper['score_components']
        st.caption('사업부서 '+str(scores.get('profile_business_unit',0))+' · 직무 '+str(scores.get('profile_job',0))+
                   ' · 전문성 '+str(scores.get('profile_expertise',0))+' · 관심사 '+str(scores.get('personal_interests',0))+
                   ' · 승인 Persona '+str(scores.get('persona_criteria',0)))
        if paper['synthetic']:
            st.caption('SYNTHETIC 가상 논문 — 실제 DOI/원문 링크 없음')
        for label, field in (('DOI (OpenAlex 제공)', 'doi'), ('OpenAlex 메타데이터', 'openalex_link'), ('원문 위치 (본문 미열람)', 'source_link')):
            if paper.get(field): st.link_button(label, paper[field])
        for reason in paper['reasons']: st.text('• '+reason)
        with st.expander('추천 점수·Persona·Environment 근거 #'+str(paper['rank'])):
            st.json({'components': paper['score_components'], 'persona': paper['persona_basis'],
                     'profile': paper.get('profile_basis',{}), 'interests': paper.get('interest_basis',{}),
                     'environment': paper['environment_basis'], 'source_basis': paper['source_basis']})
