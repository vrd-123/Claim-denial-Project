"""
auth.py — Supabase + Google OAuth authentication helpers for the Streamlit UI.

Provides:
  - get_supabase_client()   → singleton Supabase client
  - render_auth_page()      → full Sign In / Sign Up UI with Google OAuth
  - render_user_sidebar()   → logged-in user badge + sign-out button
  - is_authenticated()      → bool — gating for every page

Session keys:
  sb_user    : Supabase User object
  sb_session : Supabase Session object
  sb_email   : cached email for display
"""

import os
import time
import streamlit as st
from supabase import create_client, Client
from dotenv import load_dotenv
from gotrue.errors import AuthApiError

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ── Dual-Mode Database Connection Helpers for Registered Users ───────────────
class PostgresRowWrapper:
    def __init__(self, dict_row):
        self._dict_row = dict_row

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._dict_row[key]
        try:
            return self._dict_row[key]
        except KeyError:
            if isinstance(key, str):
                return self._dict_row[key.lower()]
            raise

    def keys(self):
        return list(self._dict_row.keys())

    def values(self):
        return list(self._dict_row.values())

    def items(self):
        return list(self._dict_row.items())

    def __iter__(self):
        return iter(self.keys())

    def __len__(self):
        return len(self._dict_row)


class PostgresCursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, params=None):
        sql_rewritten = sql.replace('?', '%s')
        self._cursor.execute(sql_rewritten, params or ())
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return PostgresRowWrapper(row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [PostgresRowWrapper(r) for r in rows]

    @property
    def description(self):
        return self._cursor.description

    def close(self):
        self._cursor.close()

    def __iter__(self):
        for r in self._cursor:
            yield PostgresRowWrapper(r)


class DbConnectionWrapper:
    def __init__(self, conn, is_postgres=False):
        self._conn = conn
        self.is_postgres = is_postgres
        self._row_factory = None

    @property
    def row_factory(self):
        return self._row_factory

    @row_factory.setter
    def row_factory(self, val):
        self._row_factory = val
        if not self.is_postgres:
            self._conn.row_factory = val

    def cursor(self):
        if self.is_postgres:
            import psycopg2.extras
            cur = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            return PostgresCursorWrapper(cur)
        else:
            return self._conn.cursor()

    def execute(self, sql, params=None):
        if self.is_postgres:
            import psycopg2.extras
            sql_rewritten = sql.replace('?', '%s')
            cur = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute(sql_rewritten, params or ())
            return PostgresCursorWrapper(cur)
        else:
            if params is not None:
                return self._conn.execute(sql, params)
            else:
                return self._conn.execute(sql)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def _get_db_conn():
    db_host = os.getenv("DB_HOST", "")
    if db_host:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(
            host=db_host,
            port=int(os.getenv("DB_PORT", 5432)),
            database=os.getenv("DB_NAME", "cdp"),
            user=os.getenv("DB_USER", "cdpuser"),
            password=os.getenv("DB_PASSWORD", ""),
        )
        return DbConnectionWrapper(conn, is_postgres=True)
    else:
        import sqlite3
        conn = sqlite3.connect("data/claim_history.db")
        return DbConnectionWrapper(conn, is_postgres=False)


def _register_user_in_db(email: str):
    email_clean = str(email or "").strip().lower()
    if not email_clean:
        return
    try:
        conn = _get_db_conn()
        cur = conn.cursor()
        
        if conn.is_postgres:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS registered_users (
                    email VARCHAR(255) PRIMARY KEY,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            
            cur.execute("""
                INSERT INTO registered_users (email)
                VALUES (?)
                ON CONFLICT (email) DO NOTHING
            """, (email_clean,))
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS registered_users (
                    email TEXT PRIMARY KEY,
                    registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            
            cur.execute("""
                INSERT OR IGNORE INTO registered_users (email)
                VALUES (?)
            """, (email_clean,))
            
        conn.commit()
        conn.close()
    except Exception as e:
        import logging
        logging.error(f"Failed to register user in db: {e}")


def _is_user_registered(email: str) -> bool:
    email_clean = str(email or "").strip().lower()
    if not email_clean:
        return False

    # 1. Check demo accounts
    demo_accounts = {"billing_agent_01", "billing_agent_02", "manager_01", "test@test.com",
                     "billing_agent_01@example.com", "billing_agent_02@example.com", "manager_01@example.com"}
    if email_clean in demo_accounts:
        return True

    # 2. Check databases
    try:
        conn = _get_db_conn()
        cur = conn.cursor()
        
        # Ensure registered_users table exists
        if conn.is_postgres:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS registered_users (
                    email VARCHAR(255) PRIMARY KEY,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS registered_users (
                    email TEXT PRIMARY KEY,
                    registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
        conn.commit()

        # Check registered_users table
        row = cur.execute("SELECT 1 FROM registered_users WHERE LOWER(email) = ?", (email_clean,)).fetchone()
        if row:
            conn.close()
            return True

        # Check claim_history (submitted_by)
        try:
            row = cur.execute("SELECT 1 FROM claim_history WHERE LOWER(submitted_by) = ? LIMIT 1", (email_clean,)).fetchone()
            if row:
                conn.close()
                return True
        except Exception:
            pass

        # Check audit_trail (user_email)
        try:
            row = cur.execute("SELECT 1 FROM audit_trail WHERE LOWER(user_email) = ? LIMIT 1", (email_clean,)).fetchone()
            if row:
                conn.close()
                return True
        except Exception:
            pass

        conn.close()
    except Exception as e:
        import logging
        logging.error(f"Error checking user registration in DB: {e}")

    return False


# ── Detect which user object Streamlit 1.42 exposes ──────────────────────────
# st.login() / st.logout() → available in Streamlit ≥ 1.38
# User info lives in st.experimental_user (Streamlit 1.38–1.42)
# (st.user is an alias in newer builds but not guaranteed)
def _get_st_user():
    """Return the Streamlit experimental_user proxy, or None if unavailable."""
    try:
        if hasattr(st, "experimental_user"):
            return st.experimental_user
    except Exception:
        pass
    return None


def _is_google_auth_configured() -> bool:
    """True when secrets.toml [auth] section has client_id set."""
    try:
        u = _get_st_user()
        if u is not None and hasattr(u, "is_logged_in"):
            return True  # auth section is present and loaded
    except Exception:
        pass
    # Fallback: check directly
    try:
        from streamlit.auth_util import get_secrets_auth_section
        section = get_secrets_auth_section()
        return bool(section and section.get("client_id"))
    except Exception:
        return False


# ── Singleton Supabase client ─────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def get_supabase_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("❌ SUPABASE_URL and SUPABASE_KEY must be set in .env")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ── Session helpers ───────────────────────────────────────────────────────────
def _set_session(user, session):
    st.session_state["sb_user"]    = user
    st.session_state["sb_session"] = session
    st.session_state["sb_email"]   = getattr(user, "email", "") or ""


def _clear_session():
    for key in ("sb_user", "sb_session", "sb_email"):
        st.session_state.pop(key, None)


def _purge_stale_widget_keys():
    """Remove stale internal widget IDs that cause KeyErrors after server restarts."""
    for key in list(st.session_state.keys()):
        if key.startswith("$$WIDGET_ID"):
            st.session_state.pop(key, None)


# ── Authentication check ──────────────────────────────────────────────────────
def is_authenticated() -> bool:
    _purge_stale_widget_keys()

    # Check Supabase session
    if st.session_state.get("sb_user") is not None:
        return True

    # Check Streamlit Google OAuth session (st.experimental_user)
    try:
        u = _get_st_user()
        if u is not None:
            return bool(getattr(u, "is_logged_in", False))
    except Exception:
        pass

    return False


# ── Sign-in ───────────────────────────────────────────────────────────────────
def _do_sign_in(email: str, password: str) -> bool:
    sb = get_supabase_client()
    try:
        resp = sb.auth.sign_in_with_password({"email": email, "password": password})
        _set_session(resp.user, resp.session)
        # Register user in local/production databases
        _register_user_in_db(email)
        return True
    except AuthApiError as e:
        msg = e.message or str(e)
        if "invalid login credentials" in msg.lower():
            st.error(
                "❌ **Invalid email or password.**\n\n"
                "If you just signed up, you must **click the confirmation link** "
                "sent to your inbox before you can sign in."
            )
        elif "email not confirmed" in msg.lower():
            st.warning(
                "📧 **Email not confirmed.**\n\n"
                "Check your inbox for a confirmation email and click the link, "
                "then try again."
            )
        else:
            st.error(f"Sign-in failed: {msg}")
        return False
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return False


# ── Sign-up ───────────────────────────────────────────────────────────────────
def _do_sign_up(email: str, password: str) -> bool:
    sb = get_supabase_client()
    try:
        resp = sb.auth.sign_up({"email": email, "password": password})

        if resp.user is None:
            st.error("This email may already be registered. Try Sign In instead.")
            return False

        # Register user in local/production databases
        _register_user_in_db(email)

        if resp.user.confirmed_at or resp.user.email_confirmed_at:
            # Supabase auto-confirm is enabled
            if resp.session:
                _set_session(resp.user, resp.session)
                st.success("✅ Account created and signed in!")
            else:
                st.success("✅ Account created! Please sign in.")
        else:
            # Email confirmation required (Supabase default)
            st.success(
                f"✅ **Account created!**\n\n"
                f"📧 A confirmation email was sent to **{email}**.\n\n"
                "Click the link in the email, then come back and **Sign In**. "
                "Check your spam folder if you don't see it."
            )
            st.session_state["pending_confirm_email"] = email
        return True

    except AuthApiError as e:
        msg = e.message or str(e)
        if "already registered" in msg.lower():
            st.warning("⚠️ This email is already registered. Use Sign In instead.")
        elif "rate limit" in msg.lower():
            st.error("Too many requests. Please wait a minute and try again.")
        else:
            st.error(f"Sign-up failed: {msg}")
        return False
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return False


# ── Password reset ────────────────────────────────────────────────────────────
def _do_reset_password(email: str) -> bool:
    email_clean = str(email or "").strip().lower()
    if not _is_user_registered(email_clean):
        st.error("This email address is not registered. Please sign up first.")
        return False

    sb = get_supabase_client()
    try:
        # Determine redirect URL for recovery redirect back to application
        redirect_uri = os.getenv("STREAMLIT_REDIRECT_URL", "http://localhost:8501")
        redirect_uri = redirect_uri.rstrip("/")
        sb.auth.reset_password_for_email(email_clean, options={"redirect_to": f"{redirect_uri}/"})
        st.success(f"📧 Password reset email sent to **{email_clean}**. Check your inbox.")
        return True
    except AuthApiError as e:
        st.error(f"Reset failed: {e.message}")
        return False
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return False


# ── Sign-out ──────────────────────────────────────────────────────────────────
def do_sign_out():
    sb = get_supabase_client()
    try:
        sb.auth.sign_out()
    except Exception:
        pass
    _clear_session()

    # Handle Google OAuth logout
    try:
        u = _get_st_user()
        if u is not None and getattr(u, "is_logged_in", False):
            if hasattr(st, "logout"):
                st.logout()
                return
    except Exception:
        pass

    st.rerun()


# ── Google OAuth ──────────────────────────────────────────────────────────────
def _do_google_login():
    """Trigger Streamlit's built-in OIDC login flow."""
    try:
        st.login()   # Streamlit 1.38+ — redirects browser to Google
        st.stop()
    except Exception as e:
        err = str(e)
        if "client_id" in err or "secrets" in err.lower():
            st.error(
                "**Google OAuth not configured correctly.**\n\n"
                "The `client_id` in `.streamlit/secrets.toml` may be wrong, or "
                "the redirect URI is not registered in Google Cloud Console.\n\n"
                "Please use email/password sign-in instead."
            )
        elif "authlib" in err.lower():
            st.error("Missing dependency: `pip install Authlib>=1.3.2`")
        else:
            st.error(f"Google sign-in error: {err}")


# ── Main auth page ────────────────────────────────────────────────────────────
def render_auth_page():
    """Renders the full-page login / register form or recovery form."""
    # 1. Inject client-side hash to query string redirect hack
    st.markdown("""
    <img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" onerror='
        (function() {
            try {
                var loc = window.parent && window.parent.location ? window.parent.location : window.location;
                var parentHash = loc.hash;
                if (parentHash && (parentHash.indexOf("access_token=") !== -1 || parentHash.indexOf("type=recovery") !== -1)) {
                    var cleanHash = parentHash.substring(1);
                    var parentSearch = loc.search;
                    var separator = parentSearch ? "&" : "?";
                    var newUrl = loc.origin + loc.pathname + parentSearch + separator + cleanHash;
                    loc.hash = "";
                    loc.href = newUrl;
                }
            } catch(e) {
                console.error("CDP Reset Redirect error: ", e);
            }
        })();
    ' style="display:none;"/>
    """, unsafe_allow_html=True)

    # 2. Check query params for recovery mode
    query_params = st.query_params
    access_token = query_params.get("access_token")
    refresh_token = query_params.get("refresh_token")
    mode_type = query_params.get("type")

    if access_token or mode_type == "recovery":
        # Centred recovery card
        _, col, _ = st.columns([1, 1.8, 1])
        with col:
            st.markdown("""
            <div style="text-align:center; padding-top:40px; margin-bottom:28px;">
                <h2 style="color:#e6edf3; margin:0 0 8px 0;
                           font-family:Inter,sans-serif; font-weight:700;
                           font-size:1.8rem; letter-spacing:-0.02em;">
                    Reset Your Password
                </h2>
                <p style="color:#8b949e; font-family:Inter,sans-serif; font-size:0.92rem; line-height:1.45; margin:8px auto 0 auto; max-width:420px; font-weight:400;">
                    Please enter your new password below to secure and update your account.
                </p>
            </div>
            """, unsafe_allow_html=True)
            
            with st.form("recovery_form", clear_on_submit=True):
                new_pass = st.text_input(
                    "New Password", type="password",
                    placeholder="Min 6 characters", key="rec_pass"
                )
                new_pass_confirm = st.text_input(
                    "Confirm New Password", type="password",
                    placeholder="Repeat new password", key="rec_pass_confirm"
                )
                submitted_rec = st.form_submit_button(
                    "Update Password & Sign In", use_container_width=True
                )
                
            if submitted_rec:
                if not new_pass:
                    st.warning("Please enter a new password.")
                elif len(new_pass) < 6:
                    st.warning("Password must be at least 6 characters.")
                elif new_pass != new_pass_confirm:
                    st.error("Passwords do not match.")
                else:
                    with st.spinner("Updating password…"):
                        try:
                            sb = get_supabase_client()
                            tok = str(access_token).strip()
                            ref = str(refresh_token or "").strip()
                            
                            sb.auth.set_session(tok, ref)
                            sb.auth.update_user({"password": new_pass})
                            sb.auth.sign_out()
                            
                            try:
                                st.query_params.clear()
                            except Exception:
                                for key in list(st.query_params.keys()):
                                    del st.query_params[key]
                                    
                            st.success("✅ Password updated successfully! Please Sign In with your new password.")
                            time.sleep(3)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to update password: {e}")
        return

    try:
        # Centred card
        _, col, _ = st.columns([1, 1.8, 1])
        with col:

            # ── Header ────────────────────────────────────────────────────────
            st.markdown("""
            <style>
            .google-btn-wrapper button {
                background-image: url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgd2lkdGg9IjI0IiBoZWlnaHQ9IjI0Ij48cGF0aCBmaWxsPSIjNDI4NUY0IiBkPSJNMjIuNTYgMTIuMjVjMC0uNzgtLjA3LTEuNTMtLjItMi4yNUgxMnY0LjI2aDUuOTJjLS4yNiAxLjM3LTEuMDQgMi41My0yLjIxIDMuMzF2Mi43N2gzLjU3YzIuMDgtMS45MiAzLjI4LTQuNzQgMy4yOC04LjA5eiIvPjxwYXRoIGZpbGw9IiMzNEE4NTMiIGQ9Ik0xMiAyM2MyLjk3IDAgNS40Ni0uOTggNy4yOC0yLjY2bC0zLjU3LTIuNzdjLS45OC42Ni0yLjIzIDEuMDYtMy43IDEuMDYtMi44NiAwLTUuMjktMS45My02LjE2LTQuNTNIMi4xOHYyLjg0QzMuOTkgMjAuNTMgNy43IDIzIDEyIDIzemIvPjxwYXRoIGZpbGw9IiNGQkJDMDUiIGQ9Ik01Ljg0IDE0LjA5Yy0uMjItLjY2LS4zNS0xLjM2LS4zNS0yLjA5cy4xMy0xLjQzLjM1LTIuMDlWNy4wNkgyLjE4QzEuNDMgOC41NSAxIDEwLjIyIDEgMTJzLjQzIDMuNDUgMS4xOCA0Ljk0bDIuODUtMi4yMmMtLjIyLS42Ni0uMzUtMS4zNi0uMzUtMi4wOXoiLz48cGF0aCBmaWxsPSIjRUE0MzM1IiBkPSJNMTIgNS4zOGMxLjYyIDAgMy4wNi41NiA0LjIxIDEuNjRsMy4xNS0zLjE1QzE3LjQ1IDIuMDkgMTQuOTcgMSAxMiAxIDcuNyAxIDMuOTkgMy40NyAyLjE4IDcuMDZsMy42NiAyLjg0Yy44Ny0yLjYgMy4zLTQuNTIgNi4xNi00LjUyeiIvPjwvc3ZnPg==') !important;
                background-repeat: no-repeat !important;
                background-position: 16px 50% !important;
                background-size: 18px 18px !important;
                padding-left: 48px !important;
                height: 42px !important;
                border: 1px solid #30363d !important;
                border-radius: 6px !important;
                background-color: #21262d !important;
                color: #c9d1d9 !important;
                font-weight: 500 !important;
                transition: all 0.2s ease !important;
            }
            .google-btn-wrapper button:hover {
                background-image: url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgd2lkdGg9IjI0IiBoZWlnaHQ9IjI0Ij48cGF0aCBmaWxsPSIjNDI4NUY0IiBkPSJNMjIuNTYgMTIuMjVjMC0uNzgtLjA3LTEuNTMtLjItMi4yNUgxMnY0LjI2aDUuOTJjLS4yNiAxLjM3LTEuMDQgMi41My0yLjIxIDMuMzF2Mi43N2gzLjU3YzIuMDgtMS45MiAzLjI4LTQuNzQgMy4yOC04LjA5eiIvPjxwYXRoIGZpbGw9IiMzNEE4NTMiIGQ9Ik0xMiAyM2MyLjk3IDAgNS40Ni0uOTggNy4yOC0yLjY2bC0zLjU3LTIuNzdjLS45OC42Ni0yLjIzIDEuMDYtMy43IDEuMDYtMi44NiAwLTUuMjktMS45My02LjE2LTQuNTNIMi4xOHYyLjg0QzMuOTkgMjAuNTMgNy43IDIzIDEyIDIzemIvPjxwYXRoIGZpbGw9IiNGQkJDMDUiIGQ9Ik01Ljg0IDE0LjA5Yy0uMjItLjY2LS4zNS0xLjM2LS4zNS0yLjA5cy4xMy0xLjQzLjM1LTIuMDlWNy4wNkgyLjE4QzEuNDMgOC41NSAxIDEwLjIyIDEgMTJzLjQzIDMuNDUgMS4xOCA0Ljk0bDIuODUtMi4yMmMtLjIyLS42Ni0uMzUtMS4zNi0uMzUtMi4wOXoiLz48cGF0aCBmaWxsPSIjRUE0MzM1IiBkPSJNMTIgNS4zOGMxLjYyIDAgMy4wNi45NiA0LjIxIDEuNjRsMy4xNS0zLjE1QzE3LjkzIDIuMDkgMTQuOTcgMSAxMiAxIDcuNyAxIDMuOTkgMy40NyAyLjE4IDcuMDZsMy42NiAyLjg0Yy44Ny0yLjYgMy4zLTQuNTIgNi4xNi00LjUyeiIvPjwvc3ZnPg==') !important;
                background-repeat: no-repeat !important;
                background-position: 16px 50% !important;
                background-size: 18px 18px !important;
                background-color: #30363d !important;
                border-color: #8b949e !important;
                color: #ffffff !important;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15) !important;
            }
            .or-separator {
                display: flex;
                align-items: center;
                text-align: center;
                margin: 24px 0 16px 0;
            }
            .or-separator::before,
            .or-separator::after {
                content: '' !important;
                flex: 1 !important;
                border-bottom: 1px solid #30363d !important;
            }
            .or-separator:not(:empty)::before {
                margin-right: 1.2em !important;
            }
            .or-separator:not(:empty)::after {
                margin-left: 1.2em !important;
            }
            .or-text {
                color: #8b949e !important;
                font-size: 0.78rem !important;
                font-weight: 600 !important;
                text-transform: uppercase !important;
                letter-spacing: 0.12em !important;
            }
            </style>
            
            <div style="text-align:center; padding-top:40px; margin-bottom:28px;">
                <h2 style="color:#e6edf3; margin:0 0 8px 0;
                           font-family:Inter,sans-serif; font-weight:700;
                           font-size:1.8rem; letter-spacing:-0.02em;">
                    Claim Denial Prevention
                </h2>
                <p style="color:#8b949e; font-family:Inter,sans-serif; font-size:0.92rem; line-height:1.45; margin:8px auto 0 auto; max-width:420px; font-weight:400;">
                    An advanced predictive analytics and policy validation engine designed to identify, analyze, and prevent healthcare claim denials before submission.
                </p>
            </div>
            """, unsafe_allow_html=True)

            # ── Google OAuth button ───────────────────────────────────────────
            google_configured = _is_google_auth_configured()
            if google_configured:
                col_g1, col_g2, col_g3 = st.columns([0.08, 0.84, 0.08])
                with col_g2:
                    st.markdown('<div class="google-btn-wrapper">', unsafe_allow_html=True)
                    if st.button(
                        "Continue with Google",
                        key="google_login_btn",
                        use_container_width=True,
                        type="secondary",
                    ):
                        _do_google_login()
                    st.markdown('</div>', unsafe_allow_html=True)

                st.markdown(
                    "<div class='or-separator'><span class='or-text'>or</span></div>",
                    unsafe_allow_html=True
                )

            # ── Tabs ──────────────────────────────────────────────────────────
            tab_in, tab_up, tab_reset = st.tabs(["Sign In", "Sign Up", "Forgot Password"])

            # Sign In
            with tab_in:
                default_email = st.session_state.get("pending_confirm_email", "")
                with st.form("signin_form", clear_on_submit=False):
                    email = st.text_input(
                        "Email", value=default_email,
                        placeholder="you@example.com", key="si_email"
                    )
                    password = st.text_input(
                        "Password", type="password",
                        placeholder="••••••••", key="si_pass"
                    )
                    submitted = st.form_submit_button(
                        "Sign In →", use_container_width=True
                    )
                if submitted:
                    if not email or not password:
                        st.warning("Please enter email and password.")
                    else:
                        with st.spinner("Authenticating…"):
                            ok = _do_sign_in(email.strip(), password)
                        if ok:
                            st.session_state.pop("pending_confirm_email", None)
                            st.rerun()

            # Sign Up
            with tab_up:
                st.caption(
                    "After sign-up, Supabase will send a confirmation email. "
                    "Click the link before signing in."
                )
                with st.form("signup_form", clear_on_submit=True):
                    su_email = st.text_input(
                        "Email", placeholder="you@gmail.com", key="su_email"
                    )
                    su_pass = st.text_input(
                        "Password", type="password",
                        placeholder="Min 6 characters", key="su_pass"
                    )
                    su_pass2 = st.text_input(
                        "Confirm Password", type="password",
                        placeholder="Repeat password", key="su_pass2"
                    )
                    submitted_up = st.form_submit_button(
                        "Create Account →", use_container_width=True
                    )
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

            # Forgot Password
            with tab_reset:
                st.caption("Enter your email and we'll send a password reset link.")
                with st.form("reset_form", clear_on_submit=True):
                    reset_email = st.text_input(
                        "Email", placeholder="you@example.com", key="reset_email"
                    )
                    submitted_reset = st.form_submit_button(
                        "Send Reset Link", use_container_width=True
                    )
                if submitted_reset:
                    if not reset_email:
                        st.warning("Please enter your email.")
                    else:
                        with st.spinner("Sending…"):
                            _do_reset_password(reset_email.strip())

    except KeyError:
        # Self-healing: stale widget IDs from server restart — wipe and reload
        st.session_state.clear()
        st.rerun()


# ── Sidebar user badge ────────────────────────────────────────────────────────
def render_user_sidebar():
    """Renders compact user badge + Sign Out button in the sidebar."""
    google_logged_in = False
    google_email = ""
    try:
        u = _get_st_user()
        if u is not None:
            google_logged_in = bool(getattr(u, "is_logged_in", False))
            if google_logged_in:
                google_email = getattr(u, "email", "") or ""
    except Exception:
        pass

    if google_logged_in:
        email    = google_email
        uid      = "Google"
        provider = "GOOGLE"
    else:
        email    = st.session_state.get("sb_email", "")
        user     = st.session_state.get("sb_user")
        uid      = getattr(user, "id", "")[:8] if user else ""
        provider = "SUPABASE"

    st.sidebar.markdown(f"""
    <div style="background:#1c2128; border:1px solid #30363d;
                border-radius:10px; padding:12px 14px; margin-bottom:12px;">
        <div style="color:#3fb950; font-size:0.75rem; font-weight:600; margin-bottom:4px;">
            ● SIGNED IN ({provider})
        </div>
        <div style="color:#e6edf3; font-size:0.86rem; word-break:break-all;">{email}</div>
        <div style="color:#8b949e; font-size:0.70rem; margin-top:2px;">uid: {uid}…</div>
    </div>
    """, unsafe_allow_html=True)

    if st.sidebar.button("Sign Out", use_container_width=True):
        do_sign_out()
