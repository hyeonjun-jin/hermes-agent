"""Explicit development controls: local Mock proposal, manual approval and rollback."""
import httpx
import streamlit as st


def alignment_panel(request, session):
    sid = session["session_id"]
    path = f"/sessions/{sid}/alignment"
    with st.sidebar.expander("피드백 기반 Persona 개선"):
        st.caption("동의한 선호만 사용합니다. 검증은 로컬 Mock이며 실제 모델 개선을 보증하지 않습니다.")
        try:
            state = request("GET", path, session=session)
            st.write("활성 Persona 버전:", state["revision"])
            st.json(state["preferences"])
            if st.button("Mock으로 후보 검증", key="propose-" + sid):
                with st.spinner("기존 Persona와 후보를 Mock으로 비교합니다…"):
                    report = request("POST", path + "/proposals", session=session)
                st.json(report)
                state = request("GET", path, session=session)
            for proposal in state["proposals"]:
                st.write("후보", proposal["proposal_id"][:8], proposal["status"])
                st.json(proposal)
                if proposal["status"] == "proposed":
                    confirmed = st.checkbox("Mock 검증의 한계를 확인하고 이 후보 적용을 승인합니다",
                                            key="confirm-" + proposal["proposal_id"])
                    if st.button("후보 승인·적용", key="approve-" + proposal["proposal_id"], disabled=not confirmed):
                        request("POST", path + "/" + proposal["proposal_id"] + "/approve", session=session, body={"confirm": True})
                        st.success("적용했습니다. 새 대화를 시작하면 반영됩니다.")
            versions = [v["revision"] for v in state["versions"] if v["revision"] != state["revision"]]
            if versions:
                target = st.selectbox("복원할 버전", versions, key="rollback-version-" + sid)
                confirmed = st.checkbox("이전 선호로 롤백을 승인합니다", key="rollback-confirm-" + sid)
                if st.button("롤백", disabled=not confirmed, key="rollback-" + sid):
                    request("POST", path + "/rollback/" + str(target), session=session, body={"confirm": True})
                    st.success("롤백했습니다. 새 대화부터 반영됩니다.")
        except httpx.HTTPError:
            st.error("Persona 작업을 완료하지 못했습니다. 근거·권한·후보 상태를 확인해 주세요.")
