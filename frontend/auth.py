from __future__ import annotations

import hmac
import os

import streamlit as st


def password_matches(candidate: str, expected: str) -> bool:
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def require_public_demo_password() -> bool:
    """Gate a public personal-demo UI; returns False until the visitor is authenticated."""
    if os.getenv("TRUSTMESH_PUBLIC_MODE", "false").lower() not in {"1", "true", "yes"}:
        return True
    expected = os.getenv("TRUSTMESH_DEMO_PASSWORD")
    if not expected or len(expected) < 12:
        st.error("The public demo password is missing or too short. Set a password of at least 12 characters.")
        st.stop()
    if st.session_state.get("trustmesh_authenticated") is True:
        return True
    st.subheader("Private TrustMesh demo")
    st.caption("Enter the demo password provided by the owner.")
    with st.form("trustmesh_login"):
        candidate = st.text_input("Demo password", type="password")
        submitted = st.form_submit_button("Continue")
    if submitted:
        if password_matches(candidate, expected):
            st.session_state["trustmesh_authenticated"] = True
            st.rerun()
        st.error("Invalid password.")
    return False
