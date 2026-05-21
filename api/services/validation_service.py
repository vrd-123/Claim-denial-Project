"""
api/services/validation_service.py
─────────────────────────────────────────────────────────────────────────────
Post-extraction validation: hard blocks (prevent auto-fill) and soft warnings
(show to user but still allow auto-fill).
"""
import re
import datetime
import csv
import os


def load_csv(path, col):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [row[col].strip() for row in csv.DictReader(f) if col in row]
    except Exception:
        return []


def validate_extracted(extracted: dict) -> dict:
    blocks = []
    warnings = []

    def get_val(key):
        return extracted.get(key, {}).get("value")

    def get_conf(key):
        return extracted.get(key, {}).get("confidence", 0)

    cid   = get_val("claim_id")
    pid   = get_val("patient_id")
    bamt  = get_val("billed_amount")
    dval  = get_val("date")
    prid  = get_val("provider_id")
    dcode = get_val("diagnosis_code")
    pcode = get_val("procedure_code")
    polid = get_val("policy_id")

    # ── HARD BLOCKS: these prevent auto-fill ─────────────────────────────────

    # claim_id
    if not cid:
        blocks.append("R-H1: claim_id is missing from the document")
    elif not re.match(r"^C\d{4,}$", str(cid)):
        blocks.append(f"R-H3: claim_id '{cid}' does not match required format CXXXX (e.g. C1234)")

    # patient_id
    if not pid:
        blocks.append("R-H2: patient_id is missing from the document")
    elif not re.match(r"^P\d{3,}$", str(pid)):
        blocks.append(f"R-H4: patient_id '{pid}' does not match required format PXXX (e.g. P206)")

    # billed_amount
    if bamt is None:
        blocks.append("R-H5: billed_amount is missing from the document")
    elif not isinstance(bamt, (int, float)) or bamt < 0:
        blocks.append(f"R-H5: billed_amount '{bamt}' is non-numeric or negative")

    # service date
    if not dval:
        blocks.append("R-H6: service date is missing from the document")
    else:
        try:
            d = datetime.datetime.strptime(str(dval), "%Y-%m-%d").date()
            if d > datetime.date.today():
                blocks.append(f"R-H6: service date '{dval}' is in the future")
        except ValueError:
            blocks.append(f"R-H6: service date '{dval}' could not be parsed as YYYY-MM-DD")

    # policy_id
    if not polid:
        blocks.append("R-H8: policy_id is missing from the document")
    elif not re.match(r"^POL\d{3,}$", str(polid)):
        blocks.append(f"R-H9: policy_id '{polid}' does not match required format POLXXX (e.g. POL001)")

    # overall confidence
    confs = [get_conf(k) for k in extracted.keys() if get_conf(k) > 0]
    avg_conf = sum(confs) / len(confs) if confs else 0
    if avg_conf < 0.40 and confs:
        blocks.append(f"R-H7: Overall extraction confidence is very low ({avg_conf:.2f}). "
                      "Document may be unreadable or unrelated to a claim.")

    # ── SOFT WARNINGS: shown to user, do not block auto-fill ─────────────────

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    provs = load_csv(os.path.join(base_dir, "data/raw/providers_1000.csv"), "provider_id")
    diags = load_csv(os.path.join(base_dir, "data/raw/diagnosis.csv"), "diagnosis_code")
    costs = load_csv(os.path.join(base_dir, "data/raw/cost.csv"), "procedure_code")

    if prid and provs and prid not in provs:
        warnings.append(f"R-S1: provider_id '{prid}' was not found in the approved provider list — verify manually")
    if dcode and diags and dcode not in diags:
        warnings.append(f"R-S2: diagnosis_code '{dcode}' was not found in the approved diagnosis list — verify manually")
    if pcode and costs and pcode not in costs:
        warnings.append(f"R-S3: procedure_code '{pcode}' was not found in the approved CPT list — verify manually")

    if not pcode:
        warnings.append("R-S5: procedure_code is missing — select it manually in the form")
    if not dcode:
        warnings.append("R-S6: diagnosis_code is missing — select it manually in the form")
    if not prid:
        warnings.append("R-S7: provider_id is missing — select it manually in the form")

    # Per-field low-confidence warnings
    for k, v in extracted.items():
        c = v.get("confidence", 0)
        if 0.40 <= c <= 0.70:
            warnings.append(f"R-S4: Field '{k}' was extracted with low confidence ({c:.2f}) — please verify")

    return {
        "hard_blocks": blocks,
        "soft_warnings": warnings,
    }
