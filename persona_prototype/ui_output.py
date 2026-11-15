"""Render final output and keep the model draft available for audit."""
import streamlit as st

from .personalization import format_answer


def render_answer(result):
    answer = result['answer']
    style = result.get('format_validation', {}).get('requested')
    if style == 'table':
        # Old saved turns can still contain the earlier one-cell <br> tables.
        answer, audit = format_answer(answer, style)
        if audit['fallback_applied']:
            st.caption('저장된 답변의 표를 화면에서 정리했습니다. 원본 기록은 유지됩니다.')
    if result.get('evidence_validation', {}).get('raw_review', {}).get('issues'):
        st.warning('모델 초안에 근거 해석 검토 항목이 있습니다. 조회 근거와 함께 확인해 주세요.')
    st.markdown(answer)
    if result.get('format_validation', {}).get('fallback_applied'):
        st.caption('표시 형식은 로컬에서 보정했습니다. 모델 원응답의 형식 준수와는 별개입니다.')
    with st.expander('모델 원응답과 로컬 보정 내역'):
        st.code(result.get('raw_answer', answer), language='markdown')
        st.json({'format': result.get('format_validation', {}),
                 'evidence': result.get('evidence_validation', {}),
                 'sources': result.get('source_evidence', {})})
