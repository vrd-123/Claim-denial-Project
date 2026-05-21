"""
app.py — Week 8 Production Streamlit UI
Calls FastAPI backend for all ML/RAG/Agent operations.
"""

import os
import requests
import streamlit as st
import pandas as pd
from datetime import datetime, date
from databricks import sql as dbsql
from dotenv import load_dotenv
from auth import render_auth_page, render_user_sidebar, is_authenticated

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────
API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
DB_HOST  = os.getenv("DATABRICKS_HOST", "")
DB_PATH  = os.getenv("DATABRICKS_HTTP_PATH", "")
DB_TOKEN = os.getenv("DATABRICKS_TOKEN", "")

st.set_page_config(
    page_title="Claim Denial Prevention",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.main { background: #0d1117; color: #e6edf3; }
[data-testid="stSidebar"] { background: #161b22; border-right: 1px solid #30363d; }
[data-testid="stSidebar"] * { color: #e6edf3 !important; }

.metric-card {
    background: linear-gradient(135deg, #1c2128, #21262d);
    border: 1px solid #30363d;
    border-radius: 12px;
    padding: 20px 24px;
    margin: 6px 0;
}
.metric-value { font-size: 2.2rem; font-weight: 700; color: #58a6ff; }
.metric-label { font-size: 0.85rem; color: #8b949e; margin-top: 4px; }

.risk-CRITICAL { background: linear-gradient(135deg,#3d1f1f,#2d1b1b); border: 1px solid #f85149; border-radius:10px; padding:16px; }
.risk-HIGH     { background: linear-gradient(135deg,#2d2416,#261e10); border: 1px solid #d29922; border-radius:10px; padding:16px; }
.risk-MEDIUM   { background: linear-gradient(135deg,#1d2d3e,#162032); border: 1px solid #388bfd; border-radius:10px; padding:16px; }
.risk-LOW      { background: linear-gradient(135deg,#1b2f23,#162219); border: 1px solid #3fb950; border-radius:10px; padding:16px; }

.reason-card {
    background: #1c2128;
    border: 1px solid #30363d;
    border-left: 4px solid #58a6ff;
    border-radius: 8px;
    padding: 14px 18px;
    margin: 8px 0;
}
.wizard-step {
    background: #1c2128;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 18px 22px;
    margin: 10px 0;
}
.step-number {
    background: #58a6ff;
    color: #0d1117;
    border-radius: 50%;
    width: 28px; height: 28px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    margin-right: 10px;
}
.policy-box {
    background: #0d1117;
    border: 1px solid #58a6ff33;
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 0.85rem;
    color: #8b949e;
    font-family: monospace;
    margin-top: 8px;
}
div.stButton > button {
    background: linear-gradient(135deg, #238636, #2ea043);
    color: white;
    border: none;
    border-radius: 8px;
    padding: 8px 20px;
    font-weight: 600;
    transition: all 0.2s;
}
div.stButton > button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px #2ea04355; }
.stTextInput > div > div > input,
.stNumberInput > div > div > input,
.stDateInput > div > div > input {
    background: #1c2128 !important;
    color: #e6edf3 !important;
    border: 1px solid #30363d !important;
    border-radius: 8px !important;
}
</style>
""", unsafe_allow_html=True)


# ── API Helpers ────────────────────────────────────────────────────────────────
def call_predict(payload: dict) -> dict:
    try:
        r = requests.post(f"{API_BASE}/predict-claim", json=payload, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error(f"[CDP-001-005] Cannot connect to FastAPI at {API_BASE}. Is the server running?")
        return {}
    except requests.exceptions.Timeout:
        st.error("[CDP-001-004] Request timed out after 30s.")
        return {}
    except Exception as e:
        st.error(f"[CDP-001-005] API error: {e}")
        return {}


def call_lookup(claim_id: str) -> dict:
    try:
        r = requests.get(f"{API_BASE}/claim/{claim_id}", timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"[CDP-005-002] Lookup error: {e}")
        return {}


def call_health() -> dict:
    try:
        r = requests.get(f"{API_BASE}/health", timeout=5)
        return r.json()
    except Exception:
        return {"status": "unreachable", "models_loaded": False, "rag_loaded": False}


def call_metrics() -> dict:
    try:
        r = requests.get(f"{API_BASE}/metrics", timeout=5)
        return r.json()
    except Exception:
        return {}


def get_db_conn():
    if not DB_HOST or not DB_TOKEN:
        return None
    try:
        return dbsql.connect(server_hostname=DB_HOST, http_path=DB_PATH, access_token=DB_TOKEN)
    except Exception:
        return None


import sqlite3
import datetime
import json as _json

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


def get_logged_in_user_email() -> str:
    """Canonical user identity — always prefer the Supabase session key set by auth.py.
    Falls back to Streamlit native auth (Google SSO), then to 'unknown' if neither is present.
    Never returns a hardcoded personal name — 'unknown' keeps misattributed rows findable.
    """
    # 1. Supabase session (set by auth.py _set_session → sb_email)
    sb_email = st.session_state.get("sb_email", "")
    if sb_email:
        return sb_email
    # 2. Streamlit native auth (Google SSO via st.login())
    if hasattr(st, "user"):
        try:
            if st.user.is_logged_in and st.user.email:
                return st.user.email
        except Exception:
            pass
    # 3. Fallback — claim will be stored but scoped to 'unknown' so it surfaces in debug
    return "unknown"


def _log_audit_trail(claim_id, action, details=None):
    try:
        import datetime as dt_mod
        conn = _get_db_conn()
        cur = conn.cursor()
        user_email = get_logged_in_user_email()
        timestamp = dt_mod.datetime.now(dt_mod.timezone.utc).isoformat()
        
        cur.execute("""
            INSERT INTO audit_trail (claim_id, user_email, action, timestamp, details)
            VALUES (?, ?, ?, ?, ?)
        """, (claim_id, user_email, action, timestamp, details))
        conn.commit()
        conn.close()
    except Exception as e:
        import logging
        logging.error(f"Failed to log audit trail: {e}")


def _save_claim_history(claim_id, outcome, prob, risk, result_dict, billed_amt, exp_c, proc, diag, prov, svc_date=None, pol_id=None, pat_id=None):
    """Persist one claim adjudication result to claim_history.db.

    Normalization rules (architecture spec §2.3):
      N-1: claim_id is always stored as strip().upper() — prevents 'saved but not found' bugs.
      N-2: service_date is always stored as plain YYYY-MM-DD — no time component.
      N-3: submitted_by comes from the authenticated session, never a hardcoded default.
    """
    try:
        # N-1 — Normalize claim_id to uppercase before any DB operation
        claim_id_norm = str(claim_id or "").strip().upper()

        import datetime as dt_mod
        # N-3 — User identity from session (set by auth.py after Supabase/Google sign-in)
        submitted_by = get_logged_in_user_email()
        submitted_at = dt_mod.datetime.now(dt_mod.timezone.utc).isoformat()

        predicted_status = result_dict.get("predicted_status", "APPROVED")
        error_codes = _json.dumps(result_dict.get("violations", []), default=str) if outcome == "RULE_DENY" else None
        reasons = result_dict.get("reasons", [])
        primary_reason = reasons[0]["explanation"] if reasons else None
        recommendation = ("Fix rule violations before ML inference."
                          if outcome == "RULE_DENY"
                          else result_dict.get("recommendation", ""))
        full_response = _json.dumps(result_dict, default=str)
        billing_ratio = (billed_amt / exp_c) if (exp_c and exp_c > 0 and billed_amt) else 0.0
        ml_called = 0 if outcome == "RULE_DENY" else 1

        # N-2 — Normalize service_date to plain YYYY-MM-DD (strip any time component)
        if svc_date is not None:
            import datetime as dt_mod
            if isinstance(svc_date, dt_mod.datetime):
                svc_date_str = svc_date.date().isoformat()
            elif isinstance(svc_date, dt_mod.date):
                svc_date_str = svc_date.isoformat()
            else:
                # handles ISO strings like "2024-03-15T00:00:00" or "2024-03-15 00:00:00"
                svc_date_str = str(svc_date).strip().split("T")[0].split(" ")[0]
        else:
            svc_date_str = None

        conn = _get_db_conn()
        cur  = conn.cursor()

        # Check resubmission BEFORE the INSERT so the count is accurate
        existing_count = cur.execute(
            "SELECT COUNT(*) FROM claim_history WHERE claim_id = ? AND submitted_by = ?",
            (claim_id_norm, submitted_by)
        ).fetchone()[0]
        audit_action = "Resubmitted claim" if existing_count > 0 else "Submitted claim"

        cur.execute("""
            INSERT INTO claim_history
            (claim_id, submitted_by, submitted_at, predicted_status, risk_level, denial_prob,
             error_codes, primary_reason, recommendation, ml_called, full_response,
             billing_ratio, billed_amount, procedure_code, diagnosis_code, provider_id,
             service_date, policy_id, patient_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (claim_id_norm, submitted_by, submitted_at, predicted_status, risk, prob,
               error_codes, primary_reason, recommendation, ml_called, full_response,
               billing_ratio, billed_amt, proc, diag, prov,
               svc_date_str, pol_id, pat_id))

        # Log to audit_trail in the same transaction
        cur.execute("""
            INSERT INTO audit_trail (claim_id, user_email, action, timestamp, details)
            VALUES (?, ?, ?, ?, ?)
        """, (claim_id_norm, submitted_by, audit_action, submitted_at,
               f"Outcome: {outcome}, Risk: {risk}, Status: {predicted_status}"))

        conn.commit()
        conn.close()

    except Exception as e:
        import logging
        logging.error(f"Failed to save claim history: {e}")
        # N-3 — Surface failure so analyst knows the audit trail write failed (spec §2.4)
        st.warning(
            f"⚠️ Audit trail write failed for claim `{claim_id}`. "
            f"This result will NOT appear in the Audit Trail. Error: `{e}`"
        )


def risk_color(level: str) -> str:
    return {"CRITICAL": "#f85149", "HIGH": "#d29922", "MEDIUM": "#388bfd", "LOW": "#3fb950"}.get(level, "#8b949e")


def _claim_content_hash(provider_id, diagnosis_code, procedure_code, billed_amount, service_date, policy_id, patient_id):
    """Stable hash of the business-meaningful fields. Claim ID is NOT part of the hash,
    so a corrected resubmission with the same ID but different fields is always treated as NEW."""
    import hashlib
    amt_str = f"{float(billed_amount or 0):.2f}"
    raw = "|".join([
        str(provider_id or "").strip().upper(),
        str(diagnosis_code or "").strip().upper(),
        str(procedure_code or "").strip().upper(),
        amt_str,
        str(service_date or "").strip(),
        str(policy_id or "").strip().upper(),
        str(patient_id or "").strip().upper(),
    ])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _check_duplicate_claim(claim_id, provider_id, diagnosis_code, procedure_code,
                           billed_amount, service_date=None, policy_id=None, patient_id=None):
    """
    Checks for duplicates in the claim history database.
    Returns (status, message, existing_row).
    status:
      'ENTIRE_DUPLICATE' – exactly the same clinical & billing fields already processed in ANY claim ID → block submission.
      'DUPLICATE_ID'     – same claim_id but different content (corrected resubmission) → allow.
      'NEW'              – no duplicates found → allow.
    """
    try:
        conn = _get_db_conn()
        conn.row_factory = sqlite3.Row
        
        # 1. Check if there exists ANY claim in history with the exact same data fields (all fields same)
        # regardless of claim_id. This prevents waste of compute on identical duplicate claims.
        sql = """
            SELECT * FROM claim_history 
            WHERE 
                (provider_id = ? OR (provider_id IS NULL AND ? IS NULL)) AND
                (diagnosis_code = ? OR (diagnosis_code IS NULL AND ? IS NULL)) AND
                (procedure_code = ? OR (procedure_code IS NULL AND ? IS NULL)) AND
                (billed_amount = ? OR (billed_amount IS NULL AND ? IS NULL)) AND
                (service_date = ? OR (service_date IS NULL AND ? IS NULL)) AND
                (policy_id = ? OR (policy_id IS NULL AND ? IS NULL)) AND
                (patient_id = ? OR (patient_id IS NULL AND ? IS NULL))
            ORDER BY submitted_at DESC LIMIT 1
        """
        params = (
            provider_id.strip() if provider_id else None, provider_id.strip() if provider_id else None,
            diagnosis_code.strip() if diagnosis_code else None, diagnosis_code.strip() if diagnosis_code else None,
            procedure_code.strip() if procedure_code else None, procedure_code.strip() if procedure_code else None,
            float(billed_amount) if billed_amount is not None else None, float(billed_amount) if billed_amount is not None else None,
            str(service_date).strip() if service_date else None, str(service_date).strip() if service_date else None,
            policy_id.strip() if policy_id else None, policy_id.strip() if policy_id else None,
            patient_id.strip() if patient_id else None, patient_id.strip() if patient_id else None
        )
        
        exact_match = conn.execute(sql, params).fetchone()
        
        if exact_match:
            conn.close()
            matched_id = exact_match["claim_id"]
            if matched_id == claim_id.strip():
                return "ENTIRE_DUPLICATE", (
                    f"An identical claim with ID '{claim_id}' was already processed "
                    f"on {exact_match['submitted_at']} (status: {exact_match['predicted_status']})."
                ), exact_match
            else:
                return "ENTIRE_DUPLICATE", (
                    f"An identical claim with a different ID "
                    f"('{matched_id}') has already been processed on {exact_match['submitted_at']} "
                    f"with status '{exact_match['predicted_status']}'."
                ), exact_match

        # 2. Check if the claim ID matches a prior submission but with different data fields
        # (interpreted as a corrected resubmission).
        id_match = conn.execute(
            "SELECT * FROM claim_history WHERE claim_id = ? ORDER BY submitted_at DESC LIMIT 1",
            (claim_id.strip(),)
        ).fetchone()
        conn.commit()
        conn.close()
        
        if id_match:
            return "DUPLICATE_ID", (
                f"Claim ID '{claim_id}' was previously processed on {id_match['submitted_at']} "
                f"with status '{id_match['predicted_status']}', but fields have changed — "
                "treating as corrected resubmission."
            ), id_match
            
    except Exception as e:
        import logging
        logging.error(f"Error checking duplicate claim: {e}")
    return "NEW", "", None


def _compute_granular_outcome(ml_status: str, denial_prob: float,
                              billing_verdict: str) -> tuple:
    """
    Maps the ML binary output (APPROVED / DENIED) + billing signals
    to one of 5 operational decision levels.
    The ML model's raw output is NEVER changed — this is a pure
    presentation/workflow layer on top of it.

    Returns (granular_outcome, base_decision)
      granular_outcome : one of the 5 level strings below
      base_decision    : 'APPROVED' or 'DENIED'  ← ML model raw output

    Decision ladder (prob = denial probability 0-1):
      APPROVED              → ML=APPROVED,  prob < 0.20, no billing flag
      APPROVED_WITH_WARNING → ML=APPROVED,  prob < 0.35  OR billing flag
      MANUAL_REVIEW         → ML=APPROVED,  0.35 ≤ prob < 0.50
                              OR ML=DENIED,  0.50 ≤ prob < 0.65
      AT_RISK               → ML=DENIED,    0.65 ≤ prob < 0.80
      HOLD_FOR_CORRECTION   → ML=DENIED,    prob ≥ 0.80
                              (RULE_DENY is passed directly, maps here)
    """
    base = ml_status  # 'APPROVED' or 'DENIED'

    if ml_status == "APPROVED":
        # If billing verdict is CONDITIONAL (high pricing 1.25x-1.75x but not rule-deny),
        # and ML predicted APPROVED, force MANUAL_REVIEW as requested by the user
        if billing_verdict == "CONDITIONAL":
            return "MANUAL_REVIEW", base
        if billing_verdict in ("FLAG_LOW", "FLAG_VERY_LOW", "FLAG_HIGH_WARN", "FLAG_LOW_WARN"):
            return "APPROVED_WITH_WARNING", base
        if denial_prob < 0.20:
            return "APPROVED", base
        if denial_prob < 0.35:
            return "APPROVED_WITH_WARNING", base
        # prob 0.35-0.50 while model still says APPROVED → borderline
        return "MANUAL_REVIEW", base
    else:  # DENIED
        if denial_prob < 0.65:
            return "MANUAL_REVIEW", base
        if denial_prob < 0.80:
            return "AT_RISK", base
        return "HOLD_FOR_CORRECTION", base


# ── Load provider/diagnosis/cost reference data (module-level cache) ──────────
import csv as _csv
_RAW_PATH = "data/raw"

def _load_ref(filepath, key_col, extra_cols=None):
    rows = {}
    try:
        with open(filepath, newline="") as f:
            for row in _csv.DictReader(f):
                k = row[key_col].strip()
                if extra_cols:
                    rows[k] = {c: row.get(c, "").strip() for c in extra_cols}
                else:
                    rows[k] = k
    except Exception:
        pass
    return rows

_PROV_DATA  = _load_ref(f"{_RAW_PATH}/providers_1000.csv", "provider_id",
                         ["doctor_name","specialty","location"])
_DIAG_DATA  = _load_ref(f"{_RAW_PATH}/diagnosis.csv",      "diagnosis_code",
                         ["category","severity"])
_COST_DATA  = _load_ref(f"{_RAW_PATH}/cost.csv",           "procedure_code",
                         ["expected_cost","region"])
_POLICY_DATA= _load_ref(f"{_RAW_PATH}/policies.csv",       "policy_id",
                         ["policy_name", "procedures_covered", "policy_start_date", "policy_end_date"])

SHAP_LABEL = {
    "billing_ratio":        "Billed amount vs. expected cost",
    "cost_diff":            "Cost gap (billed − expected)",
    "high_cost_flag":       "High-cost claim flag",
    "provider_claim_count": "Provider historical volume",
    "provider_specialty_enc":"Provider specialty risk",
    "severity_score":       "Diagnosis severity level",
    "diag_claim_count":     "Diagnosis claim frequency",
    "diag_category_enc":    "Diagnosis category",
    "is_billed_missing":    "Completeness: billed amount",
    "is_proc_missing":      "Completeness: procedure code",
    "is_diag_missing":      "Completeness: diagnosis code",
    "claim_age_days":       "Claim submission timeliness",
}


def _render_claim_summary(claim_id, patient_id, provider_id, diag_code, proc_code,
                           billed_amt, exp_c, svc_date):
    prov_info  = _PROV_DATA.get(provider_id, {})
    diag_info  = _DIAG_DATA.get(diag_code, {})
    cost_info  = _COST_DATA.get(proc_code, {})
    ratio_pct  = f"{billed_amt/exp_c*100:.0f}%" if (proc_code and exp_c > 0 and billed_amt is not None) else "N/A"
    exp_str    = f"₹{exp_c:,.0f}" if proc_code else "—"
    ratio_str  = ratio_pct if proc_code else "—"
    prov_label = f"{prov_info.get('doctor_name','—')} ({prov_info.get('specialty','—')})" if prov_info else (provider_id or "—")
    diag_label = f"{diag_code} — {diag_info.get('category','?')} (Severity: {diag_info.get('severity','?')})" if diag_info else (diag_code or "—")
    region     = cost_info.get("region", "—") if cost_info else "—"
    billed_str = f"₹{billed_amt:,.0f}" if billed_amt is not None else "—"
    date_str   = svc_date.isoformat() if svc_date else "—"
    st.markdown(f"""
<div style="background:#1c2128;border:1px solid #30363d;border-radius:12px;padding:16px 20px;margin:10px 0">
<b style="color:#58a6ff">CLAIM SUMMARY</b>
<span style="float:right;color:#8b949e;font-size:0.9rem">{claim_id}</span><br>
<hr style="border-color:#30363d;margin:8px 0">
<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:0.9rem">
  <span><b>Patient:</b> {patient_id or '—'}</span>
  <span><b>Provider:</b> {prov_label}</span>
  <span><b>Diagnosis:</b> {diag_label}</span>
  <span><b>Procedure:</b> {proc_code or '—'} &nbsp; Region: {region}</span>
  <span><b>Billed:</b> {billed_str}</span>
  <span><b>Expected:</b> {exp_str} &nbsp; Ratio: {ratio_str}</span>
  <span><b>Date:</b> {date_str}</span>
</div></div>""", unsafe_allow_html=True)



def _determine_denial_category(reasons, violations, outcome):
    """Predicts the likely denial category based on top risk drivers."""
    if outcome == "RULE_DENY" and violations:
        v_fields = [v.get("field", "") for v in violations]
        msgs = [v.get("message", "").lower() for v in violations]
        if any("missing" in m for m in msgs) or any(f.startswith("is_") for f in v_fields):
            return "Documentation / Completeness"
        if any(f in v_fields for f in ["provider_id", "patient_id", "policy_id"]):
            return "Eligibility / Administrative"
        if any(f in v_fields for f in ["diagnosis_code", "procedure_code"]):
            return "Coding"
        return "Administrative"
    
    drivers = sorted([r for r in reasons if r.get("impact_score", 0) < 0], key=lambda x: x.get("impact_score", 0))
    if not drivers:
        return "None (Clean Claim)"
        
    top_feature = drivers[0].get("feature", "")
    
    if top_feature in ("billing_ratio", "cost_diff", "high_cost_flag"):
        return "Billing / Financial"
    elif top_feature in ("is_billed_missing", "is_proc_missing", "is_diag_missing"):
        return "Documentation / Completeness"
    elif top_feature in ("provider_specialty_enc", "diag_category_enc", "severity_score", "diag_claim_count"):
        return "Medical Necessity"
    elif top_feature in ("claim_age_days",):
        return "Eligibility / Timeliness"
        
    return "Coding / Administrative"

# ── Granular outcome metadata ────────────────────────────────────────────────
_OUTCOME_META = {
    # outcome_key : (bg, border, text_color, emoji+label, ml_maps_to)
    "APPROVED": (
        "#163c1e", "#2ea44f", "#3fb950",
        "APPROVED",
        "APPROVED",
    ),
    "APPROVED_WITH_WARNING": (
        "#1a3020", "#3fb950", "#3fb950",
        "APPROVED — WITH WARNINGS",
        "APPROVED",
    ),
    "MANUAL_REVIEW": (
        "#2d260f", "#d29922", "#e3b341",
        "MANUAL REVIEW REQUIRED",
        "SEE ML OUTPUT",
    ),
    "AT_RISK": (
        "#2a1a0f", "#d29922", "#e3b341",
        "AT RISK OF DENIAL",
        "DENIED",
    ),
    "HOLD_FOR_CORRECTION": (
        "#34181a", "#f85149", "#f85149",
        "HOLD — CORRECTION REQUIRED",
        "DENIED",
    ),
    # legacy key kept for rule-deny path which calls banner directly
    "RULE_DENY": (
        "#34181a", "#f85149", "#f85149",
        "REJECTED — RULE VIOLATION",
        "DENIED",
    ),
}

_OUTCOME_WHY = {
    "APPROVED": lambda prob, risk, bv, ratio: (
        f"• <b>Procedure is covered</b> under the assigned policy.<br>"
        f"• <b>All mandatory fields are complete</b> — no missing entries detected.<br>"
        f"• <b>Billing amount is within acceptable range</b> ({ratio} of benchmark).<br>"
        f"• <b>Service date is within the policy active window.</b><br>"
        f"• Denial probability: <b>{prob*100:.1f}%</b> — Risk: <b>{risk}</b>."
    ),
    "APPROVED_WITH_WARNING": lambda prob, risk, bv, ratio: (
        f"• ML model classifies this claim as <b>APPROVED</b>.<br>"
        f"• However, billing verdict is <b>{bv}</b> (amount: {ratio}).<br>"
        f"• Denial probability: <b>{prob*100:.1f}%</b><br>"
        f"• Verify under-billing intent or attach a supporting note."
    ),
    "MANUAL_REVIEW": lambda prob, risk, bv, ratio: (
        f"• <b>MANUAL REVIEW REQUIRED</b> — billing variance detected.<br>"
        f"• Billing verdict: <b>{bv}</b> — amount ratio {ratio}.<br>"
        f"• Route to supervisor for peer review and sign-off."
    ),
    "AT_RISK": lambda prob, risk, bv, ratio: (
        f"• ML model predicts <b>DENIED</b> with {prob*100:.1f}% confidence.<br>"
        f"• Risk level: <b>{risk}</b>.<br>"
        f"• Billing: <b>{bv}</b> ({ratio}).<br>"
        f"• Submitting now is likely to trigger a payer rejection."
    ),
    "HOLD_FOR_CORRECTION": lambda prob, risk, bv, ratio: (
        f"• Very high denial confidence: <b>{prob*100:.0f}%</b>.<br>"
        f"• Risk level: <b>{risk}</b> — immediate correction required.<br>"
        f"• Billing: <b>{bv}</b> ({ratio}).<br>"
        f"• Do not submit until all blockers are resolved."
    ),
    "RULE_DENY": lambda prob, risk, bv, ratio: (
        f"• Hard rule violations detected — ML inference was <b>not</b> run.<br>"
        f"• Claim fails mandatory field or coding requirements.<br>"
        f"• Denial probability: <b>100%</b> (rule-enforced).<br>"
        f"• Fix listed violations before re-submitting."
    ),
}

_OUTCOME_ACTION = {
    "APPROVED": (
        "Ready to Submit",
        "Claim has zero blockages and very low denial risk. Recommend immediate billing transmission.",
        "1. Download the decision report.<br>2. Submit the Claim.",
    ),
    "APPROVED_WITH_WARNING": (
        "Submit with Supporting Note",
        "Approved, but billing variance may attract audits. Attach a note explaining the amount.",
        "1. Attach a brief billing justification note.<br>2. Submit the claim and flag for internal audit tracking.",
    ),
    "MANUAL_REVIEW": (
        "Route to Supervisor",
        "Borderline risk score. Human judgment is required before any submission action.",
        "1. Escalate to billing supervisor or peer reviewer.<br>2. Do not Submit the claim until approved by reviewer.",
    ),
    "AT_RISK": (
        "Correct Before Submitting",
        "High denial risk. Submitting now will likely result in payer rejection.",
        "1. Use the Fix Wizard to identify and correct flagged fields.<br>2. Re-analyse after corrections.",
    ),
    "HOLD_FOR_CORRECTION": (
        "Do Not Submit — Fix Required",
        "Claim has critical issues. Submission will cause immediate clearinghouse rejection.",
        "1. Open the Fix Wizard to repair all mandatory fields.<br>2. Re-run analysis before any submission.",
    ),
    "RULE_DENY": (
        "Do Not Submit — Fix Required",
        "Hard rule violations block ML analysis. All violations must be corrected first.",
        "1. Fix all flagged fields (see violations list).<br>2. Re-submit the corrected claim for ML analysis.",
    ),
}


def _render_decision_banner(outcome, prob, risk):
    # Fetch result details from session state
    res = st.session_state.get("last_result", {})
    reasons = res.get("reasons", [])
    violations = res.get("violations", [])
    base_decision = res.get("base_decision", "APPROVED" if outcome in ("APPROVED", "APPROVED_WITH_WARNING") else "DENIED")
    billed_amt = res.get("billed_amount", 0.0)
    exp_c = res.get("expected_cost", 0.0)
    bv = res.get("billing_verdict", "")
    b_ratio = res.get("billing_ratio", 0.0)
    ratio_str = f"{b_ratio*100:.0f}% of benchmark" if b_ratio else "N/A"
    dup_status = st.session_state.get("last_claim_dup_status", "NEW")

    # Header
    st.markdown("---")
    st.markdown("<h3 style='text-align: center; margin-top: 20px; margin-bottom: 10px;'>Result</h3>", unsafe_allow_html=True)
    if dup_status == "DUPLICATE_ID":
        st.info("**Re-analysed Claim**: Previously processed claim ID with updated fields — treated as corrected resubmission.")

    col1, col2 = st.columns([1, 1])

    category = _determine_denial_category(reasons, violations, outcome)
    cat_color = "#8b949e" if category.startswith("None") else "#e3b341"

    # Check timely warning
    from datetime import date, datetime
    is_timely_warning = False
    if outcome == "APPROVED_WITH_WARNING" or outcome == "MANUAL_REVIEW":
        svc_dt = res.get("_service_date")
        if svc_dt:
            if isinstance(svc_dt, str):
                try:
                    svc_dt = date.fromisoformat(svc_dt)
                except ValueError:
                    pass
            if isinstance(svc_dt, (date, datetime)):
                if isinstance(svc_dt, datetime):
                    svc_dt = svc_dt.date()
                if (date.today() - svc_dt).days > 90:
                    is_timely_warning = True
        if not is_timely_warning and (category == "Eligibility / Timeliness" or any(r.get("feature") == "claim_age_days" for r in reasons)):
            is_timely_warning = True

    # Check billing warning
    is_billing_warning = False
    if outcome == "APPROVED_WITH_WARNING" or outcome == "MANUAL_REVIEW":
        if bv not in ("ACCEPT", "", "NORMAL", None):
            is_billing_warning = True
        elif category == "Billing / Financial" or any(r.get("feature") in ("billing_ratio", "cost_diff", "high_cost_flag") for r in reasons):
            is_billing_warning = True

    # look up this outcome's metadata (fall back to HOLD if unknown key)
    meta   = _OUTCOME_META.get(outcome, _OUTCOME_META["HOLD_FOR_CORRECTION"])
    bg, border, txt_clr, label, _ = meta

    if is_timely_warning and is_billing_warning:
        why_text = (
            f"• ML model classifies this claim as <b>{base_decision}</b>.<br>"
            f"• <b>Multiple warnings detected:</b><br>"
            f"  - Service date is more than <b>90 days old</b> (timely filing concern).<br>"
            f"  - Billing verdict is <b>{bv}</b> ({ratio_str}).<br>"
            f"• Denial probability: <b>{prob*100:.1f}%</b><br>"
            f"• Action: Attach timely filing exception and check billing variance."
        )
        act_title = "Resolve Timeliness & Billing Deviation"
        act_desc = f"Service date is more than 90 days in the past, and billing amount (₹{billed_amt:,.0f}) deviates from the expected cost (₹{exp_c:,.0f})."
        act_steps = (
            "1. Attach a documented timely filing exception note or proof of prior attempt.<br>"
            "2. Verify CPT codes / contract pricing and attach billing justification note.<br>"
            "3. Submit the claim and flag for supervisor review."
        )
    elif is_timely_warning:
        why_text = (
            f"• ML model classifies this claim as <b>APPROVED</b>.<br>"
            f"• Service date is more than <b>90 days old</b> (timely filing concern).<br>"
            f"• Denial probability: <b>{prob*100:.1f}%</b><br>"
            f"• Attach a timely filing exception or supporting note."
        )
        act_title = "Attach Timely Filing Exception Note"
        act_desc = "Service date is more than 90 days in the past. Payer rules require claims to be submitted within 90 days of service unless an exception is attached."
        act_steps = "1. Attach a documented timely filing exception note or proof of prior attempt.<br>2. Submit the claim and flag for timeliness review."
    elif is_billing_warning:
        why_fn = _OUTCOME_WHY.get(outcome, _OUTCOME_WHY["HOLD_FOR_CORRECTION"])
        why_text = why_fn(prob, risk, bv, ratio_str)
        if bv in ("FLAG_LOW", "FLAG_VERY_LOW", "FLAG_LOW_WARN"):
            act_title = "Recheck claim: Billing amount less than expected"
            act_desc = f"Billed amount (₹{billed_amt:,.0f}) is less than expected cost (₹{exp_c:,.0f}). Recheck billing details for under-coding or missing line items."
            act_steps = "1. Confirm that all procedures and supplies are accounted for.<br>2. Correct billing amount or upload supporting note and submit."
        else:
            act_title = "Recheck claim: Billing amount more than expected"
            act_desc = f"Billed amount (₹{billed_amt:,.0f}) exceeds the expected cost (₹{exp_c:,.0f}). Recheck billing details to avoid an overbilling audit."
            act_steps = "1. Verify CPT codes and modifiers justify the higher cost.<br>2. Correct billing amount or upload justification and submit."
    else:
        why_fn = _OUTCOME_WHY.get(outcome, _OUTCOME_WHY["HOLD_FOR_CORRECTION"])
        why_text = why_fn(prob, risk, bv, ratio_str)
        act_title, act_desc, act_steps = _OUTCOME_ACTION.get(
            outcome, _OUTCOME_ACTION["HOLD_FOR_CORRECTION"]
        )
        if outcome == "MANUAL_REVIEW" and bv == "CONDITIONAL":
            act_title = "Route to Supervisor: High Billing Variance"
            act_desc = f"Billed amount (₹{billed_amt:,.0f}) is 1.25x-1.75x the expected benchmark cost (₹{exp_c:,.0f}), representing high risk of overbilling."
            act_steps = "1. Route to supervisor or peer reviewer for manual review.<br>2. Request supporting medical necessity documents if needed to justify high-level billing."

    # ── COLUMN 1: DECISION ──
    with col1:
        st.markdown("<h5 style='text-align: center; margin-bottom: 12px;'>Decision</h5>", unsafe_allow_html=True)
        bd_color = "#3fb950" if base_decision == "APPROVED" else "#f85149"
        st.markdown(
            f"""
            <div style="background-color:{bg}; border:2px solid {border};
                        border-radius:12px; padding:18px; color:#e6edf3; min-height:280px;
                        display:flex; flex-direction:column; justify-content:space-between;">
                <div>
                    <h4 style="color:{txt_clr}; margin-top:0; font-weight:bold;
                                letter-spacing:0.5px; font-size:1.1rem; margin-bottom:6px">{label}</h4>
                    <div style="font-size:0.75rem; color:#8b949e; margin-bottom:8px">
                        ML base: <span style="color:{bd_color}; font-weight:bold">{base_decision}</span>
                        &nbsp;|&nbsp; Denial prob: <b>{prob*100:.1f}%</b><br>
                        Risk Category: <span style="color:{cat_color}; font-weight:bold">{category}</span>
                    </div>
                    <hr style="border-color:{border}; opacity:0.3; margin:8px 0;">
                    <div style="font-size:0.82rem; line-height:1.45">
                        {why_text}
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ── COLUMN 2: ACTION GUIDE ──
    with col2:
        st.markdown("<h5 style='text-align: center; margin-bottom: 12px;'>Analyst Action Guide</h5>", unsafe_allow_html=True)
        st.markdown(
            f"""
            <div style="background-color:#1c2128; border:1px solid #30363d;
                        border-radius:12px; padding:18px; min-height:280px;
                        display:flex; flex-direction:column; justify-content:space-between; color:#e6edf3;">
                <div>
                    <strong style="font-size:1.1rem; color:#e6edf3; display:block; margin-bottom:6px">{act_title}</strong>
                    <p style="font-size:0.82rem; margin-top:8px; line-height:1.45; color:#8b949e">{act_desc}</p>
                </div>
                <div style="font-size:0.8rem; color:#8b949e; line-height:1.4; border-top:1px solid #30363d; padding-top:12px; margin-top:12px">
                    <strong style="color:#e6edf3">Next steps:</strong><br>{act_steps}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.write("")

    st.markdown("---")
    
    # ── METRICS & GAUGE CHART (Universally shown) ──
    import plotly.graph_objects as go
    bar_clr = "#f85149" if prob >= 0.55 else "#d29922" if prob >= 0.35 else "#3fb950"
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=prob*100,
        number={"suffix": "%", "font": {"size": 28, "color": "#e6edf3"}},
        title={"text": "Denial Risk", "font": {"size": 14, "color": "#8b949e"}},
        gauge={"axis":{"range":[0,100]}, "bar":{"color":bar_clr},
               "steps":[{"range":[0,30],"color":"#e8f5e9"},
                        {"range":[30,60],"color":"#fff8e1"},
                        {"range":[60,100],"color":"#ffebee"}],
               "threshold":{"line":{"color":"black","width":3},"thickness":0.75,"value":prob*100}}
    ))
    fig.update_layout(height=200, margin=dict(l=10,r=10,t=50,b=10),
                      paper_bgcolor="rgba(0,0,0,0)", font_color="#e6edf3")
                      
    gc1, gc2 = st.columns([1, 1])
    with gc1:
        st.plotly_chart(fig, use_container_width=True)
    with gc2:
        st.markdown("<br>", unsafe_allow_html=True)
        m1, m2, m3 = st.columns(3)
        m1.metric("Denial Prob", f"{prob*100:.1f}%")
        m2.metric("Approval Prob", f"{(1-prob)*100:.1f}%")
        m3.metric("Risk Level", risk)
        st.caption(f"Denial risk: {prob*100:.1f}% — {risk}")

    st.markdown("---")


def _render_xai_tab(outcome, reasons, prob):
    import plotly.graph_objects as go
    denial_drivers  = [r for r in reasons if r.get("impact_score", 0) < 0]
    approval_factors= [r for r in reasons if r.get("impact_score", 0) > 0]

    if outcome == "RULE_DENY":
        st.info("Rule-based rejections do not use SHAP. See violations above.")
        return

    if outcome == "APPROVED":
        st.markdown("### Why This Claim Was Approved")
        _render_factor_list("Approval Factors", approval_factors, "#3fb950")
    elif outcome == "APPROVED_WITH_WARNING":
        st.markdown("### Why This Claim Was Approved")
        _render_factor_list("Approval Factors", approval_factors, "#3fb950")
        with st.expander("View warning / risk factors"):
            _render_factor_list("Warning Factors", denial_drivers, "#d29922")
    elif outcome == "MANUAL_REVIEW":
        st.markdown("### Why This Claim Is Flagged for Review")
        col_d, col_a = st.columns(2)
        with col_d:
            _render_factor_list("Denial Risk Factors", denial_drivers, "#f85149")
        with col_a:
            _render_factor_list("Approval Factors", approval_factors, "#3fb950")
    else:  # denied claims (AT_RISK, HOLD_FOR_CORRECTION)
        st.markdown("### Why This Claim Was Denied")
        _render_factor_list("Top Denial Drivers", denial_drivers, "#f85149")
        with st.expander("View mitigating (approval) factors"):
            _render_factor_list("Mitigating Factors", approval_factors, "#3fb950")
        st.caption("Addressing the denial drivers above can improve the chance of approval on resubmission.")

    # SHAP bar chart
    if reasons:
        features = [SHAP_LABEL.get(r["feature"], r["feature"]) for r in reasons]
        scores   = [r.get("impact_score", 0) for r in reasons]
        colors   = ["#f85149" if s < 0 else "#3fb950" for s in scores]
        fig = go.Figure(go.Bar(x=scores, y=features, orientation="h",
                               marker_color=colors))
        fig.update_layout(height=280, margin=dict(l=0,r=0,t=20,b=0),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          font_color="#e6edf3", xaxis_title="SHAP Impact")
        st.plotly_chart(fig, use_container_width=True)


def _render_factor_list(title, factors, color):
    st.markdown(f"**{title}**")
    st.markdown(f"<div style='border-top:2px solid {color};margin-bottom:6px'></div>", unsafe_allow_html=True)
    if not factors:
        st.caption("None identified.")
        return
    for r in factors[:5]:
        label = SHAP_LABEL.get(r["feature"], r["feature"])
        score = r.get("impact_score", 0)
        st.markdown(f"• {r['explanation']}  \n"
                    f"  <span style='color:#8b949e;font-size:0.8rem'>[SHAP: {score:+.3f}] — {label}</span>",
                    unsafe_allow_html=True)


def _render_policy_tab(outcome, reasons, result):
    # For clean APPROVED claims — show the four approval compliance pillars
    if outcome == "APPROVED":
        st.success("No policy concerns identified. This claim satisfies all four approval criteria.")
        st.markdown("#### Policy Compliance Summary")
        for pillar, clause, tag in [
            ("Procedure Coverage",
             "The procedure code is listed under covered services for the assigned policy.",
             "Satisfied"),
            ("Field Completeness",
             "All mandatory claim fields (Claim ID, Patient ID, Diagnosis, Procedure, Billed Amount, Service Date, Policy ID) are present.",
             "Satisfied"),
            ("Billing Alignment",
             "The billed amount is within 125% of the expected benchmark cost, within the acceptable threshold.",
             "Satisfied"),
            ("Policy Date Window",
             "The service date falls within the policy active period (after start date and before end date).",
             "Satisfied"),
        ]:
            with st.expander(f"{pillar}  —  {tag}"):
                st.markdown(f"<div class='policy-box'>{clause}</div>", unsafe_allow_html=True)
        return

    # Check timely filing issue
    from datetime import date, datetime
    svc_dt = result.get("_service_date")
    is_timely_warning = False
    if svc_dt:
        if isinstance(svc_dt, str):
            try:
                svc_dt = date.fromisoformat(svc_dt)
            except ValueError:
                pass
        if isinstance(svc_dt, (date, datetime)):
            if isinstance(svc_dt, datetime):
                svc_dt = svc_dt.date()
            if (date.today() - svc_dt).days > 90:
                is_timely_warning = True
    if not is_timely_warning:
        is_timely_warning = any(r.get("feature") == "claim_age_days" and r.get("impact_score", 0) < 0 for r in reasons)
        
    # Determine billing deviation issue
    billing_verdict = result.get("billing_verdict", "")
    is_billing_warning = False
    if billing_verdict not in ("ACCEPT", "", "NORMAL", None):
        is_billing_warning = True
    else:
        is_billing_warning = any(r.get("feature") in ("billing_ratio", "cost_diff", "high_cost_flag") and r.get("impact_score", 0) < 0 for r in reasons)

    shown_any = False

    # Show warning compliance policies if active
    if is_timely_warning or is_billing_warning:
        st.warning(" **COMPLIANCE WARNINGS DETECTED**")
        st.markdown("####  Policy Compliance Reference")
        
        if is_timely_warning:
            st.markdown("""<div class='policy-box' style='border-left:3px solid #d29922; background:#1e1a0f; margin-bottom:12px;'>
                <b>ICAP-001 Section 5: CLAIM SUBMISSION TIMELINESS</b><br>
                <i>POLICY 5.1 — TIMELY FILING REQUIREMENT</i><br>
                If the claim was submitted significantly late relative to the service date (e.g., beyond 90 days), 
                it will be denied for late filing unless a documented exception applies.
            </div>""", unsafe_allow_html=True)
            shown_any = True
            
        if is_billing_warning:
            st.markdown("""<div class='policy-box' style='border-left:3px solid #d29922; background:#1e1a0f; margin-bottom:12px;'>
                <b>ICAP-001 Section 7: EXACT BILLING ALIGNMENT RULE</b><br>
                <i>POLICY 7.1 — BILLING DEVIATION WARNINGS</i><br>
                Claims that have a valid billing amount but deviate from the expected benchmark cost 
                (either less than the expected cost or more than the expected cost) must be flagged 
                with a warning of 'Approved with Warning' (MANUAL REVIEW NEEDED) and require rechecking 
                before final claim submission to ensure proper pricing.
            </div>""", unsafe_allow_html=True)
            shown_any = True

    # Show RAG policies if any
    policies = []
    for r in reasons:
        if r.get("policy_text"):
            policies.append({
                "title":     r.get("policy_source", "Policy Document"),
                "excerpt":   r["policy_text"][:400],
                "tag":       "Policy violated" if outcome in ("AT_RISK", "HOLD_FOR_CORRECTION") else " For reference",
            })

    if policies:
        st.markdown("####  Retrieved Policy Documents")
        tag_map = {
            "RULE_DENY":              " Directly caused rejection",
            "APPROVED_WITH_WARNING":  "Relevant to conditional review",
            "MANUAL_REVIEW":          "Borderline — supervisor review needed",
            "AT_RISK":                " Policy not met",
            "HOLD_FOR_CORRECTION":    " Policy not met",
        }
        tag = tag_map.get(outcome, " Policy Reference")
        for p in policies[:4]:
            with st.expander(f" {p['title']}  —  {tag}"):
                st.markdown(f"<div class='policy-box'>{p['excerpt']}...</div>", unsafe_allow_html=True)
        if outcome in ("AT_RISK", "HOLD_FOR_CORRECTION"):
            st.caption("These policies were retrieved based on the specific denial reasons identified for this claim.")
        shown_any = True

    if not shown_any:
        if result.get("denial_prob", 0) <= 0.15:
            st.success(" No policy concerns identified for this claim.")
        else:
            st.info("No policy documents retrieved. RAG may be unavailable.")


def _render_fix_wizard_rule_deny(violations, proc_code, exp_c, billed_amt):
    st.markdown("###  Required Fixes Before Resubmission")
    complete = sum(1 for v in violations if v["field"] not in [vv["field"] for vv in violations])
    total_fields = 7
    fixed = total_fields - len(violations)
    st.progress(max(0, fixed) / total_fields, text=f"Claim completeness: {fixed}/{total_fields} fields valid")
    for i, v in enumerate(violations, 1):
        field = v["field"].replace("_", " ").title()
        st.markdown(f"""<div class="wizard-step">
            <span class="step-number">{i}</span><b>FIX: {field.upper()}</b><br>
            <b>Field:</b> {v['field']}<br>
            <b>Issue:</b> {v['message']}<br>
            <b>Action:</b> Provide a valid {field} and resubmit.
            {"<br><b>Reference:</b> Expected cost for " + str(proc_code) + " is ₹" + f"{exp_c:,.0f}" if v["field"] == "billed_amount" and proc_code else ""}
       """, unsafe_allow_html=True)


def _render_fix_wizard_ml(outcome, reasons, result, billed_amt, exp_c, billing_verdict, proc_code, diag_code, provider_id, b_ratio):
    if outcome == "APPROVED":
        st.markdown("### Recommended Fixes to Improve Approval Chances")
        st.success("No fixes required. This claim has passed all four approval criteria and is ready to submit.")
        # Enumerate the four passing criteria as checklist items
        pct = billed_amt/exp_c*100 if exp_c > 0 else 0
        st.markdown(f"""
<div style='background:#163c1e;border:1px solid #2ea44f;border-radius:8px;padding:14px;margin-top:8px'>
  <div style='color:#3fb950;font-weight:bold;margin-bottom:8px'> All Checks Passed</div>
  <ul style='color:#c9d1d9;font-size:0.85rem;line-height:1.8;margin:0;padding-left:18px'>
    <li><b>Procedure covered</b> under assigned policy</li>
    <li><b>All mandatory fields complete</b> — no missing entries</li>
    <li><b>Billing within acceptable range</b> — {pct:.0f}% of expected benchmark (₹{exp_c:,.0f})</li>
    <li><b>Service date within policy active window</b></li>
  </ul>
</div>""", unsafe_allow_html=True)
        st.caption("No action required. Proceed to transmit this claim to the payer.")
        return
    if outcome == "APPROVED_WITH_WARNING":
        st.markdown("### Required Actions Before Resubmission")
        violations = result.get("violations", [])
        
        # Determine timely filing issue
        from datetime import date, datetime
        svc_dt = result.get("_service_date")
        is_timely_warning = False
        if svc_dt:
            if isinstance(svc_dt, str):
                try:
                    svc_dt = date.fromisoformat(svc_dt)
                except ValueError:
                    pass
            if isinstance(svc_dt, (date, datetime)):
                if isinstance(svc_dt, datetime):
                    svc_dt = svc_dt.date()
                if (date.today() - svc_dt).days > 90:
                    is_timely_warning = True
        if not is_timely_warning:
            is_timely_warning = any(r.get("feature") == "claim_age_days" and r.get("impact_score", 0) < 0 for r in reasons)
            
        # Determine billing deviation issue
        is_billing_warning = False
        if billing_verdict not in ("ACCEPT", "", "NORMAL", None):
            is_billing_warning = True
        else:
            is_billing_warning = any(r.get("feature") in ("billing_ratio", "cost_diff", "high_cost_flag") and r.get("impact_score", 0) < 0 for r in reasons)
            
        # If neither is identified (fallback), show billing deviation
        if not is_timely_warning and not is_billing_warning:
            is_billing_warning = True
            
        if is_timely_warning and is_billing_warning:
            st.warning(" **MULTIPLE COMPLIANCE WARNINGS DETECTED**")
            
            st.markdown("""<div class="wizard-step" style="border-left:3px solid #d29922; background:#1e1a0f; padding:12px; border-radius:6px; margin-bottom:12px">
                <span style="color:#e3b341; font-weight:bold; font-size:0.92rem">TIMELY FILING WARNING</span><br>
                Service date is more than 90 days in the past.<br>
                <b>Action:</b> Please attach a documented timely filing exception or proof of prior submission attempt before transmitting the claim.
            </div>""", unsafe_allow_html=True)
            
            if billing_verdict in ("FLAG_LOW", "FLAG_VERY_LOW", "FLAG_LOW_WARN"):
                st.markdown(f"""<div class="wizard-step" style="border-left:3px solid #d29922; background:#1e1a0f; padding:12px; border-radius:6px;">
                    <span style="color:#e3b341; font-weight:bold; font-size:0.92rem">BILLING VARIANCE WARNING (UNDER-BILLING)</span><br>
                    Billed amount (₹{billed_amt:,.0f}) is less than the expected cost (₹{exp_c:,.0f}).<br>
                    <b>Action:</b> Verify the bill is not missing line items or under-coded before submission.
                </div>""", unsafe_allow_html=True)
            else:
                st.markdown(f"""<div class="wizard-step" style="border-left:3px solid #d29922; background:#1e1a0f; padding:12px; border-radius:6px;">
                    <span style="color:#e3b341; font-weight:bold; font-size:0.92rem">BILLING VARIANCE WARNING (OVER-BILLING)</span><br>
                    Billed amount (₹{billed_amt:,.0f}) exceeds or deviates from the expected cost (₹{exp_c:,.0f}).<br>
                    <b>Action:</b> Recheck bill details and justify the higher cost before submission.
                </div>""", unsafe_allow_html=True)
                
        elif is_timely_warning:
            st.warning(" **MANUAL REVIEW NEEDED (TIMELY FILING)**  \n"
                       "Service date is more than 90 days in the past. "
                       "Please attach a documented timely filing exception or proof of prior submission attempt before transmitting the claim.")
        else:
            # Single billing warning
            if billing_verdict in ("FLAG_LOW", "FLAG_VERY_LOW", "FLAG_LOW_WARN"):
                st.warning(" **MANUAL REVIEW NEEDED (UNDER-BILLING)**  \n"
                           f"Billing amount (₹{billed_amt:,.0f}) is **less than** the expected cost (₹{exp_c:,.0f}). "
                           "Please verify the bill is not missing line items or under-coded before submission.")
            elif billing_verdict in ("CONDITIONAL", "FLAG_HIGH_WARN"):
                st.warning("**MANUAL REVIEW NEEDED (OVER-BILLING)**  \n"
                           f"Billing amount (₹{billed_amt:,.0f}) is **more than** the expected cost (₹{exp_c:,.0f}). "
                           "Please recheck the bill details and justify the higher cost before submission.")
            else:
                st.warning("**MANUAL REVIEW NEEDED (BILLING COMPLIANCE)**  \n"
                           "Verify the billing details against the provider contract before claim transmission.")
        return

    if outcome == "MANUAL_REVIEW":
        st.markdown("### Flags Requiring Review Before Final Processing")
        pct = b_ratio * 100
        st.warning(" **MANUAL REVIEW REQUIRED**")
        
        # Check timely warning
        from datetime import date, datetime
        svc_dt = result.get("_service_date")
        is_timely_warning = False
        if svc_dt:
            if isinstance(svc_dt, str):
                try:
                    svc_dt = date.fromisoformat(svc_dt)
                except ValueError:
                    pass
            if isinstance(svc_dt, (date, datetime)):
                if isinstance(svc_dt, datetime):
                    svc_dt = svc_dt.date()
                if (date.today() - svc_dt).days > 90:
                    is_timely_warning = True
        if not is_timely_warning:
            is_timely_warning = any(r.get("feature") == "claim_age_days" and r.get("impact_score", 0) < 0 for r in reasons)

        if is_timely_warning:
            st.markdown(f"""<div class="wizard-step" style="border-left:3px solid #d29922; background:#1e1a0f; padding:12px; border-radius:6px; margin-bottom:12px">
                <span style="color:#e3b341; font-weight:bold; font-size:0.92rem">TIMELY FILING ISSUE</span><br>
                Service date is more than 90 days in the past.<br>
                <b>Action:</b> Obtain a documented timely filing exception note or proof of prior attempt before final transmission.
            </div>""", unsafe_allow_html=True)
            
        st.markdown(f"""<div class="wizard-step" style="border-left:3px solid #d29922; background:#1e1a0f; padding:12px; border-radius:6px; margin-bottom:12px">
            <span style="color:#e3b341; font-weight:bold; font-size:0.92rem"> BILLING VARIANCE DETECTED</span><br>
            <b>Submitted Billed Amount:</b> ₹{billed_amt:,.0f} &nbsp;|&nbsp;
            <b>Expected Cost:</b> ₹{exp_c:,.0f} &nbsp;|&nbsp;
            <b>Ratio:</b> {pct:.0f}% of expected benchmark<br>
            <b>Action:</b> Route to a billing supervisor or peer reviewer. Do not Submit the claim until approved by the reviewer.
        </div>""", unsafe_allow_html=True)
        
        return

    # Remaining high-risk categories: AT_RISK or HOLD_FOR_CORRECTION
    if outcome == "HOLD_FOR_CORRECTION":
        st.markdown("### Required Actions to Release Submission Hold")
        st.error(" **ADMINISTRATIVE HOLD — CORRECTION REQUIRED**")
    else:  # AT_RISK
        st.markdown("### Recommended Fixes to Mitigate Denial Risk")
        st.warning(" **HIGH DENIAL RISK DETECTED**")

    denial_drivers = [r for r in reasons if r.get("impact_score", 0) < 0]
    for i, r in enumerate(denial_drivers[:4], 1):
        label  = SHAP_LABEL.get(r["feature"], r["feature"])
        impact = abs(r.get("impact_score", 0))
        
        if outcome == "HOLD_FOR_CORRECTION":
            impact_tag = "CRITICAL"
            tag_color = "#f85149"
        else:
            impact_tag = "HIGH" if impact > 0.1 else "MEDIUM"
            tag_color = "#d29922"

        # Build fix action based on feature
        actions = {
            "billing_ratio":      f"Reduce billed amount (currently ₹{billed_amt:,.0f}) closer to expected ₹{exp_c:,.0f}.",
            "is_diag_missing":    f"Add a valid ICD-10 diagnosis code. Current: {diag_code or 'MISSING'}.",
            "is_proc_missing":    f"Add the CPT procedure code. Current: {proc_code or 'MISSING'}.",
            "is_billed_missing":  "Enter the billed amount (must be > ₹0).",
            "high_cost_flag":     "Attach a Letter of Medical Necessity for high-cost claims.",
            "claim_age_days":     "Submit a timely filing exception with proof of earlier attempt.",
            "provider_claim_count": f"Attach provider NPI and credentials for {provider_id}.",
            "severity_score":     f"Verify ICD-10 severity for {diag_code} matches billed procedure {proc_code}.",
        }
        action = actions.get(r["feature"], result.get("next_action", "Review and correct the flagged item."))
        st.markdown(f"""<div class="wizard-step">
            <span class="step-number">{i}</span><b>{label.upper()}</b>
            &nbsp;<span style='color:{tag_color};font-size:0.8rem;font-weight:bold'>[{impact_tag}]</span><br>
            {r['explanation']}<br>
            <b>Action:</b> {action}
        </div>""", unsafe_allow_html=True)
        
    if outcome == "HOLD_FOR_CORRECTION":
        st.caption("Admin hold will be released only after correcting all critical blocks above.")
    else:
        st.caption("Addressing the risk factors above will lower the denial probability and increase approval chances.")


# ── Auth gate — unauthenticated users see ONLY the login page ─────────────────
if not is_authenticated():
    render_auth_page()
    st.stop()

# ── Normalize user email into sb_email immediately after auth passes ──────────
# This ensures get_logged_in_user_email() always finds the email regardless of
# which auth path was used (Supabase password OR Google OAuth via st.login()).
if not st.session_state.get("sb_email"):
    # Try Streamlit native auth (Google OAuth)
    _resolved_email = ""
    if hasattr(st, "user"):
        try:
            if st.user.is_logged_in and st.user.email:
                _resolved_email = st.user.email
        except Exception:
            pass
    # Try Supabase user object as fallback
    if not _resolved_email:
        _sb_user = st.session_state.get("sb_user")
        if _sb_user:
            _resolved_email = getattr(_sb_user, "email", "") or ""
    if _resolved_email:
        st.session_state["sb_email"] = _resolved_email

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("Claim Denial Prevention System")
    # st.markdown("---")
    render_user_sidebar()
    # st.markdown("---")
    health = call_health()
    status_color = "#3fb950" if health.get("status") == "ok" else "#f85149"
    # st.markdown(f"**API Status:** <span style='color:{status_color}'>● {health.get('status','unreachable').upper()}</span>", unsafe_allow_html=True)
    # st.markdown(f"**ML Models:** {'✅' if health.get('models_loaded') else '❌'}")
    # st.markdown(f"**RAG:** {'✅' if health.get('rag_loaded') else '❌'}")
    # st.markdown("---")
    page = st.radio("Navigate", [
        "Submit & Predict",
        "Claim Search & Audit Trail",
        "Claim Fix Wizard",
        "Policy Explorer",
    ], key="navigate_tab")

# ── Page: Submit & Predict ─────────────────────────────────────────────────────
if page == "Submit & Predict":
    st.markdown("### Submit & Predict")
    st.markdown("Enter claim details to know its status.")

    # Reference options (derive from module-level dicts loaded above)
    diag_options = sorted(_DIAG_DATA.keys())
    proc_options = sorted(_COST_DATA.keys())
    prov_options = sorted(_PROV_DATA.keys())
    policy_options = sorted(_POLICY_DATA.keys())
    _exp_cost_map  = {k: float(v["expected_cost"]) for k, v in _COST_DATA.items() if v.get("expected_cost")}
    _exp_cost_mean = float(sum(_exp_cost_map.values()) / len(_exp_cost_map)) if _exp_cost_map else 8500.0

    import re
    import requests

    # ── Session-state keys used to seed the form widgets ─────────────────────
    # Streamlit owns widget state via key= argument.  We write to those keys
    # directly so the widgets re-render with the extracted values.
    _FORM_KEYS = {
        "ext_claim_id":      "form_claim_id",
        "ext_patient_id":    "form_patient_id",
        "ext_provider_id":   "form_provider_id",
        "ext_diag_code":     "form_diag_code",
        "ext_proc_code":     "form_proc_code",
        "ext_billed_amount": "form_billed_amount",
        "ext_date":          "form_svc_date",
        "ext_policy_id":     "form_policy_id",
    }

    def _clear_form():
        for k in _FORM_KEYS.values():
            if k in st.session_state:
                del st.session_state[k]
        for k in _FORM_KEYS:
            if k in st.session_state:
                del st.session_state[k]
        # Clear file uploader state
        if "claim_file_uploader" in st.session_state:
            del st.session_state["claim_file_uploader"]
        # Clear previous analysis results
        if "last_result" in st.session_state:
            del st.session_state["last_result"]

    upload_mode = st.radio(
        "Submission Mode",
        ["Single Claim", "Batch Upload"],
        horizontal=True,
        key="upload_mode",
    )

    # ══════════════════════════════════════════════════════════════════════════
    # BATCH UPLOAD MODE
    # ══════════════════════════════════════════════════════════════════════════
    if upload_mode == "Batch Upload":
        st.markdown("### Batch Upload")
        st.markdown(
            "Upload a **CSV or Excel** file with one claim per row. "
            "The system will validate every row and run the full ML pipeline "
            "on all valid claims at once."
        )

        batch_file = st.file_uploader(
            "Upload CSV or Excel (one claim per row)",
            type=["csv", "xlsx"],
            help="Columns: claim_id, patient_id, provider_id, diagnosis_code, procedure_code, billed_amount, service_date, policy_id",
            key="batch_file_uploader",
        )

        if batch_file is not None:
            # ── Parse uploaded file ──────────────────────────────────────────
            try:
                if batch_file.name.endswith(".xlsx"):
                    batch_df = pd.read_excel(batch_file)
                else:
                    batch_df = pd.read_csv(batch_file)
            except Exception as e:
                st.error(f"Could not parse file: {e}")
                batch_df = None

            if batch_df is not None:
                # Normalize column names case-insensitively and strip whitespace
                batch_df.columns = [c.strip().lower() for c in batch_df.columns]
                
                # Check for member_id as an alias for patient_id
                if "member_id" in batch_df.columns and "patient_id" not in batch_df.columns:
                    batch_df.rename(columns={"member_id": "patient_id"}, inplace=True)
                
                REQUIRED_COLS = [
                    "claim_id", "patient_id", "provider_id",
                    "diagnosis_code", "procedure_code", "billed_amount",
                    "service_date", "policy_id",
                ]
                missing_cols = [c for c in REQUIRED_COLS if c not in batch_df.columns]
                if missing_cols:
                    st.error(f" Missing columns in file: `{', '.join(missing_cols)}`. The file must contain: claim_id, patient_id/member_id, provider_id, diagnosis_code, procedure_code, billed_amount, service_date, policy_id.")
                else:
                    # ── Helper Fingerprint Hashing Functions ──────────────────
                    def get_exact_fingerprint(row):
                        import hashlib
                        cid = str(row.get("claim_id", "") or "").strip().lower()
                        pid = str(row.get("patient_id", "") or "").strip().lower()
                        prov = str(row.get("provider_id", "") or "").strip().lower()
                        diag = str(row.get("diagnosis_code", "") or "").strip().lower()
                        prc = str(row.get("procedure_code", "") or "").strip().lower()
                        try:
                            amt = f"{float(row.get('billed_amount') or 0):.2f}"
                        except Exception:
                            amt = str(row.get("billed_amount", "")).strip().lower()
                        sdt = str(row.get("service_date", "") or "").strip().lower()
                        pol = str(row.get("policy_id", "") or "").strip().lower()
                        raw = f"{cid}|{pid}|{prov}|{diag}|{prc}|{amt}|{sdt}|{pol}"
                        return hashlib.sha256(raw.encode()).hexdigest()

                    def get_suspicious_fingerprint(row):
                        import hashlib
                        pid = str(row.get("patient_id", "") or "").strip().lower()
                        prov = str(row.get("provider_id", "") or "").strip().lower()
                        prc = str(row.get("procedure_code", "") or "").strip().lower()
                        try:
                            amt = f"{float(row.get('billed_amount') or 0):.2f}"
                        except Exception:
                            amt = str(row.get("billed_amount", "")).strip().lower()
                        sdt = str(row.get("service_date", "") or "").strip().lower()
                        raw = f"{pid}|{prov}|{prc}|{amt}|{sdt}"
                        return hashlib.sha256(raw.encode()).hexdigest()

                    # ── Per-row validation ───────────────────────────────────
                    def _validate_batch_row(row):
                        errs = []
                        cid = str(row.get("claim_id", "") or "").strip()
                        pid = str(row.get("patient_id", "") or "").strip()

                        if not cid:
                            errs.append("claim_id missing")
                        elif not re.match(r"^C\d{4,}$", cid):
                            errs.append(f"claim_id '{cid}' invalid (need CXXXX)")

                        if not pid:
                            errs.append("patient_id missing")
                        elif not re.match(r"^P\d{3,}$", pid):
                            errs.append(f"patient_id '{pid}' invalid (need PXXX)")

                        if errs:
                            return "; ".join(errs)
                        return "Valid"

                    batch_df["_status"] = batch_df.apply(_validate_batch_row, axis=1)
                    n_valid = (batch_df["_status"] == "Valid").sum()
                    n_err   = len(batch_df) - n_valid

                    # ── Preview table ────────────────────────────────────────
                    st.markdown(f"**Preview:** {len(batch_df)} rows loaded")
                    preview_cols = ["claim_id", "patient_id", "diagnosis_code",
                                    "procedure_code", "billed_amount", "service_date",
                                    "policy_id", "_status"]
                    st.dataframe(
                        batch_df[preview_cols].rename(columns={"_status": "Status"}),
                        use_container_width=True,
                    )

                    # ── Validation summary banner ────────────────────────────
                    if n_err > 0:
                        st.warning(f" **{n_valid} valid** · **{n_err} rows have errors** — invalid rows will be processed as INVALID_INPUT.")
                        with st.expander("Show row errors"):
                            err_rows = batch_df[batch_df["_status"] != "Valid"][["claim_id", "_status"]]
                            st.dataframe(err_rows.rename(columns={"_status": "Error"}), use_container_width=True)
                    else:
                        st.success(f" All {n_valid} rows are valid and ready to submit.")

                    # ── Submit batch button ──────────────────────────────────
                    if len(batch_df) > 0:
                        if st.button(f"Submit all {len(batch_df)} Claims for Adjudication", type="primary", use_container_width=True):
                            processed_results = []
                            claims_payload = []
                            claim_details_map = {}
                            
                            conn = _get_db_conn()
                            conn.row_factory = sqlite3.Row
                            
                            # In-memory sets to track duplicate states within the uploaded batch
                            processed_batch_exact = set()
                            processed_batch_claim_ids = {} # maps claim_id -> exact_fingerprint
                            processed_batch_suspicious = set()
                            
                            # Parse and evaluate formats, duplicates, and rules before API
                            for idx, r in batch_df.iterrows():
                                cid = str(r.get("claim_id", "") or "").strip()
                                pid = str(r.get("patient_id", "") or "").strip()
                                pol = str(r.get("policy_id", "") or "").strip()
                                sdt = str(r.get("service_date", "") or "").strip()
                                amt = r.get("billed_amount")
                                prc = str(r.get("procedure_code", "") or "").strip()
                                prov = str(r.get("provider_id", "") or "").strip()
                                diag = str(r.get("diagnosis_code", "") or "").strip()
                                
                                # 1. Format errors
                                if r["_status"] != "Valid":
                                    processed_results.append({
                                        "claim_id": cid or f"ROW_{idx+1}",
                                        "patient_id": pid,
                                        "provider_id": prov,
                                        "diagnosis_code": diag,
                                        "procedure_code": prc,
                                        "billed_amount": amt,
                                        "service_date": sdt,
                                        "policy_id": pol,
                                        "status": "INVALID_INPUT",
                                        "duplicate_type": "—",
                                        "risk_score_str": "—",
                                        "denial_prob": 0.0,
                                        "primary_reason": r["_status"],
                                        "policy_match": "N/A",
                                        "next_action": "Correct formatting errors and re-upload.",
                                        "violations": [{"field": "row", "message": r["_status"]}],
                                        "reasons": [],
                                        "recommendation": "Check template column names, types and patterns.",
                                        "outcome_key": "INVALID_INPUT",
                                        "row_number": idx + 1
                                    })
                                    continue
                                    
                                # Parsing valid dates/floats
                                try:
                                    svc_dt = sdt
                                    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
                                        try:
                                            svc_dt = datetime.datetime.strptime(sdt, fmt).date().isoformat()
                                            break
                                        except ValueError:
                                            pass
                                except Exception:
                                    svc_dt = sdt
                                    
                                try:
                                    billed_amt = float(amt)
                                except Exception:
                                    billed_amt = 0.0
                                    
                                # Generate fingerprints
                                exact_fingerprint = get_exact_fingerprint(r)
                                suspicious_fingerprint = get_suspicious_fingerprint(r)

                                dup_status = None
                                dup_type = "—"
                                dup_reason = ""
                                dup_action = ""
                                force_manual_review = False
                                is_revised_resubmission = False
                                
                                # ── DUPLICATE ENGINE LAYER 1: WITHIN UPLOADED BATCH ──
                                if exact_fingerprint in processed_batch_exact:
                                    dup_status = "DUPLICATE_BLOCKED"
                                    dup_type = "Within-Batch Exact Duplicate"
                                    dup_reason = "Exact duplicate row in uploaded batch"
                                    dup_action = "Remove duplicate entry"
                                elif cid in processed_batch_claim_ids:
                                    # Claim ID conflict in the batch
                                    force_manual_review = True
                                    dup_type = "Within-Batch ID Conflict"
                                    dup_reason = "Claim ID conflict within uploaded batch"
                                    dup_action = "Investigate duplicate Claim ID"
                                elif suspicious_fingerprint in processed_batch_suspicious:
                                    # Suspicious duplicate within the batch
                                    force_manual_review = True
                                    dup_type = "Within-Batch Suspicious Duplicate"
                                    dup_reason = "Suspicious duplicate pattern found within uploaded batch"
                                    dup_action = "Verify patient identity and procedures"
                                    
                                # ── DUPLICATE ENGINE LAYER 2 & 3: AGAINST HISTORICAL DATABASE ──
                                if not dup_status:
                                    # Layer 2a: Exact Duplicate of History Claim
                                    exact_match_query = """
                                        SELECT claim_id, submitted_at, predicted_status FROM claim_history 
                                        WHERE 
                                            claim_id = ? AND patient_id = ? AND provider_id = ? AND diagnosis_code = ? AND
                                            procedure_code = ? AND billed_amount = ? AND service_date = ? AND policy_id = ?
                                        LIMIT 1
                                    """
                                    exact_row = conn.execute(exact_match_query, (
                                        cid, pid, prov, diag, prc, billed_amt, svc_dt, pol
                                    )).fetchone()
                                    
                                    if exact_row:
                                        dup_status = "DUPLICATE_BLOCKED"
                                        dup_type = "Exact Match (History)"
                                        dup_reason = "Exact duplicate of historical claim already processed"
                                        dup_action = "Do not resubmit"
                                    else:
                                        # Layer 2b: Claim ID match but modified fields (Revised Resubmission)
                                        hist_id_query = "SELECT claim_id, submitted_at FROM claim_history WHERE claim_id = ? LIMIT 1"
                                        hist_id_row = conn.execute(hist_id_query, (cid,)).fetchone()
                                        if hist_id_row:
                                            is_revised_resubmission = True
                                            dup_type = "Existing ID Modified"
                                            dup_reason = "Existing claim ID found in history with modified fields"
                                            dup_action = "Re-adjudicate corrected claim information"
                                        
                                        # Layer 3: Suspicious history duplicate
                                        else:
                                            suspicious_query = """
                                                SELECT claim_id, submitted_at, predicted_status FROM claim_history
                                                WHERE claim_id != ? AND patient_id = ? AND provider_id = ? AND procedure_code = ?
                                                  AND billed_amount = ? AND service_date = ?
                                                LIMIT 1
                                            """
                                            suspicious_row = conn.execute(suspicious_query, (
                                                cid, pid, prov, prc, billed_amt, svc_dt
                                            )).fetchone()
                                            
                                            if suspicious_row:
                                                force_manual_review = True
                                                dup_type = "Historical Suspicious Duplicate"
                                                dup_reason = f"Suspicious duplicate pattern matching historical claim ID '{suspicious_row['claim_id']}'"
                                                dup_action = "Verify patient identity and prior claims"

                                # Record this valid claim's fingerprint in the within-batch memory maps
                                if not dup_status:
                                    processed_batch_exact.add(exact_fingerprint)
                                    processed_batch_claim_ids[cid] = exact_fingerprint
                                    processed_batch_suspicious.add(suspicious_fingerprint)
                                    
                                # Handle blocked duplicates immediately (no ML, no rules, no DB write)
                                if dup_status == "DUPLICATE_BLOCKED":
                                    processed_results.append({
                                        "claim_id": cid,
                                        "patient_id": pid,
                                        "provider_id": prov,
                                        "diagnosis_code": diag,
                                        "procedure_code": prc,
                                        "billed_amount": billed_amt,
                                        "service_date": svc_dt,
                                        "policy_id": pol,
                                        "status": "DUPLICATE_BLOCKED",
                                        "duplicate_type": dup_type,
                                        "risk_score_str": "—",
                                        "denial_prob": 0.0,
                                        "primary_reason": dup_reason,
                                        "policy_match": "N/A",
                                        "next_action": dup_action,
                                        "violations": [],
                                        "reasons": [],
                                        "recommendation": dup_reason,
                                        "outcome_key": "DUPLICATE_BLOCKED",
                                        "row_number": idx + 1
                                    })
                                    continue
                                    
                                # ── RULES ENGINE ──
                                exp_c = _exp_cost_map.get(prc, _exp_cost_mean) if prc else _exp_cost_mean
                                violations = []
                                
                                if not diag:
                                    violations.append({"rule_id":"R03","field":"diagnosis_code","message":"Diagnosis code is missing."})
                                elif diag not in _DIAG_DATA:
                                    violations.append({"rule_id":"R06","field":"diagnosis_code","message":f"Diagnosis code '{diag}' is not in approved ICD list."})
                                
                                if not prc:
                                    violations.append({"rule_id":"R04","field":"procedure_code","message":"Procedure code is missing."})
                                elif prc not in _COST_DATA:
                                    violations.append({"rule_id":"R07","field":"procedure_code","message":f"Procedure code '{prc}' is not in approved CPT list."})
                                
                                if not prov:
                                    violations.append({"rule_id":"R05","field":"provider_id","message":"Provider ID is required. Claims without a registered provider ID cannot be processed."})
                                elif prov not in _PROV_DATA:
                                    violations.append({"rule_id":"R05","field":"provider_id","message":"Provider ID not found in approved provider list."})
                                
                                if not pol:
                                    violations.append({"rule_id":"R12","field":"policy_id","message":"Policy ID is missing."})
                                elif pol not in _POLICY_DATA:
                                    violations.append({"rule_id":"R12","field":"policy_id","message":f"Policy ID '{pol}' is not in approved policy list."})

                                if not svc_dt:
                                    violations.append({"rule_id":"R09","field":"service_date","message":"Service date is missing."})
                                    
                                # ── Policy date active window and coverage validation ────
                                if pol and pol in _POLICY_DATA:
                                    p_meta = _POLICY_DATA[pol]
                                    covered_procs = [p.strip().upper() for p in p_meta.get("procedures_covered", "").split(",") if p.strip()]
                                    if prc and prc.upper() not in covered_procs:
                                        violations.append({
                                            "rule_id": "R10",
                                            "field": "policy_id",
                                            "message": f"Procedure '{prc}' is not covered under Policy '{pol}'."
                                        })
                                    
                                    start_date_str = p_meta.get("policy_start_date", "")
                                    end_date_str = p_meta.get("policy_end_date", "")
                                    
                                    if svc_dt:
                                        from datetime import datetime as dt
                                        try:
                                            if isinstance(svc_dt, str):
                                                svc_date_parsed = dt.strptime(svc_dt.split()[0], "%Y-%m-%d").date()
                                            else:
                                                svc_date_parsed = svc_dt
                                        except Exception:
                                            svc_date_parsed = None
                                            
                                        if svc_date_parsed:
                                            if start_date_str:
                                                try:
                                                    sd = dt.strptime(start_date_str, "%Y-%m-%d").date()
                                                    if svc_date_parsed < sd:
                                                        violations.append({
                                                            "rule_id": "R11",
                                                            "field": "service_date",
                                                            "message": f"Service date {svc_dt} is before the policy start date {start_date_str}."
                                                        })
                                                except Exception:
                                                    pass
                                            if end_date_str:
                                                try:
                                                    ed = dt.strptime(end_date_str, "%Y-%m-%d").date()
                                                    if svc_date_parsed > ed:
                                                        violations.append({
                                                            "rule_id": "R11",
                                                            "field": "service_date",
                                                            "message": f"Service date {svc_dt} is after the policy expiration deadline {end_date_str} (Policy expired)."
                                                        })
                                                except Exception:
                                                    pass
                                    
                                billing_verdict = "ACCEPT"
                                if billed_amt is None or billed_amt == 0.0:
                                    violations.append({"rule_id":"R02","field":"billed_amount","message":"Billed amount is missing or zero."})
                                    billing_verdict = "AUTO_REJECT_MISSING"
                                elif billed_amt > 1.75 * exp_c:
                                    violations.append({"rule_id":"R02b","field":"billed_amount","message":f"Billed amount ₹{billed_amt:,.0f} exceeds 175% of expected cost (₹{exp_c:,.0f})."})
                                    billing_verdict = "AUTO_REJECT_HIGH"
                                elif exp_c > 0:
                                    ratio = billed_amt / exp_c
                                    if ratio > 1.25:
                                        billing_verdict = "CONDITIONAL"
                                    elif ratio > 1.15:
                                        billing_verdict = "FLAG_HIGH_WARN"
                                    elif ratio < 0.50:
                                        billing_verdict = "FLAG_VERY_LOW"
                                    elif ratio < 0.75:
                                        billing_verdict = "FLAG_LOW"
                                    elif ratio < 0.85:
                                        billing_verdict = "FLAG_LOW_WARN"
                                        
                                if violations:
                                    processed_results.append({
                                        "claim_id": cid,
                                        "patient_id": pid,
                                        "provider_id": prov,
                                        "diagnosis_code": diag,
                                        "procedure_code": prc,
                                        "billed_amount": billed_amt,
                                        "service_date": svc_dt,
                                        "policy_id": pol,
                                        "status": "REJECTED",
                                        "duplicate_type": dup_type,
                                        "risk_score_str": "100%",
                                        "denial_prob": 1.0,
                                        "primary_reason": "; ".join([v["message"] for v in violations]),
                                        "policy_match": "N/A",
                                        "next_action": "Correct rule violations and resubmit.",
                                        "violations": violations,
                                        "reasons": [],
                                        "recommendation": "Fix administrative requirements before resubmission.",
                                        "outcome_key": "RULE_DENY",
                                        "row_number": idx + 1
                                    })
                                    try:
                                        _save_claim_history(cid, "RULE_DENY", 1.0, "CRITICAL", 
                                                            {"claim_id": cid, "outcome": "RULE_DENY", "violations": violations}, 
                                                            billed_amt, exp_c, prc, diag, prov,
                                                            svc_dt, pol, pid)
                                    except:
                                        pass
                                    continue
                                    
                                # ── ML PIPELINE PREPARATION ──
                                claims_payload.append({
                                    "claim_id":       cid,
                                    "patient_id":     pid,
                                    "provider_id":    prov or None,
                                    "diagnosis_code": diag or None,
                                    "procedure_code": prc or None,
                                    "billed_amount":  billed_amt,
                                    "service_date":   svc_dt,
                                    "policy_id":      pol or None,
                                })
                                claim_details_map[cid] = {
                                    "claim_id": cid,
                                    "patient_id": pid,
                                    "provider_id": prov,
                                    "diagnosis_code": diag,
                                    "procedure_code": prc,
                                    "billed_amount": billed_amt,
                                    "service_date": svc_dt,
                                    "policy_id": pol,
                                    "exp_c": exp_c,
                                    "billing_verdict": billing_verdict,
                                    "dup_type": dup_type,
                                    "dup_reason": dup_reason,
                                    "dup_action": dup_action,
                                    "is_revised": is_revised_resubmission,
                                    "force_manual_review": force_manual_review,
                                    "row_number": idx + 1
                                }
                                
                            conn.close()

                            # ── ML PIPELINE: call /predict-claim in a loop ──
                            if claims_payload:
                                progress_bar = st.progress(0, text="Running ML pipeline…")
                                n = len(claims_payload)
                                for idx, claim_payload in enumerate(claims_payload):
                                    cid = claim_payload["claim_id"]
                                    details = claim_details_map[cid]
                                    progress_bar.progress((idx + 1) / n, text=f"Analysing claim {idx+1}/{n}: {cid}")
                                    
                                    try:
                                        api_res = call_predict(claim_payload)
                                    except Exception as e:
                                        api_res = {}

                                    if not api_res:
                                        processed_results.append({
                                            "claim_id": cid,
                                            "patient_id": details["patient_id"],
                                            "provider_id": details["provider_id"],
                                            "diagnosis_code": details["diagnosis_code"],
                                            "procedure_code": details["procedure_code"],
                                            "billed_amount": details["billed_amount"],
                                            "service_date": details["service_date"],
                                            "policy_id": details["policy_id"],
                                            "status": "INVALID_INPUT",
                                            "duplicate_type": details["dup_type"],
                                            "risk_score_str": "—",
                                            "denial_prob": 0.0,
                                            "primary_reason": "API call failed. Check server connection.",
                                            "policy_match": "N/A",
                                            "next_action": "Retry after fixing server connection.",
                                            "violations": [],
                                            "reasons": [],
                                            "recommendation": "Check API server.",
                                            "outcome_key": "INVALID_INPUT",
                                            "_service_date": details["service_date"],
                                            "billing_verdict": details["billing_verdict"],
                                            "expected_cost": details["exp_c"],
                                            "row_number": details["row_number"]
                                        })
                                        continue

                                    ml_status = api_res.get("predicted_status", "APPROVED")
                                    prob      = api_res.get("denial_prob", 0.0)
                                    risk      = api_res.get("risk_level", "LOW")
                                    reasons   = api_res.get("reasons", [])
                                    recom     = api_res.get("recommendation", "")
                                    primary   = api_res.get("primary_reason", reasons[0]["explanation"] if reasons else "")

                                    # Use same granular outcome logic as single claim
                                    outcome, base_decision = _compute_granular_outcome(
                                        ml_status, prob, details["billing_verdict"]
                                    )

                                    if details["is_revised"]:
                                        status = "REVISED_RESUBMISSION"
                                        action_out = details["dup_action"] or "Re-analyse after correction."
                                    elif details["force_manual_review"]:
                                        status = "MANUAL_REVIEW"
                                        action_out = details["dup_action"] or "Route to supervisor for manual review."
                                    elif outcome == "APPROVED":
                                        status = "APPROVED"
                                        action_out = "Submit"
                                    elif outcome == "APPROVED_WITH_WARNING":
                                        status = "APPROVED_WITH_WARNING"
                                        action_out = "Verify warning flags and transmit."
                                    elif outcome == "MANUAL_REVIEW":
                                        status = "MANUAL_REVIEW"
                                        action_out = "Route to supervisor for manual review."
                                    elif outcome == "AT_RISK":
                                        status = "AT_RISK"
                                        action_out = "Mitigate risk drivers before resubmission."
                                    else:
                                        status = "REJECTED"
                                        action_out = "Mitigate risk drivers before resubmission."

                                    policy_match = (
                                        "RAG Match: Approved Policy Criteria"
                                        if "APPROVED" in status or "RESUBMISSION" in status
                                        else "RAG Match: Policy Exception Detected"
                                    )

                                    processed_results.append({
                                        "claim_id": cid,
                                        "patient_id": details["patient_id"],
                                        "provider_id": details["provider_id"],
                                        "diagnosis_code": details["diagnosis_code"],
                                        "procedure_code": details["procedure_code"],
                                        "billed_amount": details["billed_amount"],
                                        "service_date": details["service_date"],
                                        "policy_id": details["policy_id"],
                                        "status": status,
                                        "duplicate_type": details["dup_type"],
                                        "risk_score_str": f"{prob*100:.0f}%",
                                        "denial_prob": prob,
                                        "primary_reason": details["dup_reason"] if details["dup_reason"] else primary,
                                        "policy_match": policy_match,
                                        "next_action": action_out,
                                        "violations": [],
                                        "reasons": reasons,
                                        "recommendation": recom or details["dup_reason"],
                                        "outcome_key": outcome,
                                        "_service_date": details["service_date"],
                                        "billing_verdict": details["billing_verdict"],
                                        "expected_cost": details["exp_c"],
                                        "base_decision": base_decision,
                                        "billing_ratio": api_res.get("billing_ratio", 
                                            details["billed_amount"] / details["exp_c"] if details["exp_c"] > 0 else 1.0),
                                        "row_number": details["row_number"]
                                    })

                                    try:
                                        _save_claim_history(
                                            cid, status, prob, risk,
                                            {**api_res, "predicted_status": ml_status, "outcome": status, "billing_verdict": details["billing_verdict"],
                                             "expected_cost": details["exp_c"]},
                                            details["billed_amount"], details["exp_c"],
                                            details["procedure_code"], details["diagnosis_code"],
                                            details["provider_id"], details["service_date"],
                                            details["policy_id"], details["patient_id"]
                                        )
                                    except Exception:
                                        pass

                                progress_bar.empty()

                            st.session_state["processed_batch_results"] = processed_results
                            st.rerun()
                            
        # Clear batch results if file is changed or uploader is empty
        if "batch_file_uploader" in st.session_state and st.session_state["batch_file_uploader"] is None:
            if "processed_batch_results" in st.session_state:
                del st.session_state["processed_batch_results"]
                
        # Render Processed Batch Results
        if "processed_batch_results" in st.session_state and st.session_state["processed_batch_results"]:
            processed_results = st.session_state["processed_batch_results"]
            
            st.markdown("---")
            # --- LEVEL 1: Batch-level summary ---
            st.markdown("### Batch Adjudication Summary")
            
            n_total = len(processed_results)
            n_approved = sum(1 for r in processed_results if r["status"] == "APPROVED")
            n_warning = sum(1 for r in processed_results if r["status"] == "APPROVED_WITH_WARNING")
            n_manual = sum(1 for r in processed_results if r["status"] == "MANUAL_REVIEW")
            n_rejected = sum(1 for r in processed_results if r["status"] == "REJECTED")
            n_duplicate = sum(1 for r in processed_results if r["status"] == "DUPLICATE_BLOCKED")
            n_revised = sum(1 for r in processed_results if r["status"] == "REVISED_RESUBMISSION")
            n_invalid = sum(1 for r in processed_results if r["status"] == "INVALID_INPUT")
            
            st.markdown(f"""
            <div style="
                display: flex;
                flex-wrap: wrap;
                gap: 12px;
                margin-bottom: 24px;
                font-family: Inter, sans-serif;
            ">
                <div style="flex: 1; min-width: 130px; background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1)">
                    <div style="font-size: 0.65rem; color: #8b949e; text-transform: uppercase; font-weight: 700">Total Rows</div>
                    <div style="font-size: 1.6rem; font-weight: 800; color: #e6edf3; margin-top: 4px">{n_total}</div>
                </div>
                <div style="flex: 1; min-width: 130px; background: #1f3625; border: 1px solid #2ea44f; border-radius: 8px; padding: 12px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1)">
                    <div style="font-size: 0.65rem; color: #8b949e; text-transform: uppercase; font-weight: 700">Approved</div>
                    <div style="font-size: 1.6rem; font-weight: 800; color: #3fb950; margin-top: 4px">{n_approved + n_warning}</div>
                </div>
                <div style="flex: 1; min-width: 130px; background: #281d37; border: 1px solid #ab7df8; border-radius: 8px; padding: 12px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1)">
                    <div style="font-size: 0.65rem; color: #8b949e; text-transform: uppercase; font-weight: 700">Manual Review</div>
                    <div style="font-size: 1.6rem; font-weight: 800; color: #ab7df8; margin-top: 4px">{n_manual}</div>
                </div>
                <div style="flex: 1; min-width: 130px; background: #3c1e1e; border: 1px solid #f85149; border-radius: 8px; padding: 12px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1)">
                    <div style="font-size: 0.65rem; color: #8b949e; text-transform: uppercase; font-weight: 700">Rejected</div>
                    <div style="font-size: 1.6rem; font-weight: 800; color: #f85149; margin-top: 4px">{n_rejected}</div>
                </div>
                <div style="flex: 1; min-width: 130px; background: #21262d; border: 1px solid #8b949e; border-radius: 8px; padding: 12px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1)">
                    <div style="font-size: 0.65rem; color: #8b949e; text-transform: uppercase; font-weight: 700">Duplicate Blocked</div>
                    <div style="font-size: 1.6rem; font-weight: 800; color: #8b949e; margin-top: 4px">{n_duplicate}</div>
                </div>
                <div style="flex: 1; min-width: 130px; background: #1b263b; border: 1px solid #52b788; border-radius: 8px; padding: 12px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1)">
                    <div style="font-size: 0.65rem; color: #8b949e; text-transform: uppercase; font-weight: 700">Revised Resub.</div>
                    <div style="font-size: 1.6rem; font-weight: 800; color: #52b788; margin-top: 4px">{n_revised}</div>
                </div>
                <div style="flex: 1; min-width: 130px; background: #2f2516; border: 1px solid #e3b341; border-radius: 8px; padding: 12px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1)">
                    <div style="font-size: 0.65rem; color: #8b949e; text-transform: uppercase; font-weight: 700">Invalid Rows</div>
                    <div style="font-size: 1.6rem; font-weight: 800; color: #e3b341; margin-top: 4px">{n_invalid}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # --- LEVEL 2: Claim-level results table ---
            st.markdown("### Processed Claims Table")
            
            all_statuses = ["APPROVED", "APPROVED_WITH_WARNING", "MANUAL_REVIEW", "REJECTED", "DUPLICATE_BLOCKED", "REVISED_RESUBMISSION", "INVALID_INPUT"]
            selected_filter = st.multiselect(
                "Filter by Adjudication Status",
                all_statuses,
                default=all_statuses
            )
            
            table_data = []
            for r in processed_results:
                table_data.append({
                    "Claim ID": r["claim_id"],
                    "Status": r["status"],
                    "Duplicate Type": r["duplicate_type"],
                    "Risk": r["risk_score_str"],
                    "Reason": r["primary_reason"],
                    "Action": r["next_action"]
                })
            
            df_table = pd.DataFrame(table_data)
            if selected_filter:
                df_table_filtered = df_table[df_table["Status"].isin(selected_filter)]
            else:
                df_table_filtered = df_table
                
            def _colour_row(row):
                colour = ""
                status = row.get("Status")
                if status == "APPROVED":
                    colour = "background-color: #162a1b; color: #3fb950"
                elif status == "APPROVED_WITH_WARNING":
                    colour = "background-color: #2b210e; color: #e3b341"
                elif status == "MANUAL_REVIEW":
                    colour = "background-color: #201335; color: #ab7df8"
                elif status == "REVISED_RESUBMISSION":
                    colour = "background-color: #1b263b; color: #52b788"
                elif status in ("REJECTED", "DUPLICATE_BLOCKED", "INVALID_INPUT"):
                    colour = "background-color: #2b1616; color: #f85149"
                return [colour] * len(row)
                
            if not df_table_filtered.empty:
                styled_df = df_table_filtered.style.apply(
                    lambda row: _colour_row(row.to_dict()), axis=1
                )
                st.dataframe(styled_df, use_container_width=True, hide_index=True)
            else:
                st.info("No claims match the selected filters.")
                
            # --- Claim Explorer Panel ---
            st.markdown("---")
            st.markdown("### Per-Claim Explainability Explorer")
            
            valid_ids = [r["claim_id"] for r in processed_results]
            sel_cid = st.selectbox("Select a claim ID to deep-dive", valid_ids)
            
            if sel_cid:
                claim_details = next(r for r in processed_results if r["claim_id"] == sel_cid)
                
                exp_c1, exp_c2, exp_c3 = st.columns(3)
                with exp_c1:
                    status_val = claim_details["status"]
                    if status_val == "APPROVED":
                        dec_html = '<span style="background:#163c1e; color:#3fb950; border:1px solid #2ea44f; padding:4px 8px; border-radius:4px; font-weight:bold">APPROVED</span>'
                    elif status_val == "APPROVED_WITH_WARNING":
                        dec_html = '<span style="background:#3c2f16; color:#e3b341; border:1px solid #d29922; padding:4px 8px; border-radius:4px; font-weight:bold">APPROVED WITH WARNING</span>'
                    elif status_val == "MANUAL_REVIEW":
                        dec_html = '<span style="background:#281d37; color:#ab7df8; border:1px solid #ab7df8; padding:4px 8px; border-radius:4px; font-weight:bold">MANUAL REVIEW</span>'
                    elif status_val == "REVISED_RESUBMISSION":
                        dec_html = '<span style="background:#1b263b; color:#52b788; border:1px solid #52b788; padding:4px 8px; border-radius:4px; font-weight:bold">REVISED RESUBMISSION</span>'
                    else:
                        dec_html = '<span style="background:#3c1e1e; color:#f85149; border:1px solid #f85149; padding:4px 8px; border-radius:4px; font-weight:bold">' + status_val.replace("_", " ") + '</span>'
                        
                    st.markdown(f"**Decision Status:** {dec_html}", unsafe_allow_html=True)
                    st.markdown(f"**Billed Amount:** ₹{claim_details['billed_amount']:,.2f}")
                    
                with exp_c2:
                    st.markdown(f"**Denial Risk Score:** `{claim_details['risk_score_str']}`")
                    st.markdown(f"**Patient ID:** `{claim_details['patient_id']}` | **Provider ID:** `{claim_details['provider_id']}`")
                    
                with exp_c3:
                    st.markdown(f"**Next Action:** `{claim_details['next_action']}`")
                    st.markdown(f"**Policy ID:** `{claim_details['policy_id']}`")
                    
                st.markdown("**Matched Policy Clause / Verification Logic:**")
                st.markdown(f"<div class='policy-box'>{claim_details['policy_match']}<br><em>Adjudication Rationale: {claim_details['primary_reason']}</em></div>", unsafe_allow_html=True)
                
                if claim_details.get("violations"):
                    st.markdown("**Rule Violations Detected:**")
                    for v in claim_details["violations"]:
                        st.markdown(f"- **{v.get('field','').replace('_',' ').title()}**: {v['message']}")

                # ── Render full output matching single-claim view ──────────────────────
                outcome_key  = claim_details.get("outcome_key", claim_details.get("status", "APPROVED"))
                prob         = claim_details.get("denial_prob", 0.0)
                risk         = claim_details.get("risk_score_str", "0%").replace("%","")
                try:
                    risk_val = float(risk)
                except ValueError:
                    risk_val = prob * 100.0
                risk_label   = "HIGH" if risk_val >= 65 else ("MEDIUM" if risk_val >= 35 else "LOW")
                reasons      = claim_details.get("reasons", [])
                billed_amt   = claim_details.get("billed_amount", 0.0) or 0.0
                exp_c        = claim_details.get("expected_cost", 0.0) or 0.0
                bv           = claim_details.get("billing_verdict", "ACCEPT")
                b_ratio      = claim_details.get("billing_ratio", billed_amt / exp_c if exp_c > 0 else 1.0)
                proc_code    = claim_details.get("procedure_code", "")
                diag_code    = claim_details.get("diagnosis_code", "")
                provider_id  = claim_details.get("provider_id", "")

                # Build a result dict compatible with render helpers
                _batch_res = {
                    **claim_details,
                    "outcome": outcome_key,
                    "billing_verdict": bv,
                    "billed_amount": billed_amt,
                    "expected_cost": exp_c,
                    "billing_ratio": b_ratio,
                    "denial_prob": prob,
                    "risk_level": risk_label,
                    "reasons": reasons,
                    "_service_date": claim_details.get("_service_date") or claim_details.get("service_date"),
                }

                if status_val in ("DUPLICATE_BLOCKED", "INVALID_INPUT"):
                    st.warning(f"**Action Required**: This claim was blocked during pre-processing due to: **{claim_details['primary_reason']}**.")
                    st.info(f"**Suggested Fix**: {claim_details['next_action']}")
                else:
                    st.session_state["last_result"] = _batch_res
                    st.session_state["last_claim_dup_status"] = "DUPLICATE_ID" if status_val == "REVISED_RESUBMISSION" else "NEW"
                    
                    st.markdown("---")
                    _render_decision_banner(outcome_key, prob, risk_label)

                    # btab1, btab2, btab3 = st.tabs(["XAI Explanation", "Policy Docs", "Claim Fix Wizard"])
                    # with btab1:
                    #     _render_xai_tab(outcome_key, reasons, prob)
                    # with btab2:
                    #     _render_policy_tab(outcome_key, reasons, _batch_res)
                    # with btab3:
                    #     _render_fix_wizard_ml(
                    #         outcome_key, reasons, _batch_res,
                    #         billed_amt, exp_c, bv,
                    #         proc_code, diag_code, provider_id, b_ratio
                    #     )

            # --- LEVEL 3: Export/Download options at bottom ---
            st.markdown("---")
            st.markdown("### Export Processed Batch")
            
            exp_c1, exp_c2, exp_c3 = st.columns(3)
            with exp_c1:
                all_csv = df_table.to_csv(index=False)
                st.download_button(
                    "Export ALL Batch Results (CSV)",
                    data=all_csv,
                    file_name=f"batch_results_all_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
                
            with exp_c2:
                flagged_table = []
                for r in processed_results:
                    if r["status"] != "APPROVED":
                        flagged_table.append({
                            "Claim ID": r["claim_id"],
                            "Status": r["status"],
                            "Duplicate Type": r["duplicate_type"],
                            "Risk Score": r["risk_score_str"],
                            "Primary Reason": r["primary_reason"],
                            "Policy Match": r["policy_match"],
                            "Next Action": r["next_action"]
                        })
                if flagged_table:
                    df_flagged = pd.DataFrame(flagged_table)
                    flagged_csv = df_flagged.to_csv(index=False)
                    st.download_button(
                        "Export Flagged Claims (CSV)",
                        data=flagged_csv,
                        file_name=f"batch_results_flagged_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                else:
                    st.button("No Flagged Claims in Batch", disabled=True, use_container_width=True)
                    
            with exp_c3:
                exceptions_data = []
                for r in processed_results:
                    if r["status"] in ("DUPLICATE_BLOCKED", "INVALID_INPUT"):
                        exceptions_data.append({
                            "Row Number": r.get("row_number", "—"),
                            "Claim ID": r["claim_id"],
                            "Duplicate Type": r["duplicate_type"],
                            "Reason": r["primary_reason"],
                            "Suggested Fix": r["next_action"]
                        })
                if exceptions_data:
                    df_exceptions = pd.DataFrame(exceptions_data)
                    exceptions_csv = df_exceptions.to_csv(index=False)
                    st.download_button(
                        "Download Exception Report (CSV)",
                        data=exceptions_csv,
                        file_name=f"batch_exceptions_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                else:
                    st.button("No Exceptions in Batch", disabled=True, use_container_width=True)

    # ══════════════════════════════════════════════════════════════════════════
    # MANUAL ENTRY & REVIEW (Single Claim mode only)
    # ══════════════════════════════════════════════════════════════════════════
    if upload_mode == "Single Claim":
        st.markdown("---")
        st.markdown("### Manual Claim Submission")

        def get_idx(opts, val):
            return opts.index(val) if val in opts else 0

        with st.container():
            st.markdown("Claim Identifiers")
            id_c1, id_c2, id_c3 = st.columns(3)
            with id_c1:
                claim_id = st.text_input(
                    "Claim ID *", placeholder="C0001", key="form_claim_id"
                )
                claim_invalid = bool(claim_id and not re.match(r"^C\d{4}$", claim_id))
                if claim_invalid:
                    st.error("Invalid format: required format CXXXX")
                    st.markdown("<style>div[data-testid='column']:nth-child(1) input { border: 2px solid #ff4b4b !important; }</style>", unsafe_allow_html=True)

            with id_c2:
                patient_id = st.text_input(
                    "Patient ID *", placeholder="P206", key="form_patient_id"
                )
                patient_invalid = bool(patient_id and not re.match(r"^P\d{3}$", patient_id))
                if patient_invalid:
                    st.error("Invalid format: required format PXXX")
                    st.markdown("<style>div[data-testid='column']:nth-child(2) input { border: 2px solid #ff4b4b !important; }</style>", unsafe_allow_html=True)

            with id_c3:
                svc_date = st.date_input("Service Date *", value=st.session_state.get("form_svc_date", None), key="form_svc_date")

            st.markdown("Clinical Details")
            cl_c1, cl_c2, cl_c3 = st.columns(3)
        
            prov_opts = [""] + prov_options
            diag_opts = [""] + diag_options
            proc_opts = [""] + proc_options
            pol_opts  = [""] + policy_options
        
            with cl_c1:
                provider_id = st.selectbox(
                    "Provider ID", options=prov_opts,
                    index=get_idx(prov_opts, st.session_state.get("form_provider_id", "")),
                    help="Select the treating provider from the approved provider list.")
            with cl_c2:
                diag_code = st.selectbox(
                    "Diagnosis Code", options=diag_opts,
                    index=get_idx(diag_opts, st.session_state.get("form_diag_code", "")),
                    help="ICD diagnosis code from approved list (e.g. D10=Heart, D20=Bone).")
            with cl_c3:
                proc_code = st.selectbox(
                    "Procedure Code", options=proc_opts,
                    index=get_idx(proc_opts, st.session_state.get("form_proc_code", "")),
                    help="Procedure code from approved CPT list.")

            if proc_code:
                exp_hint = _exp_cost_map.get(proc_code, _exp_cost_mean)
                st.caption(f"Expected cost for **{proc_code}**: ₹{exp_hint:,.0f}")

            st.markdown("Billing & Policy")
            bill_col, pol_col, _ = st.columns([1, 1, 1])
            with bill_col:
                billed_amt = st.number_input(
                    "Billed Amount (₹)", min_value=0.0, step=100.0,
                    value=st.session_state.get("form_billed_amount", None),
                    key="form_billed_amount",
                    help="Enter the total amount billed. Zero = auto-rejected.")
            with pol_col: 
                policy_id = st.selectbox(
                    "Policy ID *", options=pol_opts,
                    index=get_idx(pol_opts, st.session_state.get("form_policy_id", "")),
                    help="Select the policy to validate procedure coverage and dates.")
        
            submitted = st.button("Analyse Claim", use_container_width=True, type="primary")

        # ── Pipeline on submit ──────────────────────────────────────────────────────
        if submitted:
            has_error = False
        
            if not claim_id or claim_invalid:
                if not claim_id:
                    st.error("Claim ID is required.")
                    st.markdown("<style>div[data-testid='column']:nth-child(1) input { border: 2px solid #ff4b4b !important; }</style>", unsafe_allow_html=True)
                has_error = True
            
            if not patient_id or patient_invalid:
                if not patient_id:
                    st.error("Patient ID is required.")
                    st.markdown("<style>div[data-testid='column']:nth-child(2) input { border: 2px solid #ff4b4b !important; }</style>", unsafe_allow_html=True)
                has_error = True
            
            if not svc_date:
                st.error("Service Date is required.")
                has_error = True
            
            if not policy_id:
                st.error("Policy ID is required.")
                has_error = True
            
            if has_error:
                st.stop()

            # ── Duplicate Checks ───────────────────────────────────────────────────
            dup_type, dup_msg, dup_row = _check_duplicate_claim(
                claim_id, provider_id, diag_code, proc_code, billed_amt,
                service_date=svc_date.isoformat() if svc_date else None,
                policy_id=policy_id or None,
                patient_id=patient_id or None,
            )
            if dup_type == "ENTIRE_DUPLICATE":
                st.error(f"**Duplicate Submission Blocked**: {dup_msg} Duplicate entries are blocked to prevent redundancy and waste of compute resources.")
                st.stop()
            elif dup_type == "DUPLICATE_ID":
                st.session_state["last_claim_dup_status"] = "DUPLICATE_ID"
            else:
                st.session_state["last_claim_dup_status"] = "NEW"

            exp_c = _exp_cost_map.get(proc_code, _exp_cost_mean) if proc_code else _exp_cost_mean

            # ── Rule Engine (R01–R09) ───────────────────────────────────────────────
            violations = []
            if not claim_id.strip():
                violations.append({"rule_id":"R01","field":"claim_id","message":"Claim ID is missing."})
            if not patient_id.strip():
                violations.append({"rule_id":"R08","field":"patient_id","message":"Patient ID is missing."})
            if not diag_code:
                violations.append({"rule_id":"R03","field":"diagnosis_code","message":"Diagnosis code is missing."})
            elif diag_code not in _DIAG_DATA:
                violations.append({"rule_id":"R06","field":"diagnosis_code","message":f"Diagnosis code '{diag_code}' is not in the approved ICD code list."})
            if not proc_code:
                violations.append({"rule_id":"R04","field":"procedure_code","message":"Procedure code is missing."})
                exp_c = 0.0  # Override expected cost to 0 if procedure code is missing, to trigger billing violation
            elif proc_code not in _COST_DATA:
                violations.append({"rule_id":"R07","field":"procedure_code","message":f"Procedure code '{proc_code}' is not in the approved CPT code list."})
            if not provider_id:
                violations.append({"rule_id":"R05","field":"provider_id","message":"Provider ID is required. Claims without a registered provider ID cannot be processed."})
            elif provider_id not in _PROV_DATA:
                violations.append({"rule_id":"R05","field":"provider_id","message":"Provider ID not found in approved provider list."})
            if svc_date is None:
                violations.append({"rule_id":"R09","field":"claim_date","message":"Claim date is missing."})
            elif svc_date > date.today():
                violations.append({"rule_id":"R09","field":"claim_date","message":"Claim date is in the future."})

            # ── Policy date active window and coverage validation (R10 and R11) ────
            if policy_id and policy_id in _POLICY_DATA:
                p_meta = _POLICY_DATA[policy_id]
                covered_procs = [p.strip().upper() for p in p_meta.get("procedures_covered", "").split(",") if p.strip()]
                if proc_code and proc_code.upper() not in covered_procs:
                    violations.append({
                        "rule_id": "R10",
                        "field": "policy_id",
                        "message": f"Procedure '{proc_code}' is not covered under Policy '{policy_id}'."
                    })
                
                start_date_str = p_meta.get("policy_start_date", "")
                end_date_str = p_meta.get("policy_end_date", "")
                
                if svc_date:
                    from datetime import datetime
                    if start_date_str:
                        try:
                            sd = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                            if svc_date < sd:
                                violations.append({
                                    "rule_id": "R11",
                                    "field": "service_date",
                                    "message": f"Service date {svc_date} is before the policy start date {start_date_str}."
                                })
                        except Exception:
                            pass
                    if end_date_str:
                        try:
                            ed = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                            if svc_date > ed:
                                violations.append({
                                    "rule_id": "R11",
                                    "field": "service_date",
                                    "message": f"Service date {svc_date} is after the policy expiration deadline {end_date_str} (Policy expired)."
                                })
                        except Exception:
                            pass

            # Billing verdict
            billing_verdict = "ACCEPT"
            if billed_amt is None or billed_amt == 0.0:
                violations.append({"rule_id":"R02","field":"billed_amount","message":"Billed amount is missing or zero."})
                billing_verdict = "AUTO_REJECT_MISSING"
            elif billed_amt > 1.75 * exp_c:
                violations.append({"rule_id":"R02b","field":"billed_amount",
                                    "message":f"Billed amount ₹{billed_amt:,.0f} exceeds 175% of expected cost (₹{exp_c:,.0f})."})
                billing_verdict = "AUTO_REJECT_HIGH"
            elif exp_c > 0:
                ratio = billed_amt / exp_c
                if ratio > 1.25:
                    billing_verdict = "CONDITIONAL"
                elif ratio > 1.15:
                    billing_verdict = "FLAG_HIGH_WARN"
                elif ratio < 0.50:
                    billing_verdict = "FLAG_VERY_LOW"
                elif ratio < 0.75:
                    billing_verdict = "FLAG_LOW"
                elif ratio < 0.85:
                    billing_verdict = "FLAG_LOW_WARN"

            # Low-bill banners (shown alongside ML, do not block)
            if billing_verdict == "FLAG_VERY_LOW":
                st.error(f"Very Low Billing Alert: ₹{billed_amt:,.0f} is less than 50% of expected ₹{exp_c:,.0f}. "
                         "This may indicate a billing error. Claim will still be evaluated.")
            elif billing_verdict in ("FLAG_LOW", "FLAG_LOW_WARN"):
                st.warning(f"Low Billing Alert: ₹{billed_amt:,.0f} is less than expected ₹{exp_c:,.0f}. "
                           "Please verify this is not an under-billing error.")
            elif billing_verdict == "FLAG_HIGH_WARN":
                st.warning(f"High Billing Alert: ₹{billed_amt:,.0f} is more than expected ₹{exp_c:,.0f}. "
                           "Please verify this is not an over-billing error.")

            # ── RULE DENY path ──────────────────────────────────────────────────────
            hard_violations = [v for v in violations if v["rule_id"] not in ("W01","W02","W03")]
            if hard_violations:
                st.session_state["last_result"] = {
                    "claim_id": claim_id.strip(), "outcome": "RULE_DENY",
                    "billing_verdict": billing_verdict, "violations": hard_violations,
                    "predicted_status": "DENIED", "denial_prob": 1.0,
                    "risk_level": "CRITICAL", "billing_ratio": billed_amt/exp_c if exp_c>0 and billed_amt is not None and billed_amt>0 else 0.0,
                    "expected_cost": exp_c, "reasons": [], "billed_amount": billed_amt if billed_amt is not None else 0.0,
                }
                st.session_state["last_claim_id"] = claim_id.strip()

                _render_claim_summary(claim_id.strip(), patient_id, provider_id,
                                      diag_code, proc_code, billed_amt, exp_c, svc_date)
                _render_decision_banner("RULE_DENY", 1.0, "CRITICAL")

                tab1, tab2 = st.tabs(["Rule Violations", "Policy Docs"])
                with tab1:
                    st.markdown("### Why This Claim Was Rejected")
                    for v in hard_violations:
                        st.markdown(f"- **{v['field'].replace('_',' ').title()}**: {v['message']}")
                    st.info("Rule-based rejections do not proceed to ML analysis. Please fix the listed issues and resubmit.")
                with tab2:
                    st.markdown("### Relevant Policy References")
                    for v in hard_violations[:2]:
                        with st.expander(f"Policy for: {v['field'].replace('_',' ').title()}  —   Directly caused rejection"):
                            st.markdown(f"<div class='policy-box'>Rule {v['rule_id']}: {v['message']}<br>"
                                        "Refer to the claim submission guidelines for mandatory field requirements.</div>",
                                        unsafe_allow_html=True)
            
                # Save rule deny history
                _save_claim_history(claim_id.strip(), "RULE_DENY", 1.0, "CRITICAL", 
                                    st.session_state["last_result"], billed_amt, exp_c, proc_code, diag_code, provider_id,
                                    svc_date.isoformat() if svc_date else None, policy_id, patient_id)

            # ── ML path ────────────────────────────────────────────────────────────
            else:
                payload = {
                    "claim_id":       claim_id.strip(),
                    "patient_id":     patient_id.strip() or None,
                    "provider_id":    provider_id or None,
                    "diagnosis_code": diag_code or None,
                    "procedure_code": proc_code or None,
                    "billed_amount":  billed_amt,
                    "service_date":   svc_date.isoformat() if svc_date else None,
                    "policy_id":      policy_id or None,
                }
                with st.spinner("Analysing claim… Running ML inference + RAG retrieval."):
                    result = call_predict(payload)

                if result:
                    b_ratio = result.get("billing_ratio", billed_amt/exp_c if exp_c>0 else 1.0)
                    prob    = result.get("denial_prob", 0)
                    status  = result.get("predicted_status", "APPROVED")
                    risk    = result.get("risk_level", "MEDIUM")
                    reasons = result.get("reasons", [])

                    # Determine granular outcome (ML base decision preserved)
                    outcome, base_decision = _compute_granular_outcome(
                        status, prob, billing_verdict
                    )

                    st.session_state["last_result"] = {
                        **result,
                        "outcome": outcome,
                        "base_decision": base_decision,   # raw ML APPROVED/DENIED
                        "billing_verdict": billing_verdict,
                        "billed_amount": billed_amt,
                        "expected_cost": exp_c,
                        "_provider_id": provider_id,
                        "_diag_code": diag_code,
                        "_proc_code": proc_code,
                        "_service_date": svc_date,
                    }
                    st.session_state["last_claim_id"] = claim_id.strip()

                    _render_claim_summary(claim_id.strip(), patient_id, provider_id,
                                          diag_code, proc_code, billed_amt, exp_c, svc_date)
                    _render_decision_banner(outcome, prob, risk)



                    if result.get("error_code"):
                        st.warning(f"Partial result (RAG unavailable): {result['error_code']}. Showing ML results only.")

                    tab1, tab2 = st.tabs(["XAI Explanation", "Policy Docs"])
                    with tab1:
                        _render_xai_tab(outcome, reasons, prob)
                    with tab2:
                        _render_policy_tab(outcome, reasons, result)

                    # Download report
                    import json as _json
                    report = {
                        "claim_id": claim_id.strip(), "outcome": outcome,
                        "denial_probability": prob, "approval_probability": round(1-prob,4),
                        "risk_level": risk, "billing_verdict": billing_verdict,
                        "billed_amount": billed_amt, "expected_cost": exp_c,
                        "top_reasons": [{"feature":r["feature"],"explanation":r["explanation"],
                                         "impact":r.get("impact_score")} for r in reasons],
                        "recommendation": result.get("recommendation",""),
                        "next_action": result.get("next_action",""),
                    }
                    st.download_button("Download Claim Report (JSON)",
                        data=_json.dumps(report, indent=2),
                        file_name=f"claim_report_{claim_id.strip()}.json",
                        mime="application/json")
                    
                    # Save ML processed history
                    _save_claim_history(claim_id.strip(), outcome, prob, risk, 
                                        st.session_state["last_result"], billed_amt, exp_c, proc_code, diag_code, provider_id,
                                        svc_date.isoformat() if svc_date else None, policy_id, patient_id)

# ── Page: Claim Search & Audit Trail ──────────────────────────────────────────
elif page == "Claim Search & Audit Trail":
    import sqlite3
    import pandas as pd
    import datetime

    st.markdown("#  Claim Search & Audit Trail")
    st.markdown("Search, audit, and compare every claim you have submitted.")

    # ── Auth guard (spec §3.4) ────────────────────────────────────────────────
    current_user_email = st.session_state.get("sb_email", "")
    if not current_user_email and hasattr(st, "user"):
        try:
            if st.user.is_logged_in and st.user.email:
                current_user_email = st.user.email
        except Exception:
            pass

    if not current_user_email:
        st.error("You must be signed in to view the audit trail.")
        st.stop()

    # ── Session state for filter values ──────────────────────────────────────
    for _k, _v in [
        ("audit_search_cid", ""), ("audit_search_pid", ""),
        ("audit_search_prov", ""), ("audit_search_pol", ""),
        ("audit_search_status", "All"), ("audit_selected_claim", None),
    ]:
        if _k not in st.session_state:
            st.session_state[_k] = _v

    # ── Zone 1 — Search & Filter Bar (spec §7) ───────────────────────────────
    with st.container(border=True):
        # Signed-in user context line (spec §7.3)
        st.markdown(
            f"<div style='font-size:0.82rem; color:#8b949e; margin-bottom:8px'>"
            f"Showing claims submitted by: <code style='color:#3fb950'>{current_user_email}</code>"
            f"</div>",
            unsafe_allow_html=True
        )
        st.markdown("#### Search Filters")

        # 3-column grid per spec §7.1
        col1, col2, col3 = st.columns(3)
        with col1:
            st.session_state["audit_search_cid"] = st.text_input(
                "Claim ID", value=st.session_state["audit_search_cid"],
                placeholder="e.g. C0001"
            ).strip().upper()
            st.session_state["audit_search_pol"] = st.text_input(
                "Policy ID", value=st.session_state["audit_search_pol"],
                placeholder="e.g. POL002"
            ).strip().upper()
        with col2:
            st.session_state["audit_search_pid"] = st.text_input(
                "Patient ID", value=st.session_state["audit_search_pid"],
                placeholder="e.g. P101"
            ).strip().upper()
            # Status dropdown per spec §7.2 — exact predicted_status values
            status_options = ["All", "APPROVED", "DENIED", "MANUAL_REVIEW"]
            cur_status = st.session_state["audit_search_status"]
            if cur_status not in status_options:
                cur_status = "All"
            st.session_state["audit_search_status"] = st.selectbox(
                "Status Filter", status_options,
                index=status_options.index(cur_status)
            )
        with col3:
            st.session_state["audit_search_prov"] = st.text_input(
                "Provider ID", value=st.session_state["audit_search_prov"],
                placeholder="e.g. PR101"
            ).strip().upper()
            # Date range — default 2000-01-01 → today+1 (spec §7.2)
            dr_c1, dr_c2 = st.columns(2)
            with dr_c1:
                start_dt = st.date_input("Start Date", value=datetime.date(2000, 1, 1))
            with dr_c2:
                end_dt = st.date_input("End Date",
                                       value=datetime.date.today() + datetime.timedelta(days=365))

        btn_c1, btn_c2, _ = st.columns([1, 1, 4])
        with btn_c1:
            st.button("Search", type="primary", use_container_width=True)
        with btn_c2:
            if st.button("Reset", use_container_width=True):
                for _k, _v in [
                    ("audit_search_cid", ""), ("audit_search_pid", ""),
                    ("audit_search_prov", ""), ("audit_search_pol", ""),
                    ("audit_search_status", "All"), ("audit_selected_claim", None),
                ]:
                    st.session_state[_k] = _v
                st.rerun()

    # ── Pre-fetch user-scoped duplicate map (spec §10) ────────────────────────
    # Must include submitted_by = ? so cross-user duplicate signals never leak
    dup_map = {}
    version_count_map = {}
    try:
        _conn = _get_db_conn()
        _dup_rows = _conn.execute("""
            SELECT provider_id, diagnosis_code, procedure_code, billed_amount,
                   service_date, policy_id, patient_id, COUNT(*)
            FROM claim_history
            WHERE submitted_by = ?
            GROUP BY provider_id, diagnosis_code, procedure_code, billed_amount,
                     service_date, policy_id, patient_id
        """, (current_user_email,)).fetchall()
        for _r in _dup_rows:
            dup_map[(_r[0], _r[1], _r[2], _r[3], _r[4], _r[5], _r[6])] = _r[7]

        _v_rows = _conn.execute(
            "SELECT claim_id, COUNT(*) FROM claim_history WHERE submitted_by = ? GROUP BY claim_id",
            (current_user_email,)
        ).fetchall()
        for _r in _v_rows:
            version_count_map[_r[0]] = _r[1]
        _conn.close()
    except Exception:
        pass

    # ── Zone 2 Query (spec §5) — user-scoped, NULL-safe date filter ───────────
    # submitted_by = ? is ALWAYS first — it is never optional
    try:
        conn = _get_db_conn()
        conn.row_factory = sqlite3.Row

        query_parts = ["SELECT * FROM claim_history WHERE submitted_by = ?"]
        params      = [current_user_email]

        if st.session_state["audit_search_cid"]:
            query_parts.append("AND claim_id LIKE ?")
            params.append(f"%{st.session_state['audit_search_cid']}%")

        if st.session_state["audit_search_pid"]:
            query_parts.append("AND patient_id LIKE ?")
            params.append(f"%{st.session_state['audit_search_pid']}%")

        if st.session_state["audit_search_prov"]:
            query_parts.append("AND provider_id LIKE ?")
            params.append(f"%{st.session_state['audit_search_prov']}%")

        if st.session_state["audit_search_pol"]:
            query_parts.append("AND policy_id LIKE ?")
            params.append(f"%{st.session_state['audit_search_pol']}%")

        status_val = st.session_state["audit_search_status"]
        if status_val != "All":
            query_parts.append("AND predicted_status = ?")
            params.append(status_val)

        # NULL-safe date filter (spec §7.2 + N-2 complement):
        # Claims with a NULL service_date (e.g. rule-denied) are always included
        query_parts.append(
            "AND (service_date IS NULL OR (service_date >= ? AND service_date <= ?))"
        )
        params.append(start_dt.isoformat())
        params.append(end_dt.isoformat())

        query_parts.append("ORDER BY submitted_at DESC")

        rows = conn.execute(" ".join(query_parts), params).fetchall()

    except Exception as e:
        st.error(f"Failed to query audit database: {e}")
        rows = []
    finally:
        if 'conn' in locals():
            conn.close()

    # ── Empty state with user-scoped debug expander (spec §5) ─────────────────
    if not rows:
        st.info("No matching claims found. Try widening the date range or clearing the filters.")

        with st.expander("🔍 Debug: show your claims in claim_history (up to 30)"):
            try:
                _dc = _get_db_conn()
                _dc.row_factory = sqlite3.Row
                debug_rows = _dc.execute(
                    "SELECT claim_id, patient_id, predicted_status, service_date, submitted_at "
                    "FROM claim_history WHERE submitted_by = ? ORDER BY submitted_at DESC LIMIT 30",
                    (current_user_email,)
                ).fetchall()
                _dc.close()
                if debug_rows:
                    st.dataframe(
                        pd.DataFrame([dict(r) for r in debug_rows]),
                        use_container_width=True, hide_index=True
                    )
                    st.caption(
                        "These are all your stored claims. If the claim you just submitted is "
                        "listed here but not in the main results above, check that your active "
                        "filters (Claim ID, date range) match the stored values exactly."
                    )
                else:
                    st.warning(
                        "No claims found for your account. If you just submitted a claim and "
                        "expected it to appear, watch for the ⚠️ warning shown after analysis — "
                        "it means the audit trail write failed."
                    )
            except Exception as _de:
                st.error(f"Debug query failed: {_de}")

    else:
        # ── Build results table (spec §8.1) ──────────────────────────────────
        table_data = []
        for r in rows:
            _dup_key = (r["provider_id"], r["diagnosis_code"], r["procedure_code"],
                        r["billed_amount"], r["service_date"], r["policy_id"], r["patient_id"])
            is_dup = "Yes" if dup_map.get(_dup_key, 1) > 1 else "No"
            table_data.append({
                "Claim ID":          r["claim_id"],
                "Submitted Date":    r["submitted_at"][:16].replace("T", " "),
                "Status":            r["predicted_status"],
                "Risk Level":        r["risk_level"] or "LOW",
                "Denial Probability": f"{float(r['denial_prob'] or 0)*100:.1f}%",
                "Duplicate Flag":    is_dup,
                "Last Updated":      r["submitted_at"][:10],
            })
        df = pd.DataFrame(table_data)

        # ── Split pane: Zone 2 (left) + Zone 3 (right) ────────────────────────
        left_col, right_col = st.columns([1.3, 1.7])

        with left_col:
            st.markdown("#### Search Results")

            # Row colouring per spec §8.2
            def _c_status(val):
                m = {"APPROVED": "#3fb950", "DENIED": "#f85149",
                     "RULE_DENY": "#f85149", "MANUAL_REVIEW": "#d29922"}
                c = m.get(val)
                return f"color:{c}; font-weight:bold;" if c else ""

            def _c_risk(val):
                m = {"LOW": "#3fb950", "MEDIUM": "#388bfd",
                     "HIGH": "#d29922", "CRITICAL": "#f85149"}
                c = m.get(val)
                return f"color:{c}; font-weight:bold;" if c else ""

            def _c_dup(val):
                return "color:#f85149; font-weight:bold;" if val == "Yes" \
                    else "color:#3fb950; font-weight:bold;" if val == "No" else ""

            styled_df = (
                df.style
                  .map(_c_status, subset=["Status"])
                  .map(_c_risk,   subset=["Risk Level"])
                  .map(_c_dup,    subset=["Duplicate Flag"])
            )
            st.dataframe(styled_df, use_container_width=True, hide_index=True)

            # Claim selector (spec §8.3)
            claim_ids_list = list(dict.fromkeys(r["claim_id"] for r in rows))
            if st.session_state["audit_selected_claim"] not in claim_ids_list:
                st.session_state["audit_selected_claim"] = claim_ids_list[0]

            selected_cid = st.selectbox(
                "Select Claim ID to Audit & Deep Dive:",
                claim_ids_list,
                index=claim_ids_list.index(st.session_state["audit_selected_claim"])
                      if st.session_state["audit_selected_claim"] in claim_ids_list else 0
            )
            st.session_state["audit_selected_claim"] = selected_cid

        # ── Zone 3 — Audit Detail Panel (spec §9) ─────────────────────────────
        with right_col:
            # Fetch all versions for this claim, user-scoped (spec §3.3)
            try:
                _vc = _get_db_conn()
                _vc.row_factory = sqlite3.Row
                versions = _vc.execute(
                    "SELECT * FROM claim_history "
                    "WHERE claim_id = ? AND submitted_by = ? ORDER BY submitted_at DESC",
                    (selected_cid, current_user_email)
                ).fetchall()
                _vc.close()
            except Exception as _ve:
                st.error(f"Error fetching version history: {_ve}")
                versions = []

            if not versions:
                st.warning("Could not load details for the selected claim.")
            else:
                active_row = versions[0]

                # ── Header banner (spec §9.1) ─────────────────────────────────
                status = active_row["predicted_status"]
                clr = ("#3fb950" if status == "APPROVED"
                       else "#d29922" if status == "MANUAL_REVIEW"
                       else "#f85149")

                # Inline badge logic
                _dup_key = (active_row["provider_id"], active_row["diagnosis_code"],
                            active_row["procedure_code"], active_row["billed_amount"],
                            active_row["service_date"], active_row["policy_id"],
                            active_row["patient_id"])
                _badges = ""
                if dup_map.get(_dup_key, 1) > 1:
                    _badges += ('<span style="background:rgba(248,81,73,.15);color:#f85149;'
                                'border:1px solid #f85149;padding:2px 8px;border-radius:12px;'
                                'font-weight:600;font-size:.75rem;margin-right:5px">Duplicate</span>')
                if len(versions) > 1:
                    _badges += ('<span style="background:rgba(56,139,253,.15);color:#388bfd;'
                                'border:1px solid #388bfd;padding:2px 8px;border-radius:12px;'
                                'font-weight:600;font-size:.75rem;margin-right:5px">Revised</span>')
                if active_row["risk_level"] in ("HIGH", "CRITICAL"):
                    _badges += ('<span style="background:rgba(247,129,102,.15);color:#f78166;'
                                'border:1px solid #f78166;padding:2px 8px;border-radius:12px;'
                                'font-weight:600;font-size:.75rem;margin-right:5px">High Risk</span>')
                if status == "MANUAL_REVIEW":
                    _badges += ('<span style="background:rgba(210,153,34,.15);color:#d29922;'
                                'border:1px solid #d29922;padding:2px 8px;border-radius:12px;'
                                'font-weight:600;font-size:.75rem;margin-right:5px">Needs Review</span>')

                st.markdown(f"""
                <div style="background:#161b22;border:1px solid {clr};border-radius:10px;
                            padding:15px;margin-bottom:15px">
                    <div style="display:flex;justify-content:space-between;
                                align-items:center;margin-bottom:8px">
                        <span style="background:{clr};color:#fff;padding:2px 8px;
                                     border-radius:4px;font-weight:600;font-size:.75rem">
                            {status}
                        </span>
                        <div>{_badges}</div>
                    </div>
                    <h3 style="margin:8px 0 2px 0;color:#e6edf3">Claim {selected_cid}</h3>
                    <p style="margin:0;font-size:.88rem;color:#8b949e">
                        Risk Score: <b>{float(active_row['denial_prob'] or 0)*100:.1f}%</b>
                        ({active_row['risk_level'] or 'LOW'})
                        &nbsp;|&nbsp; Billed: <b>₹{float(active_row['billed_amount'] or 0):,.2f}</b>
                    </p>
                </div>
                """, unsafe_allow_html=True)

                # Log view once per session per claim to avoid flooding the audit trail
                if st.session_state.get("last_logged_view") != selected_cid:
                    _log_audit_trail(selected_cid, "Viewed claim", "User viewed claim details.")
                    st.session_state["last_logged_view"] = selected_cid

                # ── 4 tabs per spec §9.2 (+ bonus tabs retained from previous work) ──
                tab_summary, tab_rules, tab_ml, tab_versions = st.tabs([
                    "Summary", "Rules Engine",
                    "ML Explanations", "Version & Compare"
                ])

                # Tab 1 — Summary (spec §9.2)
                with tab_summary:
                    st.markdown("#### Clinical & Billing Info")
                    _sc1, _sc2 = st.columns(2)
                    with _sc1:
                        st.markdown(f"**Patient ID:** `{active_row['patient_id'] or '—'}`")
                        st.markdown(f"**Provider ID:** `{active_row['provider_id'] or '—'}`")
                        st.markdown(f"**Policy ID:** `{active_row['policy_id'] or '—'}`")
                    with _sc2:
                        st.markdown(f"**Diagnosis ICD:** `{active_row['diagnosis_code'] or '—'}`")
                        st.markdown(f"**Procedure CPT:** `{active_row['procedure_code'] or '—'}`")
                        st.markdown(f"**Service Date:** `{active_row['service_date'] or '—'}`")
                    st.markdown("---")
                    st.info(f"**Next Action:** {active_row['recommendation'] or 'Evaluate claim details.'}")

                # Tab 2 — Rules Engine (spec §9.2)
                with tab_rules:
                    st.markdown("#### Administrative Rules Audit")
                    _violations = []
                    if active_row["error_codes"]:
                        try:
                            import json as _j
                            _violations = _j.loads(active_row["error_codes"])
                        except Exception:
                            pass
                    if _violations:
                        st.markdown(f"**{len(_violations)} rule violations detected:**")
                        for _v in _violations:
                            st.error(f"**{_v.get('field','Rule').replace('_',' ').title()}**: "
                                     f"{_v.get('message','')}")
                    else:
                        st.success("All administrative rules passed. No violations.")

                # Tab 3 — ML Explanations (spec §9.2)
                with tab_ml:
                    st.markdown("#### Explainable AI Drivers")
                    if not active_row["ml_called"]:
                        st.info("This claim was blocked by the Rules Engine. No ML inference ran.")
                    else:
                        st.markdown(f"**Denial Probability:** "
                                    f"`{float(active_row['denial_prob'] or 0)*100:.2f}%`")
                        try:
                            import json as _j
                            _fr = _j.loads(active_row["full_response"])
                            _shap = _fr.get("shap_scores", {})
                        except Exception:
                            _shap = {}
                        if _shap:
                            st.markdown("**SHAP Denial Impact Factors:**")
                            _sl = []
                            for _k, _sv in _shap.items():
                                _sl.append({"Driver": SHAP_LABEL.get(
                                    _k, _k.replace("_", " ").title()),
                                    "Impact Score": float(_sv)})
                            _df_shap = (pd.DataFrame(_sl)
                                          .sort_values("Impact Score", ascending=False))
                            st.bar_chart(_df_shap.set_index("Driver")["Impact Score"])
                        else:
                            st.caption("SHAP feature impact details not available.")

                # Tab 4 — Version & Compare (spec §9.2)
                with tab_versions:
                    st.markdown("#### Claim Submission Version History")
                    st.markdown(f"Found **{len(versions)} submission(s)** for `{selected_cid}`.")

                    for _idx, _v in enumerate(versions):
                        _vnum = len(versions) - _idx
                        _sv = _v["predicted_status"]
                        _sc = ("#3fb950" if _sv == "APPROVED"
                               else "#f85149" if _sv in ("DENIED", "RULE_DENY")
                               else "#d29922")
                        st.markdown(
                            f"**Version {_vnum}** "
                            f"({_v['submitted_at'][:16].replace('T', ' ')})  "
                            f"<span style='color:{_sc};font-weight:bold'>{_sv}</span>  "
                            f"| Billed: `₹{float(_v['billed_amount'] or 0):,.0f}` "
                            f"| Proc: `{_v['procedure_code'] or '—'}`",
                            unsafe_allow_html=True
                        )

                    if len(versions) > 1:
                        st.markdown("---")
                        st.markdown("#### Compare Versions Tool")
                        _cv1, _cv2 = st.columns(2)
                        with _cv1:
                            _v1_sel = st.selectbox("Version A",
                                                   range(1, len(versions) + 1),
                                                   index=0, key="cmp_v1")
                        with _cv2:
                            _v2_sel = st.selectbox("Version B",
                                                   range(1, len(versions) + 1),
                                                   index=min(1, len(versions) - 1),
                                                   key="cmp_v2")
                        _ra = versions[len(versions) - _v1_sel]
                        _rb = versions[len(versions) - _v2_sel]
                        _cmp_rows = []
                        for _f in ["billed_amount", "procedure_code", "diagnosis_code",
                                   "provider_id", "service_date", "policy_id", "patient_id"]:
                            _va, _vb = _ra[_f], _rb[_f]
                            _cmp_rows.append({
                                "Field": _f.replace("_", " ").title(),
                                f"V{_v1_sel}": _va, f"V{_v2_sel}": _vb,
                                "Changed?": "✅ Changed" if str(_va) != str(_vb) else "Identical"
                            })
                        _cdf = pd.DataFrame(_cmp_rows)

                        def _hl_changed(row):
                            _c = ("background-color:rgba(248,81,73,.15);"
                                  "color:#ff6b6b;font-weight:bold;"
                                  if "Changed" in str(row["Changed?"]) else "")
                            return [_c] * len(row)

                        st.dataframe(
                            _cdf.style.apply(_hl_changed, axis=1),
                            use_container_width=True, hide_index=True
                        )

                # ── Export controls (spec §9.3) ───────────────────────────────
                st.markdown("---")
                _ec1, _ec2 = st.columns(2)
                with _ec1:
                    import json as _j
                    st.download_button(
                        "Export Active Version (JSON)",
                        data=_j.dumps(dict(active_row), indent=2, default=str),
                        file_name=f"claim_audit_{selected_cid}.json",
                        mime="application/json",
                        use_container_width=True
                    )
                with _ec2:
                    st.download_button(
                        "Export Audit History (CSV)",
                        data=pd.DataFrame([dict(r) for r in versions]).to_csv(index=False),
                        file_name=f"claim_history_{selected_cid}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )


# ── Page: Claim Fix Wizard ─────────────────────────────────────────────────────
elif page == "Claim Fix Wizard":
    st.markdown("# Claim Fix Wizard")
    st.markdown("Step-by-step correction guide based on your last prediction.")

    result   = st.session_state.get("last_result")
    claim_id = st.session_state.get("last_claim_id", "—")

    if not result:
        st.info("Go to **Submit & Predict** first to analyse a claim, then return here.")
    else:
        outcome  = result.get("outcome", "ML_DENY")
        prob     = result.get("denial_prob", 1.0)
        risk     = result.get("risk_level", "CRITICAL")
        reasons  = result.get("reasons", [])
        exp_c    = result.get("expected_cost", 0)
        billed_amt = result.get("billed_amount", 0)
        billing_verdict = result.get("billing_verdict", "ACCEPT")
        b_ratio  = result.get("billing_ratio", 0)
        proc_code  = result.get("_proc_code", "")
        diag_code  = result.get("_diag_code", "")
        provider_id= result.get("_provider_id", "")

        st.markdown(f"""<div class="risk-{risk}" style="margin-bottom:16px">
            <h3 style="color:{risk_color(risk)};margin:0">Claim {claim_id} — {outcome.replace('_',' ')} ({prob*100:.1f}% denial risk)</h3>
        </div>""", unsafe_allow_html=True)

        if outcome == "RULE_DENY":
            violations = result.get("violations", [])
            _render_fix_wizard_rule_deny(violations, proc_code, exp_c, billed_amt)
        else:
            _render_fix_wizard_ml(outcome, reasons, result, billed_amt, exp_c,
                                  billing_verdict, proc_code, diag_code, provider_id, b_ratio)

        if st.button("Analyse Another Claim"):
            st.session_state.pop("last_result", None)
# ── Page: Analytics ───────────────────────────────────────────────────────────
elif page == "Analytics":
    st.markdown("# Analytics")
    st.markdown("Denial trend charts from locally processed claims.")

    try:
        conn = _get_db_conn()
        conn.commit()
        # Denial rate by diagnosis code
        df_diag = pd.read_sql_query("""
            SELECT diagnosis_code, COUNT(*) as total,
                   SUM(CASE WHEN predicted_status='DENIED' THEN 1 ELSE 0 END) as denied
            FROM claim_history
            WHERE diagnosis_code IS NOT NULL AND diagnosis_code != ''
            GROUP BY diagnosis_code
            ORDER BY total DESC LIMIT 15
        """, conn._conn)
        
        if not df_diag.empty:
            df_diag["Denial Rate %"] = (df_diag["denied"]/df_diag["total"]*100).round(1)
            st.subheader("Denial Rate by Diagnosis Code")
            st.bar_chart(df_diag.set_index("diagnosis_code")["Denial Rate %"])
            st.dataframe(df_diag, use_container_width=True)
        else:
            st.info("No claims processed yet.")

        # Billing ratio distribution
        df_ratio = pd.read_sql_query("""
            SELECT ROUND(CAST(billing_ratio AS NUMERIC), 1) as ratio_bucket, COUNT(*) as cnt
            FROM claim_history
            WHERE billing_ratio BETWEEN 0 AND 5
            GROUP BY ratio_bucket ORDER BY ratio_bucket
        """, conn._conn)
        
        if not df_ratio.empty:
            st.subheader("Billing Ratio Distribution")
            st.bar_chart(df_ratio.set_index("ratio_bucket")["cnt"])
            
    except Exception as e:
        st.error(f"Analytics query failed: {e}")
    finally:
        if 'conn' in locals():
            conn.close()


# ── Page: Policy Explorer ──────────────────────────────────────────────────────
elif page == "Policy Explorer":
    st.markdown("# Policy Explorer")
    st.markdown("Search the 3 policy documents used by the RAG system.")

    policy_dir = os.getenv("POLICY_DOCS_DIR", "data/policy_docs")
    docs = {}
    if os.path.isdir(policy_dir):
        for f in sorted(os.listdir(policy_dir)):
            if f.endswith(".txt"):
                with open(os.path.join(policy_dir, f), encoding="utf-8") as fh:
                    docs[f] = fh.read()

    if not docs:
        st.error(f"No policy docs found in {policy_dir}")
    else:
        query = st.text_input("Search policy text", placeholder="Search", key="policy_search")
        selected = st.selectbox("Select document", list(docs.keys()))

        text = docs[selected]
        if query:
            lines = text.splitlines()
            matched = [l for l in lines if query.lower() in l.lower()]
            st.markdown(f"**{len(matched)} matches** for `{query}` in `{selected}`:")
            for line in matched[:30]:
                highlighted = line.replace(query, f"**{query}**")
                st.markdown(f"- {highlighted}")
        else:
            with st.expander(f"{selected} ({len(text)} chars)", expanded=True):
                st.text(text[:3000] + ("..." if len(text) > 3000 else ""))