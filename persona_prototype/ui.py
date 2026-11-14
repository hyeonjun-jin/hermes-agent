"""Streamlit client; API keys never travel to the browser or this API client."""
import os

import httpx
import streamlit as st

st.set_page_config(page_title="Persona Chat", page_icon="💬", layout="centered")


def request(method, path, *, session=None, body=None):
    api = os.environ.get("PERSONA_CHAT_API", "http://127.0.0.1:8000")
    headers = {"Authorization": "Bearer " + session["session_token"]} if session else {}
    response = httpx.request(method, api + path, headers=headers, json=body, timeout=180)
    response.raise_for_status()
    return response.json()


st.title("Persona Chat")
st.caption("사용자 맥락과 기억을 반영하는 개발용 챗봇")
try:
    health = request("GET", "/health")
except httpx.HTTPError:
    st.error("챗봇 Backend에 연결할 수 없습니다. 실행 상태를 확인해 주세요.")
    st.stop()
with st.sidebar:
    st.header("대화")
    st.warning("개발 전용 사용자 선택입니다. 실제 서비스 인증이 아닙니다.")
    user = st.selectbox("테스트 사용자", ["alice", "bob", "carol"], format_func=str.title)
    st.caption("모델: " + health["model"])
    if health["remaining_calls"] is not None:
        st.metric("남은 모델 호출", health["remaining_calls"])
        st.caption("모든 사용자와 Subagent가 12회 예산을 공유합니다.")
    fresh = st.button("새 대화", use_container_width=True)

if "sessions" not in st.session_state:
    st.session_state.sessions = {}
try:
    existing = request("GET", "/dev/sessions?user=" + user)
except httpx.HTTPError:
    st.error("개발용 대화 목록을 불러올 수 없습니다.")
    st.stop()
selection_key = "conversation-" + user
if fresh or not existing:
    try:
        session = request("POST", "/dev/sessions", body={"user": user})
        st.session_state.sessions[user] = session
        existing = [{"session_id": session["session_id"]}, *existing]
        st.session_state[selection_key] = session["session_id"]
    except httpx.HTTPError:
        st.error("개발용 세션을 만들 수 없습니다.")
        st.stop()
with st.sidebar:
    selected = st.selectbox("대화 기록 선택", [s["session_id"] for s in existing], key=selection_key,
                            format_func=lambda value: "대화 " + value[:8])
known = st.session_state.sessions.get(user)
if not known or known["session_id"] != selected:
    try:
        st.session_state.sessions[user] = request("POST", f"/dev/sessions/{selected}/resume", body={"user": user})
    except httpx.HTTPError:
        st.error("개발용 대화를 복원할 수 없습니다.")
        st.stop()
session = st.session_state.sessions[user]
sid = session["session_id"]
try:
    history = request("GET", "/sessions/" + sid, session=session)
except httpx.HTTPError:
    st.error("이 대화에 접근할 수 없습니다. 새 대화를 시작해 주세요.")
    st.stop()
st.caption("대화 사용자: " + user.title())
with st.sidebar.expander("적용된 Persona"):
    st.json(history["persona"])
with st.sidebar.expander("대화 기록"):
    for turn in history["turns"]:
        st.write(turn["question"])
if health["mode"] == "mock":
    st.info("현재 Mock 모드입니다. 연결·세션 동작을 시험하며 실제 LLM 품질을 뜻하지 않습니다.")
for turn in history["turns"]:
    with st.chat_message("user"):
        st.write(turn["question"])
    result = turn["result"]
    with st.chat_message("assistant"):
        st.markdown(result["answer"])
        quality = result.get("quality", {})
        if quality.get("source_ids"):
            st.caption("참고 문서: " + ", ".join(quality["source_ids"]))
        if result.get("loop_error") or result.get("completion", {}).get("complete") is False:
            st.warning("실행 또는 근거 검증이 완료되지 않았습니다.")
        if not quality.get("korean_present", True) or quality.get("possible_environment_contradiction"):
            st.warning("응답 언어 또는 근거 해석을 추가로 검토해야 합니다.")
        with st.expander("활용한 기억과 검토 내역"):
            st.json({"memory": result.get("recall_events", []), "agents": result.get("delegations", []),
                     "quality": quality, "format": result.get("format_validation", {})})
        with st.expander("답변 피드백"):
            comment = st.text_input("의견", key="comment-" + turn["turn_id"])
            rating = st.radio("평가", ["helpful", "unhelpful"], key="rating-" + turn["turn_id"], horizontal=True,
                              format_func=lambda value: "도움돼요" if value == "helpful" else "아쉬워요")
            if st.button("피드백 저장", key="save-" + turn["turn_id"]):
                try:
                    request("POST", f"/sessions/{sid}/feedback", session=session,
                            body={"turn_id": turn["turn_id"], "rating": rating, "comment": comment})
                    st.success("피드백을 저장했습니다. 자동 학습에는 사용하지 않습니다.")
                except httpx.HTTPError:
                    st.error("피드백 저장에 실패했습니다.")

question = st.chat_input("질문을 입력하세요", disabled=health["remaining_calls"] == 0 or health["stopped"])
if question:
    try:
        with st.spinner("답변을 준비하고 있습니다…"):
            request("POST", f"/sessions/{sid}/messages", session=session, body={"message": question})
        st.rerun()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            st.error("모델 호출 예산이 소진되었거나 중단됐습니다. 자동 재시도하지 않습니다.")
        else:
            st.error("답변을 생성하지 못했습니다. Backend 상태를 확인해 주세요.")
    except httpx.HTTPError:
        st.error("연결이 끊겼습니다. 대화 기록을 먼저 확인하고 중복 전송에 유의해 주세요.")
