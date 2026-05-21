"""
auth.py — Supabase authentication helpers for the Streamlit UI.

Provides:
  - get_supabase_client()   → singleton Supabase client
  - render_auth_page()      → full Sign In / Sign Up UI
  - render_user_sidebar()   → logged-in user badge + sign-out button
  - is_authenticated()      → bool — gating for every page

Session keys used (all stored in st.session_state):
  sb_user    : dict  — Supabase User object (id, email, role)
  sb_session : dict  — Supabase Session object (access_token, etc.)
  sb_email   : str   — cached email for display
"""

import os
import streamlit as st
from supabase import create_client, Client
from dotenv import load_dotenv
from gotrue.errors import AuthApiError

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")


# ── Singleton client ───────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def get_supabase_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("SUPABASE_URL and SUPABASE_KEY must be set in .env")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ── Session helpers ────────────────────────────────────────────────────────────
def _set_session(user, session):
    """Persist Supabase user + session into Streamlit session_state."""
    st.session_state["sb_user"]    = user
    st.session_state["sb_session"] = session
    st.session_state["sb_email"]   = getattr(user, "email", "") or ""


def _clear_session():
    for key in ("sb_user", "sb_session", "sb_email"):
        st.session_state.pop(key, None)


def is_authenticated() -> bool:
    sb_auth = st.session_state.get("sb_user") is not None
    st_auth = False
    if hasattr(st, "user"):
        try:
            st_auth = st.user.is_logged_in
        except Exception:
            pass
    return sb_auth or st_auth


# ── Sign-in ────────────────────────────────────────────────────────────────────
def _do_sign_in(email: str, password: str) -> bool:
    sb = get_supabase_client()
    try:
        resp = sb.auth.sign_in_with_password({"email": email, "password": password})
        _set_session(resp.user, resp.session)
        return True
    except AuthApiError as e:
        st.error(f"Sign-in failed: {e.message}")
        return False
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return False


# ── Sign-up ────────────────────────────────────────────────────────────────────
def _do_sign_up(email: str, password: str) -> bool:
    sb = get_supabase_client()
    try:
        resp = sb.auth.sign_up({"email": email, "password": password})
        # Supabase may require email confirmation — check user
        if resp.user and resp.user.confirmed_at:
            _set_session(resp.user, resp.session)
            st.success("Account created and signed in!")
        else:
            st.success(
                "Account created! Please check your email inbox to confirm your address, "
                "then sign in."
            )
        return True
    except AuthApiError as e:
        st.error(f"Sign-up failed: {e.message}")
        return False
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return False


# ── Sign-out ───────────────────────────────────────────────────────────────────
def do_sign_out():
    sb = get_supabase_client()
    try:
        sb.auth.sign_out()
    except Exception:
        pass  # sign out locally even if the API call fails
    _clear_session()
    
    is_st_auth = False
    if hasattr(st, "user"):
        try:
            is_st_auth = st.user.is_logged_in
        except Exception:
            pass
            
    if is_st_auth and hasattr(st, "logout"):
        st.logout()
    else:
        st.rerun()


def render_auth_page():
    """
    Renders the full-page Sign In / Sign Up form.
    Call this when is_authenticated() is False.
    """
    # If the user clicked the custom HTML Google button, trigger st.login()
    if st.query_params.get("login") == "google" and hasattr(st, "login"):
        st.query_params.clear()
        st.login()
        st.stop()

    # Centred card layout
    _, col, _ = st.columns([1, 1.6, 1])
    with col:
        # st.markdown("""
        # <div style="
        #     background: linear-gradient(135deg,#1c2128,#161b22);
        #     border: 1px solid #30363d;
        #     border-radius: 16px;
        #     padding: 40px 36px 32px 36px;
        #     margin-top: 60px;
        # ">
        # """, unsafe_allow_html=True)

        # Logo / title
        st.markdown("""
        <div style="text-align:center; margin-bottom:28px">
            <h2 style="color:#e6edf3; margin:10px 0 4px 0; font-family:Inter,sans-serif; font-weight:700">
                Claim Denial Prevention
            </h2>
            <p style="color:#8b949e; font-size:0.9rem; margin:0">
                AI-powered claim denial prevention platform.
            </p>
        </div>
        """, unsafe_allow_html=True)

        if hasattr(st, "login"):
            st.markdown("""
            <style>
            .google-btn {
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 12px;
                width: 100%;
                padding: 0.6rem 1rem;
                border-radius: 10px;
                border: 1px solid #30363d;
                background-color: #1f242c;
                color: #e6edf3;
                font-size: 16px;
                font-weight: 500;
                cursor: pointer;
                text-decoration: none;
                transition: 0.2s ease;
            }

            .google-btn:hover {
                border-color: #4285F4;
                background-color: #242930;
                box-shadow: 0 0 5px rgba(66,133,244,0.4);
                color: #ffffff;
                text-decoration: none;
            }

            .google-logo {
                width: 20px;
                height: 20px;
            }
            </style>

            <a class="google-btn" href="?login=google" target="_self">
                <img class="google-logo"
                    src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg">
                Sign in with Google
            </a>
            """, unsafe_allow_html=True)

            st.markdown(
                "<div style='text-align:center; color:#8b949e; margin:10px 0;'> OR </div>",
                unsafe_allow_html=True
            )

        tab_in, tab_up = st.tabs(["Sign In", "Sign Up"])

        # ── Sign In tab ──────────────────────────────────────────────────────
        with tab_in:
            with st.form("signin_form", clear_on_submit=False):
                email    = st.text_input("Email", placeholder="you@example.com", key="si_email")
                password = st.text_input("Password", type="password", placeholder="••••••••", key="si_pass")
                submitted = st.form_submit_button("Sign In →", use_container_width=True)

            if submitted:
                if not email or not password:
                    st.warning("Please enter both email and password.")
                else:
                    with st.spinner("Authenticating…"):
                        ok = _do_sign_in(email.strip(), password)
                    if ok:
                        st.rerun()

        # ── Sign Up tab ──────────────────────────────────────────────────────
        with tab_up:
            with st.form("signup_form", clear_on_submit=True):
                su_email  = st.text_input("Email", placeholder="you@example.com", key="su_email")
                su_pass   = st.text_input("Password", type="password",
                                          placeholder="Min 6 characters", key="su_pass")
                su_pass2  = st.text_input("Confirm Password", type="password",
                                          placeholder="Repeat password", key="su_pass2")
                submitted_up = st.form_submit_button("Create Account →", use_container_width=True)

            if submitted_up:
                if not su_email or not su_pass:
                    st.warning("Please fill in all fields.")
                elif len(su_pass) < 6:
                    st.warning("Password must be at least 6 characters.")
                elif su_pass != su_pass2:
                    st.error("Passwords do not match.")
                else:
                    with st.spinner("Creating account…"):
                        _do_sign_up(su_email.strip(), su_pass)

        st.markdown("</div>", unsafe_allow_html=True)


# ── Sidebar user badge ─────────────────────────────────────────────────────────
def render_user_sidebar():
    """
    Renders a compact user badge + Sign Out button inside the sidebar.
    Call this at the top of the sidebar block after authentication is confirmed.
    """
    is_st_auth = False
    if hasattr(st, "user"):
        try:
            is_st_auth = st.user.is_logged_in
        except Exception:
            pass

    if is_st_auth:
        email = st.user.email
        uid = "Google Auth"
        provider = "GOOGLE"
    else:
        email = st.session_state.get("sb_email", "")
        user  = st.session_state.get("sb_user")
        uid   = getattr(user, "id", "")[:8] if user else ""
        provider = "SUPABASE"

    st.sidebar.markdown(f"""
    <div style="
        background: #1c2128;
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 12px 14px;
        margin-bottom: 12px;
    ">
        <div style="color:#3fb950; font-size:0.78rem; font-weight:600; margin-bottom:4px">
            ● SIGNED IN ({provider})
        </div>
        <div style="color:#e6edf3; font-size:0.88rem; word-break:break-all">{email}</div>
        <div style="color:#8b949e; font-size:0.72rem; margin-top:3px">uid: {uid}…</div>
    </div>
    """, unsafe_allow_html=True)

    if st.sidebar.button("Sign Out", use_container_width=True):
        do_sign_out()
