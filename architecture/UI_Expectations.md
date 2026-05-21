# UI Expectations — AI-Powered Claim Denial Prevention & Remediation System

> **Scope**: This document covers the working UI only — authentication and deployment are excluded.  
> **Audience**: Developers building the Streamlit frontend + FastAPI integration.  
> **Data context**: Claims (`claim_id`, `patient_id`, `provider_id`, `diagnosis_code`, `procedure_code`, `billed_amount`, `date`), Cost (`procedure_code`, `average_cost`, `expected_cost`, `region`), Diagnosis (`diagnosis_code`, `category`, `severity`), Providers (`provider_id`, `doctor_name`, `specialty`, `location`).

---

## 1. Overall UI Architecture

The UI is a **single-page Streamlit application** structured into three zones:

```
┌─────────────────────────────────────────────────────────────┐
│  HEADER BAR  — Logo | App Title | Session Info              │
├──────────────┬──────────────────────────────────────────────┤
│              │                                              │
│  LEFT PANEL  │         MAIN RESULTS PANEL                   │
│  (Claim      │  ┌──────────────────────────────────────┐   │
│   Input      │  │  Decision Banner                     │   │
│   Form)      │  ├──────────────────────────────────────┤   │
│              │  │  Probability Gauge  |  Risk Summary   │   │
│              │  ├──────────────────────────────────────┤   │
│              │  │  Tab 1: XAI Explanation               │   │
│              │  │  Tab 2: Policy Documents (RAG)        │   │
│              │  │  Tab 3: Claim Fix Wizard              │   │
│              │  └──────────────────────────────────────┘   │
└──────────────┴──────────────────────────────────────────────┘
```

### Layout Rules
- Use `st.columns([1, 2])` to split Input (left) and Results (right).
- Results panel only becomes visible **after** the user submits a claim.
- All four outcome types (Rule Deny, Conditional, ML Approve, ML Deny) render in the **same Results panel** — only the content changes.
- Use `st.tabs(["🔍 Explanation", "📄 Policy Docs", "🛠️ Fix Wizard"])` for the lower section.

---

## 2. Claim Input Form (Left Panel)

### 2.1 Input Fields

| Field | Widget | Notes |
|---|---|---|
| Claim ID | `st.text_input` | Auto-populated if looking up existing claim; editable |
| Patient ID | `st.text_input` | Free text |
| Provider ID | `st.selectbox` | Populated from `providers_1000.csv` (`provider_id` values) |
| Diagnosis Code | `st.selectbox` | Populated from `diagnosis.csv` (`diagnosis_code` values); shows code + category |
| Procedure Code | `st.selectbox` | Populated from `cost.csv` (`procedure_code`); shows code + region |
| Billed Amount (₹) | `st.number_input` | Min = 0, step = 100; **critical field** |
| Claim Date | `st.date_input` | Defaults to today |

### 2.2 Inline Field Warnings (Before Submission)

Show `st.warning()` inline beneath the field (do not wait for submission) for:
- **Billed Amount = 0**: "⚠️ Billed amount cannot be zero. This will result in an automatic rejection."
- **No Diagnosis Code selected**: "⚠️ Diagnosis code is required for all claims."
- **No Procedure Code selected**: "⚠️ Procedure code is required."
- **Provider ID not found in master list**: "⚠️ Provider ID not recognised. Verify before submitting."

These are **soft warnings** shown live using `st.session_state` + `on_change` callbacks — they do not block submission.

### 2.3 Submit Button

```python
st.button("🔍 Analyse Claim", type="primary", use_container_width=True)
```

On click: trigger the full pipeline (Rule Engine → optionally ML → XAI → RAG) and populate the Results panel.

### 2.4 Reset Button

```python
st.button("↺ Reset", use_container_width=True)
```

Clears all fields and hides the Results panel.

---

## 3. Pipeline Decision Logic (Backend → UI Mapping)

This is the **single source of truth** for what the UI displays based on each pipeline outcome.

### 3.1 Decision Flow

```
Claim Submitted
       │
       ▼
┌──────────────────────────────────┐
│       RULE ENGINE                │
│  Check: billed_amount, codes,    │
│  provider, diagnosis presence    │
└──────────────────────────────────┘
       │
   Rule fails?──────────────────────► OUTCOME A: RULE_DENY
       │                                (No ML call)
       ▼ (rule passes)
┌──────────────────────────────────┐
│     BILLED AMOUNT CHECK          │
│  Compare billed vs expected_cost │
│  from cost.csv                   │
└──────────────────────────────────┘
       │
       ├── billed = 0 ────────────────► OUTCOME A: AUTO_REJECT_MISSING
       ├── billed > 175% expected ─────► OUTCOME A: AUTO_REJECT_HIGH
       ├── billed 125–175% expected ───► ML runs ──► OUTCOME B: CONDITIONAL
       ├── billed within ±25% expected ► ML runs ──► OUTCOME C or D
       ├── billed 50–75% expected ─────► ML runs + FLAG_LOW warning
       └── billed < 50% expected ──────► ML runs + FLAG_VERY_LOW warning
```

### 3.2 Billed Amount Condition Table

| Condition | Internal Code | ML Called? | UI Verdict |
|---|---|---|---|
| Billed = 0 | `AUTO_REJECT_MISSING` | ❌ No | Hard Reject |
| Billed > 175% of expected | `AUTO_REJECT_HIGH` | ❌ No | Hard Reject |
| Billed 125–175% of expected | `CONDITIONAL` | ✅ Yes | Conditionally Approved |
| Billed within ±25% of expected | `ACCEPT` | ✅ Yes | Normal ML flow |
| Billed 50–75% of expected | `FLAG_LOW` | ✅ Yes | Normal ML + low-bill warning |
| Billed < 50% of expected | `FLAG_VERY_LOW` | ✅ Yes | Normal ML + strong low-bill warning |

### 3.3 Probability Score Rules

| Outcome | Denial Probability | Approval Probability | Display |
|---|---|---|---|
| Rule Deny / Auto Reject | **~1.00 (100%)** | ~0.00 | Red gauge, full |
| ML Deny | **> 0.70** | < 0.30 | Red gauge |
| Conditional Approval | **0.40–0.49** | 0.51–0.60 | Amber gauge |
| ML Approve | **< 0.30** | > 0.70 | Green gauge |

> **Implementation note**: For Rule Deny cases, override the ML score to 0.98–1.00 in the API response — do **not** run the model. For Conditional, the ML output is retained as-is but only shown if it falls in the 0.40–0.55 denial range; if it falls outside, cap or floor it to the boundary.

---

## 4. Decision Banner (Results Panel — Top)

The banner is the **first thing the user sees** after submission. It must be unmistakable.

### 4.1 Banner Variants

**OUTCOME A — Hard Reject (Rule Engine)**
```
┌─────────────────────────────────────────────────────┐
│  ❌  CLAIM REJECTED                                  │
│  Rejection Reason: [Rule trigger, e.g.              │
│  "Billed amount missing" / "Diagnosis code absent"] │
│  This claim was rejected before ML analysis.        │
│  Denial Probability: 100%                           │
└─────────────────────────────────────────────────────┘
```
Color: `#FF4444` background, white text. Use `st.error()` styled block.

**OUTCOME B — Conditional Approval**
```
┌─────────────────────────────────────────────────────┐
│  ⚠️  CONDITIONALLY APPROVED                         │
│  This claim has been provisionally approved         │
│  but requires manual review before processing.      │
│  Denial Risk: MEDIUM (~45%)                         │
└─────────────────────────────────────────────────────┘
```
Color: `#FF8C00` / amber. Use `st.warning()` styled block.

**OUTCOME C — ML Approved**
```
┌─────────────────────────────────────────────────────┐
│  ✅  CLAIM APPROVED                                  │
│  This claim passed all validation checks.            │
│  Approval Probability: [X]%                         │
└─────────────────────────────────────────────────────┘
```
Color: `#28A745` green. Use `st.success()` styled block.

**OUTCOME D — ML Denied**
```
┌─────────────────────────────────────────────────────┐
│  ❌  CLAIM DENIED                                    │
│  The model has identified high denial risk.          │
│  Denial Probability: [X]%   Risk Level: HIGH         │
└─────────────────────────────────────────────────────┘
```
Color: `#FF4444`. Use `st.error()` styled block.

---

## 5. Probability Gauge & Risk Summary (Results Panel — Middle)

### 5.1 Gauge Display

Use a Plotly gauge chart rendered via `st.plotly_chart()`:

```python
import plotly.graph_objects as go

fig = go.Figure(go.Indicator(
    mode="gauge+number",
    value=denial_probability * 100,
    title={"text": "Denial Risk (%)"},
    gauge={
        "axis": {"range": [0, 100]},
        "bar": {"color": bar_color},  # red / amber / green
        "steps": [
            {"range": [0, 30], "color": "#e8f5e9"},   # low risk
            {"range": [30, 60], "color": "#fff8e1"},   # medium risk
            {"range": [60, 100], "color": "#ffebee"},  # high risk
        ],
        "threshold": {
            "line": {"color": "black", "width": 3},
            "thickness": 0.75,
            "value": denial_probability * 100
        }
    }
))
```

### 5.2 Metric Cards (beside gauge)

Show three `st.metric()` cards in a `st.columns(3)` layout:

| Metric | Value |
|---|---|
| Denial Probability | e.g. `82%` (delta: `HIGH RISK` in red) |
| Approval Probability | e.g. `18%` |
| Risk Category | `HIGH` / `MEDIUM` / `LOW` (colored badge) |

---

## 6. Tab 1 — XAI Explanation

### 6.1 What to Show Per Outcome

#### OUTCOME A — Rule Deny
- **Do not run SHAP**. The rule engine is sufficient.
- Show a titled section: **"Why This Claim Was Rejected"**
- Display a simple bullet list of rule violations (from the rule engine response):
  - e.g. "❌ Billed amount is missing (value = 0)"
  - e.g. "❌ Diagnosis code is absent — required for all claims"
  - e.g. "❌ Procedure code not found in approved code list"
- Below, show a static info box: *"Rule-based rejections do not proceed to ML analysis. Please fix the listed issues and resubmit."*
- Show denial drivers only. Do not show approval factors.

#### OUTCOME B — Conditional Approval
- **Run SHAP**. Show **both** denial drivers and approval factors.
- Header: **"Why This Claim Is Flagged for Review"**
- Layout: two columns side by side.

**Left column — Denial Drivers (risks present)**
```
🔴 Denial Risk Factors
━━━━━━━━━━━━━━━━━━━━━
• Billed amount is 142% of expected cost   [SHAP: +0.31]
• Provider has elevated historical risk    [SHAP: +0.18]
• Diagnosis severity: High                 [SHAP: +0.12]
```

**Right column — Approval Factors (why it still passed)**
```
🟢 Approval Factors
━━━━━━━━━━━━━━━━━━━
• Valid procedure-diagnosis mapping        [SHAP: -0.22]
• Provider is in-network                   [SHAP: -0.15]
• Claim date within policy period          [SHAP: -0.09]
```

- Use a **horizontal SHAP bar chart** (Plotly or Matplotlib): red bars pointing right = denial drivers, green bars pointing left = approval factors.
- Show top 5 features per side maximum.

#### OUTCOME C — ML Approved
- **Only show XAI if the claim has any non-trivial risk flags** (denial probability > 15%). 
- If denial probability ≤ 15%: show a single green box — *"✅ This claim shows no significant risk factors. No further explanation required."* — and hide the XAI tab content.
- If denial probability 15–30%: show only Approval Factors. Do not show denial drivers for an approved claim with low risk.
- Header: **"Why This Claim Was Approved"**
- Show only the green approval factors column (same format as above).

#### OUTCOME D — ML Denied
- **Run SHAP fully**. Show primarily denial drivers.
- Header: **"Why This Claim Was Denied"**
- Show denial drivers prominently (left-weighted or full-width).
- Show approval factors in a collapsed `st.expander("View mitigating factors")` — do not prominently display them.
- Include a sentence at the bottom: *"Addressing the denial drivers above can improve the chance of approval on resubmission."*

### 6.2 SHAP → Human-Readable Mapping

Map SHAP feature names to display labels:

| SHAP Feature | Display Label |
|---|---|
| `billed_to_expected_ratio` | Billed amount vs. expected cost |
| `provider_risk_score` | Provider historical denial rate |
| `severity_score` | Diagnosis severity level |
| `claim_frequency` | Claim frequency for this provider |
| `high_cost_flag` | High-cost claim flag |
| `diagnosis_category_encoded` | Diagnosis category |
| `procedure_match_flag` | Procedure-diagnosis code match |
| `provider_specialty_encoded` | Provider specialty risk |
| `missing_fields_count` | Completeness of claim fields |
| `billed_amount` | Raw billed amount |

---

## 7. Tab 2 — Policy Documents (RAG)

### 7.1 How RAG Query Is Formed

The query sent to the RAG engine is constructed from the XAI output:

```python
rag_query = f"""
Claim outcome: {outcome}
Top denial drivers: {', '.join(top_denial_reasons)}
Diagnosis: {diagnosis_code} ({diagnosis_category}, severity: {severity})
Procedure: {procedure_code}
Billed: {billed_amount} vs expected: {expected_cost}
"""
```

### 7.2 What to Display Per Outcome

#### OUTCOME A — Rule Deny
- Show 1–2 policy documents directly relevant to the violated rules:
  - If billed = 0: retrieve policy on **mandatory billing fields**.
  - If diagnosis missing: retrieve policy on **diagnosis code requirements**.
- Display format: each policy doc in a `st.expander(policy_title)` with:
  - Policy title (bold)
  - Relevant excerpt (2–4 sentences)
  - Relevance tag: e.g. `🔴 Directly caused rejection`

#### OUTCOME B — Conditional Approval
- Show 2–3 policy documents — retrieve policies that explain:
  - Why the elevated billing triggers review (cost threshold policy)
  - What conditions allow conditional approval
  - What the reviewer needs to verify
- Each policy in an expander with relevance tag: `⚠️ Relevant to conditional review`

#### OUTCOME C — ML Approved
- If denial probability ≤ 15%: **do not show the Policy tab at all** or show: *"✅ No policy concerns identified for this claim."*
- If denial probability 15–30%: show 1 policy doc (informational, not alarming), tagged: `ℹ️ For reference`

#### OUTCOME D — ML Denied
- Show 2–4 policy documents supporting the denial:
  - Pull policies matching the top 2–3 denial drivers
  - Each policy tagged: `🔴 Policy violated` or `🔴 Policy not met`
- Order policies by relevance score (highest first).
- Include a note: *"These policies were retrieved based on the specific denial reasons identified for this claim."*

### 7.3 Policy Card Format

Each retrieved policy document should be rendered as:

```
┌─────────────────────────────────────────────────────┐
│  📄  [Policy Title]                    [Tag Badge]  │
│  ─────────────────────────────────────────────────  │
│  [2–4 sentence relevant excerpt from policy doc]    │
│                                                      │
│  Relevance Score: ██████░░░░  72%                   │
│  Source: synthetic_policy_docs / [filename]         │
└─────────────────────────────────────────────────────┘
```

Render using `st.expander()` with a custom header. Show a max of **4 policy cards** per query result — never dump all retrieved documents.

---

## 8. Tab 3 — Claim Fix Wizard

The Fix Wizard is an **actionable remediation guide** — it tells the billing analyst exactly what to change.

### 8.1 Fix Wizard Per Outcome

#### OUTCOME A — Rule Deny
- Title: **"🛠️ Required Fixes Before Resubmission"**
- Show a numbered fix list, one fix per violated rule:

```
1. ❌ ADD BILLED AMOUNT
   Field: billed_amount
   Issue: Billed amount is 0 or missing.
   Action: Enter the correct billed amount for procedure [PROC_CODE].
   Reference: Expected cost for [PROC_CODE] in [region] is ₹[expected_cost].

2. ❌ ADD DIAGNOSIS CODE
   Field: diagnosis_code
   Issue: No diagnosis code was provided.
   Action: Add the ICD-10 diagnosis code corresponding to the patient's
           condition. Verify with the treating physician.
```

- Each fix has: **Field name**, **Issue**, **Action** (specific, not generic), **Reference** (from data).
- Show a `st.progress()` bar: "Claim completeness: X / Y fields complete."

#### OUTCOME B — Conditional Approval
- Title: **"⚠️ Flags Requiring Review Before Final Processing"**
- Show the billing amount flag prominently first:

```
⚠️  BILLING AMOUNT FLAGGED
    Submitted: ₹[billed_amount]
    Expected:  ₹[expected_cost]
    Ratio:     [X]% of expected  (threshold: 125–175%)
    Action:    Attach a medical necessity justification letter
               and itemised bill breakdown before processing.
```

- Then show any secondary ML-driven flags in order of SHAP magnitude:

```
⚠️  ELEVATED PROVIDER RISK
    Provider: [provider_id] — [doctor_name] ([specialty])
    Action:  Flag for manual review by senior claims analyst.

⚠️  HIGH SEVERITY DIAGNOSIS
    Diagnosis: [diagnosis_code] — [category] (Severity: High)
    Action:  Verify that procedure [procedure_code] aligns with
             treatment protocol for this diagnosis.
```

- End with: *"This claim can proceed after the above conditions are satisfied."*

#### OUTCOME C — ML Approved
- Title: **"✅ No Fixes Required"**
- Show a simple green success message:

```
✅  This claim has passed all validation checks.
    No corrections are needed.
    You may proceed with submission.
```

- If `FLAG_LOW` or `FLAG_VERY_LOW` billed amount condition is present, add a **non-blocking note**:

```
ℹ️  NOTE: Billed amount (₹[X]) is [Y]% of the expected cost
    (₹[expected_cost]). This is unusual but within accepted limits.
    Verify this is not an under-billing error.
```

#### OUTCOME D — ML Denied
- Title: **"🛠️ Recommended Fixes to Improve Approval Chances"**
- Show one fix card per top SHAP denial driver (top 3–4 maximum), ordered by impact:

```
1. 🔴 HIGH BILLING AMOUNT  [Impact: HIGH]
   Submitted: ₹[billed_amount] — [X]% of expected cost
   Expected:  ₹[expected_cost]
   Action:  Review and reduce the billed amount or provide itemised
            justification. Amounts within ±25% of expected are
            less likely to be flagged.

2. 🔴 PROVIDER RISK  [Impact: MEDIUM]
   Provider: [provider_id] ([specialty])
   Issue:   This provider has a historically elevated denial rate.
   Action:  Route claim for senior review. Ensure all documentation
            is complete and attached.

3. 🔴 MISSING PROCEDURE-DIAGNOSIS MAPPING  [Impact: MEDIUM]
   Procedure: [procedure_code]
   Diagnosis: [diagnosis_code]
   Action:  Verify that this procedure is clinically justified by the
            stated diagnosis. Attach physician notes if required.
```

- Show at the bottom: *"Resubmit after addressing the above. Each fix reduces denial probability."*

---

## 9. Low Billed Amount Warning Banners

For `FLAG_LOW` and `FLAG_VERY_LOW` cases, show a persistent warning banner **above the results panel** (not replacing the decision banner):

**FLAG_LOW (50–75% of expected)**
```python
st.warning(
  f"⚠️ Low Billing Alert: Submitted amount ₹{billed} is only "
  f"{ratio:.0%} of the expected cost ₹{expected}. "
  f"Please verify this is not an under-billing error."
)
```

**FLAG_VERY_LOW (< 50% of expected)**
```python
st.error(
  f"🚨 Very Low Billing Alert: Submitted amount ₹{billed} is less than "
  f"50% of the expected cost ₹{expected}. This may indicate a billing "
  f"error or data entry mistake. Claim will still be evaluated."
)
```

These banners are shown **alongside** the normal ML outcome — they do not override it.

---

## 10. Rule Engine — Complete Logic Specification

The Rule Engine runs **before ML**. If any hard rule fails, ML is not called.

### 10.1 Hard Reject Rules (AUTO_REJECT)

| Rule ID | Check | Condition | Reject Message |
|---|---|---|---|
| R01 | Billed Amount | `billed_amount == 0 or null` | "Billed amount is missing or zero." |
| R02 | Billed Amount | `billed_amount > 1.75 × expected_cost` | "Billed amount exceeds 175% of expected cost." |
| R03 | Diagnosis Code | `diagnosis_code is null or empty` | "Diagnosis code is missing." |
| R04 | Procedure Code | `procedure_code is null or empty` | "Procedure code is missing." |
| R05 | Provider ID | `provider_id not in silver_provider.provider_id` | "Provider ID not found in approved provider list." |
| R06 | Diagnosis Code | `diagnosis_code not in silver_diagnosis.diagnosis_code` | "Diagnosis code is not in the approved ICD code list." |
| R07 | Procedure Code | `procedure_code not in cost.procedure_code` | "Procedure code is not in the approved CPT code list." |
| R08 | Patient ID | `patient_id is null or empty` | "Patient ID is missing." |
| R09 | Claim Date | `claim_date > today` | "Claim date is in the future." |
| R10 | Duplicate | `claim_id already exists in system` | "Duplicate claim detected." |

### 10.2 Soft Warning Rules (Not reject — shown as warnings)

| Rule ID | Check | Condition | Warning Message |
|---|---|---|---|
| W01 | Provider Location | `provider.location is null` | "Provider location is missing — may affect regional cost benchmarking." |
| W02 | Claim Date | `claim_date older than 90 days` | "Claim date is over 90 days old. Verify claim is within policy window." |
| W03 | Billed Amount | `FLAG_LOW or FLAG_VERY_LOW` | Low/Very Low billing alert (see Section 9). |

### 10.3 Rule Engine Response Structure

```json
{
  "rule_outcome": "REJECT",  // REJECT | PASS | WARN
  "violated_rules": [
    {
      "rule_id": "R03",
      "field": "diagnosis_code",
      "message": "Diagnosis code is missing.",
      "severity": "HARD_REJECT"
    }
  ],
  "warnings": [],
  "proceed_to_ml": false,
  "denial_probability_override": 1.00
}
```

---

## 11. Full API Response Structure (FastAPI → Streamlit)

The FastAPI endpoint `POST /predict-claim` should return a unified response that the UI consumes:

```json
{
  "claim_id": "C0001",
  "pipeline_stage": "RULE_ENGINE | ML",
  "outcome": "RULE_DENY | CONDITIONAL | ML_APPROVE | ML_DENY",
  "billing_flag": "AUTO_REJECT_MISSING | AUTO_REJECT_HIGH | CONDITIONAL | ACCEPT | FLAG_LOW | FLAG_VERY_LOW",
  "denial_probability": 0.95,
  "approval_probability": 0.05,
  "risk_level": "HIGH | MEDIUM | LOW",
  "rule_violations": [
    {
      "rule_id": "R03",
      "field": "diagnosis_code",
      "message": "Diagnosis code is missing.",
      "fix_action": "Add the ICD-10 code for the patient's diagnosis."
    }
  ],
  "xai": {
    "denial_drivers": [
      {"feature": "billed_to_expected_ratio", "label": "Billed amount vs. expected cost", "shap_value": 0.31, "direction": "DENY"},
      {"feature": "provider_risk_score", "label": "Provider historical denial rate", "shap_value": 0.18, "direction": "DENY"}
    ],
    "approval_factors": [
      {"feature": "procedure_match_flag", "label": "Procedure-diagnosis code match", "shap_value": -0.22, "direction": "APPROVE"}
    ]
  },
  "rag": {
    "retrieved_policies": [
      {
        "title": "Billing Amount Threshold Policy",
        "excerpt": "Claims submitted above 125% of the expected regional benchmark require itemised justification...",
        "relevance_score": 0.87,
        "tag": "Policy violated",
        "source": "policy_billing_thresholds.txt"
      }
    ]
  },
  "fix_wizard": {
    "fixes_required": true,
    "fixes": [
      {
        "priority": 1,
        "impact": "HIGH",
        "field": "billed_amount",
        "issue": "Billed amount is 142% of expected cost.",
        "action": "Review and reduce billed amount or attach itemised justification."
      }
    ]
  },
  "claim_details": {
    "provider_name": "Dr Patel",
    "specialty": "Neurology",
    "diagnosis_label": "Heart (High severity)",
    "procedure_code": "PROC2",
    "expected_cost": 15000,
    "billed_amount": 21300,
    "billed_ratio": 1.42
  }
}
```

---

## 12. Claim Summary Card (Results Panel — Always Visible)

Before the decision tabs, show a compact **Claim Summary Card** so the analyst can always see what they submitted:

```
┌──────────────────────────────────────────────────────────────┐
│  CLAIM SUMMARY                                    C0001      │
│  ─────────────────────────────────────────────────────────   │
│  Patient: P206        Provider: Dr Patel (Neurology)         │
│  Diagnosis: D10 — Heart (Severity: High)                     │
│  Procedure: PROC2     Region: Mumbai                         │
│  Billed: ₹21,300      Expected: ₹15,000    Ratio: 142%       │
│  Date: 2024-02-04                                            │
└──────────────────────────────────────────────────────────────┘
```

Use `st.info()` or a styled `st.container()` with `st.columns` for this card.

---

## 13. Production-Level UI Requirements

### 13.1 Session State Management

- Use `st.session_state` to persist the last result so it doesn't re-run on widget interaction.
- Store: `last_claim_id`, `last_result`, `form_submitted` (bool).
- Never re-trigger the API call on every Streamlit rerun — gate it on the submit button click.

### 13.2 Loading State

Show a spinner during API calls:
```python
with st.spinner("Analysing claim... This may take a few seconds."):
    result = call_api(payload)
```

For slower RAG queries, show a progress bar with stages:
```
[██░░░░░░] Rule Engine ✓  →  [████░░░░] ML Model ✓  →  [██████░░] XAI ✓  →  [████████] RAG complete
```

### 13.3 Error Handling

| Error | Display |
|---|---|
| API timeout / connection error | `st.error("Unable to reach the analysis service. Please try again.")` |
| Invalid input (pre-submit) | Inline field warnings (Section 2.2) |
| Partial pipeline failure (e.g. RAG fails) | Show ML + XAI results; show `st.warning("Policy retrieval unavailable. Showing ML results only.")` in Tab 2 |
| Unknown claim ID (lookup mode) | `st.warning("Claim ID not found. Please check and re-enter.")` |

### 13.4 Accessibility & Usability

- All colour-coded outcomes must also use **icons and text labels** (not colour alone) — required for colour-blind users.
- Decision banner font size: minimum 18px / `st.markdown` with heading level `##`.
- Gauge chart must include a textual summary beneath it (e.g. "Denial risk: 82% — HIGH").
- All `st.expander` elements should be closed by default to reduce cognitive load.

### 13.5 Audit Trail (Claim History Panel)

Add a **sidebar or bottom panel** showing the last 10 claims analysed in the session:

```
RECENT CLAIMS
─────────────────────────────────
C0001  ❌ DENIED       14:32
C0002  ✅ APPROVED     14:28
C0003  ⚠️ CONDITIONAL  14:15
```

Each row is clickable and loads that claim's result back into the Results panel without re-calling the API (use `st.session_state` cache).

### 13.6 Export / Download

Add a **Download Report** button in the Results panel:
```python
st.download_button(
    label="📥 Download Claim Report (PDF / JSON)",
    data=generate_report(result),
    file_name=f"claim_report_{claim_id}.json",
    mime="application/json"
)
```

Report should include: claim summary, outcome, denial/approval probability, XAI reasons, policy references, and fix wizard steps.

### 13.7 Confidence Indicators

Beneath the probability gauge, show a model confidence note:

- If `denial_probability` is in the 0.45–0.55 range: *"⚠️ Model confidence is low for this claim. Manual review is recommended."*
- If `denial_probability > 0.80` or `< 0.20`: *"Model confidence is high for this outcome."*

### 13.8 Mobile Responsiveness

Streamlit is primarily desktop; however:
- Avoid using more than 3 columns at any point.
- Use `use_container_width=True` on all charts and buttons.
- Test at 1024px viewport width minimum.

### 13.9 Tooltips on Technical Fields

Add `help=` parameter on all technical input fields:

```python
st.selectbox("Diagnosis Code", options=diagnosis_codes,
             help="Select the ICD-10 diagnosis code as recorded by the physician.")
st.number_input("Billed Amount (₹)", min_value=0,
                help="Enter the total amount billed for this claim. Must match the invoice.")
```

### 13.10 Batch Mode (Future / Optional)

Add a sidebar toggle: **"🗂️ Batch Upload Mode"**

When enabled, replace the form with a file uploader:
```python
uploaded_file = st.file_uploader("Upload Claims CSV", type=["csv"])
```
Process each row through the pipeline and return a downloadable results CSV with all columns plus `outcome`, `denial_probability`, `top_denial_reason`, `fix_required`.

---

## 14. Complete XAI + RAG + Fix Wizard Alignment Matrix

This matrix ensures all three modules **always agree** with the pipeline outcome:

| Outcome | XAI Shows | RAG Shows | Fix Wizard Shows |
|---|---|---|---|
| Rule Deny | Rule violation list (no SHAP) | Policies for violated rules (1–2 docs) | All hard fixes, numbered, specific |
| Conditional Approval | Both denial drivers AND approval factors | Threshold/review policies (2–3 docs) | Billing flag + secondary ML flags |
| ML Approved (clean) | Nothing (or collapsed) | Nothing (or "No concerns") | "No fixes required" message |
| ML Approved (low risk present) | Approval factors only | 1 informational policy | Low-bill note if applicable |
| ML Denied | Denial drivers prominently; approval factors collapsed | Denial-supporting policies (2–4 docs) | Prioritised fix list per SHAP driver |

---

## 15. Streamlit Page Configuration

```python
st.set_page_config(
    page_title="Claim Denial Prevention System",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="collapsed"
)
```

Use a clean custom CSS injection for production look:

```python
st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        border-radius: 6px 6px 0 0;
        padding: 8px 20px;
        font-weight: 600;
    }
    div[data-testid="stMetricValue"] { font-size: 2rem; }
    .block-container { padding-top: 1.5rem; }
</style>
""", unsafe_allow_html=True)
```

---

*Document version: 1.0 | Project: AI-Powered Claim Denial Prevention & Remediation System | Scope: UI Working Layer Only*
