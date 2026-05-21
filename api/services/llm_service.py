"""
api/services/llm_service.py
─────────────────────────────────────────────────────────────────────────────
Field extraction from raw claim text.

Priority:
  1. OpenAI GPT-4o  — if OPENAI_API_KEY is set
  2. Regex heuristics — always available, no external dependency
"""
import os
import re
import json
from datetime import datetime, date

# ── Regex heuristic extraction (no external API needed) ──────────────────────

def _regex_extract(text: str) -> dict:
    """
    Extract the 7 claim fields from free-form text using labelled-value patterns.
    Returns the same structured dict as the LLM path
    {field: {"value": ..., "confidence": float}}.
    """
    def search(patterns: list, confidence_base=0.90) -> tuple:
        """Return (value, confidence) or (None, 0)."""
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip(), confidence_base
        return None, 0.0

    # ── claim_id ──────────────────────────────────────────────────────────────
    cid_val, cid_conf = search([
        r"Claim\s*(?:Identifier|ID|Number|#)[\s:]+([C]\d{4,})",
        r"\b(C\d{4,})\b",
    ])

    # ── patient_id ────────────────────────────────────────────────────────────
    pid_val, pid_conf = search([
        r"Patient\s*(?:ID|Number|#)[\s:]+([P]\d{3,})",
        r"\b(P\d{3,})\b",
    ])

    # ── provider_id ───────────────────────────────────────────────────────────
    prid_val, prid_conf = search([
        r"Provider\s*(?:ID|Number|#)[\s:]+(\S+)",
    ], confidence_base=0.85)

    # ── diagnosis_code ────────────────────────────────────────────────────────
    diag_val, diag_conf = search([
        r"(?:Primary\s+)?Diagnosis(?:\s+Code)?[\s:]+([A-Z]\d+(?:\.\d+)?)",
        r"\b(D\d{2,})\b",
    ])

    # ── procedure_code ────────────────────────────────────────────────────────
    proc_val, proc_conf = search([
        r"Procedure(?:\s+(?:Code|Performed|ID))?[\s:]+(\S+)",
        r"\b(PROC\d+)\b",
    ], confidence_base=0.88)
    # Strip trailing parenthetical descriptions e.g. "PROC1 (Echocardiogram)"
    if proc_val:
        proc_val = proc_val.split("(")[0].strip()

    # ── policy_id ─────────────────────────────────────────────────────────────
    pol_val, pol_conf = search([
        r"Policy\s*(?:ID|Number|#)[\s:]+(POL\d+)",
        r"\b(POL\d+)\b",
    ], confidence_base=0.90)

    # ── billed_amount ─────────────────────────────────────────────────────────
    amt_val, amt_conf = None, 0.0
    amt_patterns = [
        r"Billed\s*Amount[\s:]+\$?([\d,]+(?:\.\d{1,2})?)",
        r"Total\s*(?:Amount|Cost|Charged)[\s:]+\$?([\d,]+(?:\.\d{1,2})?)",
        r"\$\s*([\d,]+(?:\.\d{1,2})?)",
    ]
    for pat in amt_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(",", "")
            try:
                amt_val = float(raw)
                amt_conf = 0.92
            except ValueError:
                pass
            break

    # ── date ──────────────────────────────────────────────────────────────────
    dt_val, dt_conf = None, 0.0
    date_patterns = [
        r"Date\s*(?:of\s*Service|of\s*Care|of\s*Visit)?[\s:]+(\d{4}-\d{2}-\d{2})",
        r"Service\s*Date[\s:]+(\d{4}-\d{2}-\d{2})",
        # human-readable formats
        r"Date\s*[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    ]
    for pat in date_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            # Try ISO first
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y"):
                try:
                    parsed = datetime.strptime(raw, fmt).date()
                    dt_val = parsed.isoformat()
                    dt_conf = 0.90
                    break
                except ValueError:
                    continue
            if dt_val:
                break

    result = {}
    if cid_val:
        result["claim_id"] = {"value": cid_val, "confidence": cid_conf}
    if pid_val:
        result["patient_id"] = {"value": pid_val, "confidence": pid_conf}
    if prid_val:
        result["provider_id"] = {"value": prid_val, "confidence": prid_conf}
    if diag_val:
        result["diagnosis_code"] = {"value": diag_val, "confidence": diag_conf}
    if proc_val:
        result["procedure_code"] = {"value": proc_val, "confidence": proc_conf}
    if amt_val is not None:
        result["billed_amount"] = {"value": amt_val, "confidence": amt_conf}
    if dt_val:
        result["date"] = {"value": dt_val, "confidence": dt_conf}
    if pol_val:
        result["policy_id"] = {"value": pol_val, "confidence": pol_conf}

    return result


# ── OpenAI path ───────────────────────────────────────────────────────────────

async def _openai_extract(text: str, api_key: str) -> dict:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=api_key)
    prompt = (
        "Extract the following 8 claim fields from the raw text below. "
        "Return a JSON object where each key maps to {\"value\": ..., \"confidence\": 0.0-1.0}.\n"
        "Keys: claim_id (format CXXXX), patient_id (format PXXX), provider_id, "
        "diagnosis_code, procedure_code, billed_amount (numeric float), date (YYYY-MM-DD), policy_id (format POLXXX).\n"
        "If a field is absent return null for value and 0.0 for confidence.\n\n"
        f"Raw text:\n{text}"
    )
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a medical claims extraction assistant. Return strict JSON only."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )
    raw = json.loads(response.choices[0].message.content)
    # Normalise: ensure each key has value/confidence structure
    result = {}
    for k, v in raw.items():
        if isinstance(v, dict) and "value" in v:
            result[k] = v
        elif v is not None:
            result[k] = {"value": v, "confidence": 0.80}
    return result


# ── Public entry-point ────────────────────────────────────────────────────────

async def extract_fields_with_llm(text: str) -> dict:
    """
    Extract claim fields from raw text.
    Uses OpenAI if OPENAI_API_KEY is set, otherwise falls back to regex heuristics.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if api_key:
        try:
            return await _openai_extract(text, api_key)
        except Exception:
            pass  # Fall through to regex

    # Always available: regex heuristic extraction
    return _regex_extract(text)
