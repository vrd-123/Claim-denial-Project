# Claim Search & Audit Trail — Functional Design Document

**System:** Claim Denial Prevention (CDP)  
**Page:** Claim Search & Audit Trail  
**Stack:** Streamlit · SQLite (`claim_history.db`) · Supabase Auth  
**Audience:** Billing analysts, compliance reviewers, engineering team

---

## 1. Purpose

The Claim Search & Audit Trail page is the post-submission inspection hub for every claim that passes through the CDP system. It serves three distinct jobs:

- **Search** — let an analyst quickly locate any of their own claims using one or more filters.
- **Audit** — give a full, version-by-version record of what was submitted, what decision was produced, and why.
- **Compare** — surface exactly what changed between two submissions of the same claim ID so corrected resubmissions can be reviewed at a glance.

Two non-negotiable guarantees underpin the whole page:

1. **Immediate reflection** — a claim analysed on the Submit & Predict page must appear in this page's results the moment the analyst navigates here, with no cache to clear or page to reload.
2. **User-scoped isolation** — an analyst can only see claims they submitted. Claims submitted by another user are completely invisible, even if the same claim ID is searched.

---

## 2. How Claims Are Stored for Immediate Reflection

### 2.1 The problem with deferred or async writes

The most common reason a claim doesn't appear immediately after analysis is that the write is either skipped (exception silently swallowed), async (happens after the Streamlit rerun), or stored in a format the query can't match (e.g. `claim_id` stored as `c0001` but searched as `C0001`). All three must be eliminated.

### 2.2 Write-then-rerun contract

The save call must happen **synchronously, inside the same Streamlit script execution** that ran the analysis, before any `st.rerun()` or navigation away from the Submit page. The pattern looks like this:

```python
# 1. Run analysis (rule engine + ML)
result = call_predict(payload)

# 2. Compute final outcome
outcome, base_decision = _compute_granular_outcome(...)

# 3. Save to DB — SYNCHRONOUS, no threading, no background task
try:
    _save_claim_history(
        claim_id_norm, outcome, prob, risk,
        result_dict, billed_amt, exp_c,
        proc_code, diag_code, provider_id,
        svc_date_str, policy_id, patient_id,
        user_email   # ← user identity, explained in Section 3
    )
except Exception as e:
    st.warning(f"⚠️ Audit trail write failed for {claim_id_norm}: {e}")

# 4. Render result to screen
_render_decision_banner(outcome, prob, risk)
```

Because Streamlit reruns the entire script top-to-bottom on every interaction, as long as the write completes before the function returns, the Audit Trail page will see the row the next time the user navigates to it — no delay, no cache, no polling.

### 2.3 Normalization rules that prevent "saved but not found" bugs

Three normalization rules must be applied at write time in `_save_claim_history()`. If any of these are inconsistent between save and search, the claim appears saved in the DB but never surfaces in results.

**Rule N-1 — Claim ID casing**  
Always call `.strip().upper()` on `claim_id` before the INSERT. The search bar must apply the same normalization before building the LIKE query. A claim saved as `c0001` and searched as `C0001` will never match without this.

```python
claim_id_norm = str(claim_id or "").strip().upper()
```

**Rule N-2 — Service date as plain YYYY-MM-DD**  
`service_date` must be stored as a plain date string with no time component. If a `datetime` object or an ISO string with a time suffix arrives, strip it:

```python
if isinstance(svc_date, datetime.datetime):
    svc_date_str = svc_date.date().isoformat()
elif isinstance(svc_date, datetime.date):
    svc_date_str = svc_date.isoformat()
else:
    svc_date_str = str(svc_date).strip().split("T")[0].split(" ")[0]
```

Without this, a `service_date` stored as `"2024-03-15 00:00:00"` will never match a BETWEEN filter using `"2024-03-15"`.

**Rule N-3 — User email as the isolation key**  
`submitted_by` must be set to the authenticated user's email at write time (pulled from `st.session_state["user"]["email"]`), not a hardcoded default. This is the field that enforces user-scoped isolation at query time (see Section 3).

### 2.4 Save failure must be visible

Silent exception swallowing (`except: pass` or `except: logging.error(...)` only) is not acceptable. If the INSERT fails, the analyst sees a green analysis result on screen but will find nothing in the audit trail. The fix is to surface a `st.warning()` in the UI:

```python
except Exception as e:
    import logging
    logging.error(f"Failed to save claim history: {e}")
    st.warning(
        f"⚠️ Audit trail write failed for claim `{claim_id}`. "
        f"This result will NOT appear in the Audit Trail. Error: `{e}`"
    )
```

### 2.5 DB schema column the save relies on

The `claim_history` table must have a `submitted_by` column (TEXT) present. If it is missing, every INSERT will fail and no claims will be saved. Verify the schema with:

```sql
PRAGMA table_info(claim_history);
```

If `submitted_by` is absent, add it:

```sql
ALTER TABLE claim_history ADD COLUMN submitted_by TEXT;
```

---

## 3. User-Scoped History with Supabase Auth

### 3.1 How Supabase auth integrates with Streamlit

Supabase handles authentication (login, session tokens, user identity) entirely on its own side. Streamlit has no native auth — it just holds whatever your `auth.py` module puts into `st.session_state` after a successful Supabase sign-in.

The pattern your `auth.py` should implement is:

```python
# auth.py (simplified)
from supabase import create_client
import streamlit as st

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

def render_auth_page():
    email    = st.text_input("Email")
    password = st.text_input("Password", type="password")
    if st.button("Sign In"):
        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if response.user:
            st.session_state["user"] = {
                "id":    response.user.id,       # UUID, unique per user
                "email": response.user.email,    # human-readable, used as display + DB key
            }
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Invalid credentials.")

def is_authenticated():
    return st.session_state.get("authenticated", False)

def render_user_sidebar():
    user = st.session_state.get("user", {})
    st.markdown(f"Signed in as **{user.get('email', '—')}**")
    if st.button("Sign Out"):
        supabase.auth.sign_out()
        for key in ["user", "authenticated"]:
            st.session_state.pop(key, None)
        st.rerun()
```

After sign-in, `st.session_state["user"]["email"]` is the stable identity token used everywhere in the app.

### 3.2 Writing the user identity into claim_history

In `_save_claim_history()`, `submitted_by` is pulled from session state:

```python
submitted_by = st.session_state.get("user", {}).get("email", "unknown")
```

This runs server-side inside Streamlit's process, so `st.session_state` is always the session of the currently active user — there is no risk of cross-contamination between users here.

The INSERT stores this alongside every claim row:

```sql
INSERT INTO claim_history
  (claim_id, submitted_by, submitted_at, predicted_status, ...)
VALUES
  (?, ?, ?, ?, ...)
```

### 3.3 Enforcing isolation at query time in the Audit Trail

Every SELECT on `claim_history` in the Audit Trail page must include a `WHERE submitted_by = ?` clause bound to the currently signed-in user's email. This is the single enforcement point — it means a logged-out user sees nothing, and a logged-in user sees only their own rows.

```python
# At the top of the Audit Trail query block
current_user_email = st.session_state.get("user", {}).get("email")

if not current_user_email:
    st.error("You must be signed in to view the audit trail.")
    st.stop()

# Build the query
query_parts = ["SELECT * FROM claim_history WHERE submitted_by = ?"]
params      = [current_user_email]

# Layer in the other filters only after the user scope is locked
if st.session_state["audit_search_cid"]:
    query_parts.append("AND claim_id LIKE ?")
    params.append(f"%{st.session_state['audit_search_cid']}%")

# ... remaining filters ...
query_parts.append("ORDER BY submitted_at DESC")
rows = conn.execute(" ".join(query_parts), params).fetchall()
```

Because `submitted_by = ?` is the **first** condition in the WHERE clause, the query optimizer will use it to scope the scan before evaluating any other filter. No user can retrieve another user's claims regardless of what they type into the search filters.

### 3.4 What happens if the user is not authenticated

The global auth gate (`if not is_authenticated(): render_auth_page(); st.stop()`) prevents unauthenticated access to every page including the Audit Trail. But as a second layer of defence, the Audit Trail query block also checks for a valid email and stops with an error if it is missing. This covers edge cases where `st.session_state` was cleared mid-session (e.g. server restart) without a full re-authentication.

### 3.5 The debug expander is also user-scoped

The "Debug: show all rows" expander (shown when zero results are returned) must also filter by `submitted_by`. It should never show another user's claims even in a debug context:

```python
debug_rows = conn.execute(
    "SELECT claim_id, patient_id, predicted_status, service_date, submitted_at "
    "FROM claim_history WHERE submitted_by = ? ORDER BY submitted_at DESC LIMIT 30",
    (current_user_email,)
).fetchall()
```

---

## 4. Full _save_claim_history() Reference Implementation

This is the complete, correct version of the save function incorporating all normalization rules and user isolation:

```python
import sqlite3
import datetime
import json as _json
import streamlit as st

def _save_claim_history(claim_id, outcome, prob, risk, result_dict,
                        billed_amt, exp_c, proc, diag, prov,
                        svc_date=None, pol_id=None, pat_id=None):
    try:
        conn = sqlite3.connect("data/claim_history.db")
        cur  = conn.cursor()

        # N-1: Normalize claim_id
        claim_id_norm = str(claim_id or "").strip().upper()

        # User identity — must come from authenticated session
        submitted_by = st.session_state.get("user", {}).get("email", "unknown")
        submitted_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        predicted_status = result_dict.get("predicted_status", "APPROVED")
        error_codes      = _json.dumps(result_dict.get("violations", [])) if outcome == "RULE_DENY" else None
        reasons          = result_dict.get("reasons", [])
        primary_reason   = reasons[0]["explanation"] if reasons else None
        recommendation   = "Fix rule violations before ML inference." if outcome == "RULE_DENY" \
                           else result_dict.get("recommendation", "")
        full_response    = _json.dumps(result_dict)
        billing_ratio    = (billed_amt / exp_c) if (exp_c and exp_c > 0 and billed_amt) else 0.0
        ml_called        = 0 if outcome == "RULE_DENY" else 1

        # N-2: Normalize service_date to plain YYYY-MM-DD
        if svc_date is not None:
            if isinstance(svc_date, datetime.datetime):
                svc_date_str = svc_date.date().isoformat()
            elif isinstance(svc_date, datetime.date):
                svc_date_str = svc_date.isoformat()
            else:
                svc_date_str = str(svc_date).strip().split("T")[0].split(" ")[0]
        else:
            svc_date_str = None

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

        conn.commit()
        conn.close()

    except Exception as e:
        import logging
        logging.error(f"Failed to save claim history: {e}")
        # N-3: Surface the failure — never swallow silently
        st.warning(
            f"⚠️ Audit trail write failed for claim `{claim_id}`. "
            f"This result will NOT appear in the Audit Trail. Error: `{e}`"
        )
```

---

## 5. Full Audit Trail Query Block Reference

This is the complete, correct query block for the Audit Trail page. User scoping is applied first, all other filters are layered after:

```python
# ── Audit Trail query — user-scoped ──────────────────────────────────────────
current_user_email = st.session_state.get("user", {}).get("email")

if not current_user_email:
    st.error("You must be signed in to view the audit trail.")
    st.stop()

try:
    conn        = sqlite3.connect("data/claim_history.db")
    conn.row_factory = sqlite3.Row

    # submitted_by = ? is ALWAYS the first condition — it is never optional
    query_parts = ["SELECT * FROM claim_history WHERE submitted_by = ?"]
    params      = [current_user_email]

    if st.session_state["audit_search_cid"]:
        query_parts.append("AND claim_id LIKE ?")
        params.append(f"%{st.session_state['audit_search_cid'].strip().upper()}%")

    if st.session_state["audit_search_pid"]:
        query_parts.append("AND patient_id LIKE ?")
        params.append(f"%{st.session_state['audit_search_pid'].strip().upper()}%")

    if st.session_state["audit_search_prov"]:
        query_parts.append("AND provider_id LIKE ?")
        params.append(f"%{st.session_state['audit_search_prov'].strip().upper()}%")

    if st.session_state["audit_search_pol"]:
        query_parts.append("AND policy_id LIKE ?")
        params.append(f"%{st.session_state['audit_search_pol'].strip().upper()}%")

    status_val = st.session_state["audit_search_status"]
    if status_val != "All":
        query_parts.append("AND predicted_status = ?")
        params.append(status_val)

    # NULL-safe date filter (N-2 complement)
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

# ── Empty state with user-scoped debug ───────────────────────────────────────
if not rows:
    st.info("No matching claims found. Try widening the date range or clearing the filters.")

    with st.expander("🔍 Debug: show your claims in claim_history (up to 30)"):
        try:
            conn = sqlite3.connect("data/claim_history.db")
            conn.row_factory = sqlite3.Row
            debug_rows = conn.execute(
                "SELECT claim_id, patient_id, predicted_status, service_date, submitted_at "
                "FROM claim_history WHERE submitted_by = ? ORDER BY submitted_at DESC LIMIT 30",
                (current_user_email,)
            ).fetchall()
            conn.close()

            if debug_rows:
                st.dataframe(pd.DataFrame([dict(r) for r in debug_rows]),
                             use_container_width=True, hide_index=True)
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
        except Exception as debug_err:
            st.error(f"Debug query failed: {debug_err}")
```

---

## 6. Layout Overview

The page is split into three vertical zones stacked top to bottom:

```
┌──────────────────────────────────────────────────────────┐
│  ZONE 1 — Search & Filter Bar                            │
├─────────────────────────────┬────────────────────────────┤
│  ZONE 2 — Results Table     │  ZONE 3 — Audit Detail     │
│  (left, ~45% width)         │  Panel (right, ~55% width) │
└─────────────────────────────┴────────────────────────────┘
```

All three zones are visible simultaneously without scrolling on a standard 1440px wide screen. Selecting a claim in Zone 2 instantly populates Zone 3 without a page reload.

---

## 7. Zone 1 — Search & Filter Bar

### 7.1 Layout

Six filter inputs in a 3-column grid inside a bordered container card:

| Column 1 | Column 2 | Column 3 |
|---|---|---|
| Claim ID (text) | Patient ID (text) | Provider ID (text) |
| Policy ID (text) | Status Filter (dropdown) | Date Range (two date pickers) |

Two action buttons below the grid:

- **Search** (primary, filled green) — executes the query.
- **Reset** (secondary, outlined) — clears all filters to defaults and reruns.

### 7.2 Field Behaviour

**Claim ID** — text, partial LIKE match, auto-normalized to uppercase. Placeholder: `e.g. C0001`.

**Patient ID** — text, partial LIKE match, uppercase-normalized. Placeholder: `e.g. P101`.

**Provider ID** — text, partial LIKE match, uppercase-normalized. Placeholder: `e.g. PR101`.

**Policy ID** — text, partial LIKE match, uppercase-normalized. Placeholder: `e.g. POL002`.

**Status Filter** — single-select dropdown: `All` (default), `APPROVED`, `DENIED`, `MANUAL_REVIEW`. Filters on `predicted_status`.

**Date Range** — two date pickers applying to the `service_date` column.

Default values:
- Start Date: `2000-01-01` (all-time — do not default to today, recent claims with old service dates would disappear)
- End Date: `today + 1 day`

The filter uses `(service_date IS NULL OR (service_date >= ? AND service_date <= ?))` so NULL service dates never hide claims.

### 7.3 Signed-in user context

A read-only line above the filter grid shows which account's claims are being searched: *"Showing claims submitted by: your@email.com"*. This is derived from `st.session_state["user"]["email"]` and cannot be changed from this page.

---

## 8. Zone 2 — Results Table

### 8.1 Columns

| Column | Source | Notes |
|---|---|---|
| Claim ID | `claim_id` | Uppercase |
| Submitted Date | `submitted_at` | `YYYY-MM-DD HH:MM`, T separator removed |
| Status | `predicted_status` | Colour-coded |
| Risk Level | `risk_level` | Colour-coded |
| Denial Probability | `denial_prob` | Displayed as `XX.X%` |
| Duplicate Flag | computed | `Yes` / `No` — see Section 10 |
| Last Updated | `submitted_at` date only | |

### 8.2 Row Colouring

| Value | Text colour |
|---|---|
| Status: APPROVED | `#3fb950` green |
| Status: DENIED | `#f85149` red |
| Status: MANUAL_REVIEW | `#d29922` amber |
| Risk Level: LOW | `#3fb950` |
| Risk Level: MEDIUM | `#388bfd` blue |
| Risk Level: HIGH | `#d29922` |
| Risk Level: CRITICAL | `#f85149` |
| Duplicate Flag: Yes | `#f85149` |
| Duplicate Flag: No | `#3fb950` |

### 8.3 Claim Selector

A selectbox below the table labelled "Select Claim ID to Audit & Deep Dive" lists every Claim ID in the result set. Selecting a value populates Zone 3 instantly.

---

## 9. Zone 3 — Audit Detail Panel

### 9.1 Header Banner

Coloured card showing: Claim ID, status badge, risk score, billed amount. Border colour matches status (green / amber / red).

### 9.2 Tabs

#### Tab 1 — Summary
Two-column grid: Patient ID, Provider ID, Policy ID (left) | Diagnosis Code, Procedure Code, Service Date (right). Analyst recommendation shown as an info callout below.

#### Tab 2 — Rules Engine
If violations exist: count headline + red error block per violation. If clean: green success callout.

#### Tab 3 — ML Explanations
If ML was not called: info callout. If called: denial probability + SHAP horizontal bar chart (red = denial drivers, green = approval factors).

#### Tab 4 — Version & Compare
Chronological version timeline. When ≥ 2 versions exist, a Compare Tool shows two selectboxes and renders a side-by-side diff table with a "Changed" / "Identical" label per field.

### 9.3 Export Controls

- **Export Active Version (JSON)** → `claim_audit_{claim_id}.json`
- **Export Audit History (CSV)** → `claim_history_{claim_id}.csv`

---

## 10. Duplicate Flag Logic

Computed at query time per row. A secondary COUNT query checks whether any other row **belonging to the same user** shares the same values across all seven clinical/billing fields: `provider_id`, `diagnosis_code`, `procedure_code`, `billed_amount`, `service_date`, `policy_id`, `patient_id`. The user scope (`submitted_by = ?`) is included in the duplicate check so users can never see cross-user duplicate signals.

```sql
SELECT COUNT(*) FROM claim_history
WHERE submitted_by = ?
  AND (provider_id = ? OR (provider_id IS NULL AND ? IS NULL))
  AND (diagnosis_code = ? OR (diagnosis_code IS NULL AND ? IS NULL))
  AND (procedure_code = ? OR (procedure_code IS NULL AND ? IS NULL))
  AND (billed_amount = ? OR (billed_amount IS NULL AND ? IS NULL))
  AND (service_date = ? OR (service_date IS NULL AND ? IS NULL))
  AND (policy_id = ? OR (policy_id IS NULL AND ? IS NULL))
  AND (patient_id = ? OR (patient_id IS NULL AND ? IS NULL))
```

Count > 1 → "Yes" (red). Otherwise → "No" (green).

---

## 11. Data Integrity Checklist

Before deploying or debugging the Audit Trail, verify all of the following:

| # | Check | How to verify |
|---|---|---|
| 1 | `claim_history` table has a `submitted_by` column | `PRAGMA table_info(claim_history)` |
| 2 | `submitted_by` is populated with the user's email, not `"varad"` or another hardcoded default | Inspect a saved row: `SELECT claim_id, submitted_by FROM claim_history LIMIT 5` |
| 3 | `claim_id` is stored uppercase | Same row inspect |
| 4 | `service_date` is stored as `YYYY-MM-DD` with no time component | `SELECT service_date FROM claim_history LIMIT 5` |
| 5 | `_save_claim_history()` is called before any `st.rerun()` or page transition | Code review of submit path |
| 6 | Save failures show `st.warning()` in the UI | Temporarily break the DB path and confirm the warning appears |
| 7 | All SELECTs on `claim_history` include `WHERE submitted_by = ?` | Code review of every query in the Audit Trail page |
| 8 | The debug expander also scopes by `submitted_by` | Code review |
| 9 | Default date range starts at `2000-01-01`, not today | Run the page and check the date picker defaults |
| 10 | Date filter uses NULL-safe `(service_date IS NULL OR ...)` form | Code review of query builder |

---

## 12. Security Model Summary

| Concern | Mechanism |
|---|---|
| Unauthenticated access | Global `if not is_authenticated(): st.stop()` before any page renders |
| Cross-user data leakage | `WHERE submitted_by = current_user_email` on every SELECT |
| Session hijacking | Supabase manages tokens; Streamlit session_state is server-side per connection |
| Hardcoded user fallback | `submitted_by` defaults to `"unknown"` if email is absent, so misattributed claims are findable but are never attributed to another real user |
| Admin override | Not implemented by default. If a supervisor role is needed, add a `role` field to `st.session_state["user"]` from the Supabase user metadata and add a bypass condition: `if current_user_role != "admin": query_parts.append("AND submitted_by = ?")` |
