"""Show receipt-backed Evidence separately from Environment and connector configuration."""
import streamlit as st


def evidence_overview(result):
    rows = []
    for item in result.get('evidence', []):
        receipts = [event['plan']['id'] for event in result.get('trace', [])
            if event.get('executed') and event['plan']['api'].startswith('read_')
            and event['result']['status'] in {'ok', 'partial'}
            and event.get('egress_policy', {}).get('status', 'approved') == 'approved'
            and item in event['result'].get('items', [])]
        rows.append({'문서 ID': item['source_id'], '제목': item['title'], '정보원': item['origin_app'],
            '자료 구분': 'SYNTHETIC' if item.get('synthetic') is True else
                        '공개 Connector' if item.get('synthetic') is False else '미확인',
            '열람 범위': item.get('evidence_coverage', '도구 반환 span (범위 별도 확인)'),
            '조회 근거': ', '.join(receipts) if receipts else '미확인 — 일치하는 Read 기록 없음'})
    return rows


def render_evidence(result):
    with st.expander('Evidence · Tool Calling으로 확보한 자료', expanded=True):
        st.caption('Environment 목록과 분리된 이번 조사 자료입니다. 검색 후보만으로는 원문 근거가 되지 않으며, SYNTHETIC과 공개 Connector 결과를 구분합니다.')
        rows = evidence_overview(result)
        if rows:
            st.table(rows)
        else:
            st.caption('확보한 Read Evidence가 없습니다. Connector 설정만으로 조회 성공을 판단하지 않습니다.')
        st.caption('논문 메타데이터·초록, 특허 청구항, IR 추출 페이지 등 도구가 반환한 범위만 확인했습니다. PDF 전문 열람이나 독립적인 사실 검증을 보장하지 않습니다.')
