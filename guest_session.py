"""게스트 진입과 세션 사용자 상태. 소셜 인증 연동은 별도 구현한다."""
from uuid import uuid4

import streamlit as st


def ensure_guest_session():
    """처음 접속하면 별도 시작 화면 없이 게스트 세션을 준비한다."""
    viewer = st.session_state.get("viewer")
    if viewer is None or viewer.get("mode") == "visitor":
        st.session_state.viewer = {"mode": "guest", "user_id": "guest_" + uuid4().hex, "provider": None}
    st.session_state.setdefault("onboarding_done", False)
    st.session_state.setdefault("onboarding_open", False)
    st.session_state.setdefault("onboarding_step", 0)


def render_guest_controls():
    """계정 저장 요청을 받되, 인증이 없는 상태에서 저장 성공을 표시하지 않는다."""
    if st.session_state.viewer["mode"] != "guest":
        return
    st.markdown("**👤 게스트로 체험 중**")
    st.caption("내 설정과 대화는 현재 세션에만 유지돼요.")
    if st.button("내 설정·분석 기록 보관하기", key="request_account_save", width="stretch"):
        st.session_state.account_save_requested = True
    if st.session_state.get("account_save_requested", False):
        st.info("계정에 보관하려면 소셜 로그인이 필요해요. 로그인 기능은 준비 중이며, 지금은 현재 세션에서 계속 체험할 수 있어요.")
    st.divider()
