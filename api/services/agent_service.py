"""
api/services/agent_service.py
─────────────────────────────────────────────────────────────────────────────
Recommendation Agent — converts ML + RAG outputs into specific, actionable
fix instructions for the billing agent.

Rule table (from Week 7 implementation guide):
  is_diag_missing     → Add ICD-10-CM code before resubmission
  is_proc_missing     → Add CPT procedure code matching the service
  is_billed_missing   → Submit the billed amount
  billing_ratio > 2.0 → Reduce billed amount to within 150% of benchmark
  high_cost_flag      → Flag for manual medical review
  provider_claim_count→ Attach additional credentials
  claim_age_days > 90 → Request timely filing exception
  severity_score      → Ensure diagnosis severity matches procedure complexity
"""

from api.core.error_codes import ErrorCode, AgentException
from api.core.logger import get_logger
from api.models.request_models import ClaimRequest
from api.models.response_models import DenialReason

logger = get_logger(__name__)

# ── SHAP feature → human-readable explanation (Denial, Approval) ────────────────
REASON_MAP: dict[str, tuple[str, str]] = {
    "billing_ratio": (
        "Claim billed amount is significantly higher than the benchmark expected cost.",
        "Claim billed amount is within the accepted benchmark cost range.",
    ),
    "cost_diff": (
        "The absolute cost gap between billed and expected amounts is excessively large.",
        "The cost gap between billed and expected amounts is within acceptable limits.",
    ),
    "high_cost_flag": (
        "Claim has been flagged as an extreme high-cost outlier by the cost model.",
        "No high-cost outlier flag detected; billing appears standard.",
    ),
    "provider_claim_count": (
        "The provider's low historical claim volume indicates a higher operational risk profile.",
        "The provider has a high historical claim volume, suggesting a reliable submission pattern.",
    ),
    "provider_specialty_enc": (
        "The billing pattern is inconsistent with the provider's recorded medical specialty.",
        "The billing pattern is consistent with the provider's medical specialty.",
    ),
    "diag_claim_count": (
        "This diagnosis code has an unusually low historical claim frequency, indicating potential miscoding.",
        "This diagnosis code has a strong historical claim frequency, indicating a reliable submission.",
    ),
    "diag_category_enc": (
        "The diagnosis category is inconsistent with the procedure and billing pattern submitted.",
        "The diagnosis category is consistent with the procedure and billing pattern.",
    ),
    "is_billed_missing": (
        "The claim billed amount was missing from the original source submission.",
        "The claim billed amount is present and valid in the original submission.",
    ),
    "is_proc_missing": (
        "The medical procedure code is missing or invalid in the claim submission.",
        "The medical procedure code is present and valid.",
    ),
    "is_diag_missing": (
        "The medical diagnosis code is missing or invalid in the claim submission.",
        "The medical diagnosis code is present and valid.",
    ),
    "claim_age_days": (
        "The claim was submitted significantly late relative to the service date.",
        "The claim was submitted promptly relative to the service date.",
    ),
    "policy_violation": (
        "Claim violates the terms of the assigned policy (uncovered procedure or invalid dates).",
        "Claim meets the assigned policy terms.",
    ),
}

# ── Agent recommendation rule table (primary denial feature → fix) ────────────
RECOMMENDATION_MAP: dict[str, dict[str, str]] = {
    "is_diag_missing": {
        "recommendation": "Add a valid ICD-10-CM diagnosis code before resubmission.",
        "next_action":    "Obtain the diagnosis from the treating physician and attach to claim.",
    },
    "is_proc_missing": {
        "recommendation": "Add the CPT procedure code matching the service rendered.",
        "next_action":    "Verify the procedure performed and select the correct CPT code.",
    },
    "is_billed_missing": {
        "recommendation": "Submit the billed amount; claims without a billing amount are auto-rejected.",
        "next_action":    "Calculate and enter the billed amount based on the service performed.",
    },
    "billing_ratio": {
        "recommendation": "Review and reduce the billed amount to within 150% of the benchmark expected cost.",
        "next_action":    "Compare the billed amount against the payer's fee schedule and adjust accordingly.",
    },
    "high_cost_flag": {
        "recommendation": "Flag for manual medical review before resubmission.",
        "next_action":    "Submit a letter of medical necessity with supporting clinical documentation.",
    },
    "provider_claim_count": {
        "recommendation": "Provider has low claim history; attach additional credentials.",
        "next_action":    "Include provider NPI, license number, and specialty verification in the claim.",
    },
    "claim_age_days": {
        "recommendation": "This claim is outside the timely filing window; request a filing exception.",
        "next_action":    "Submit a timely filing exception request with proof of earlier submission attempt.",
    },
    "policy_violation": {
        "recommendation": "Review the assigned policy terms for valid procedures and dates.",
        "next_action":    "Ensure the claim date and procedure code are covered by the policy.",
    },
    "severity_score": {
        "recommendation": "Ensure the diagnosis severity matches the complexity of the billed procedure.",
        "next_action":    "Review that the ICD-10 diagnosis code justifies the CPT procedure billed.",
    },
    "cost_diff": {
        "recommendation": "Reconcile the cost difference between billed and expected amount.",
        "next_action":    "Review the payer's fee schedule and resubmit with a corrected billing amount.",
    },
    "diag_category_enc": {
        "recommendation": "Verify the diagnosis category is appropriate for the billed procedure.",
        "next_action":    "Cross-reference the ICD-10 category with the CPT code to confirm clinical alignment.",
    },
    "provider_specialty_enc": {
        "recommendation": "Ensure procedure is within scope of the provider's documented specialty.",
        "next_action":    "Attach a specialty certification or referral authorization for out-of-scope services.",
    },
    "diag_claim_count": {
        "recommendation": "This diagnosis code has elevated denial rates — add additional clinical documentation.",
        "next_action":    "Attach clinical notes, lab results, or imaging reports that support the diagnosis.",
    },
}

_DEFAULT_RECOMMENDATION = {
    "recommendation": "Review the claim for completeness and accuracy before resubmission.",
    "next_action":    "Consult the payer's claim submission guide and verify all required fields are populated.",
}


def build_denial_reasons(
    shap_scores: dict[str, float],
    rag_results: dict[str, list[dict]],
    predicted_status: str,
    top_n: int = 3,
    feature_vector: dict[str, float] = None,
) -> list[DenialReason]:
    """
    Builds a ranked list of DenialReason objects from SHAP proxy scores and
    RAG-retrieved policy passages.

    Selects top_n features by absolute SHAP magnitude so that:
    - DENIED claims:   negative-score features = denial drivers
    - APPROVED claims: positive-score features = approval factors
    Both are always present and meaningful.
    """
    # Filter out truly zero-impact features (e.g. provider_specialty_enc = 0.0)
    filtered = {k: v for k, v in shap_scores.items() if abs(v) > 0.0001}

    # User requested: remove severity_score as a reason for approved claims (including approved with warning)
    if predicted_status == "APPROVED":
        if "severity_score" in filtered:
            del filtered["severity_score"]

    # Sort logic: on APPROVED claims, bubble negative warning drivers to the top
    # so that warnings are guaranteed to appear in the XAI/SHAP reasons card.
    if predicted_status == "APPROVED":
        negatives = sorted([(k, v) for k, v in filtered.items() if v < 0], key=lambda x: abs(x[1]), reverse=True)
        positives = sorted([(k, v) for k, v in filtered.items() if v >= 0], key=lambda x: abs(x[1]), reverse=True)
        ranked = (negatives + positives)[:top_n]
    else:
        # Sort strictly by descending absolute magnitude (most impactful first)
        ranked = sorted(filtered.items(), key=lambda x: abs(x[1]), reverse=True)[:top_n]

    reasons: list[DenialReason] = []
    for rank, (feature, score) in enumerate(ranked, start=1):
        hits       = rag_results.get(feature, [])
        top_policy = hits[0] if hits else None

        # Select message based on SHAP sign: negative → denial message, positive → approval
        msgs = REASON_MAP.get(feature, ("Feature contributed to denial risk.", "Feature contributed to approval."))
        msg_idx = 0 if score < 0 else 1
        explanation = msgs[msg_idx] if isinstance(msgs, tuple) else msgs

        # Override for billing_ratio deviation warnings
        if feature == "billing_ratio" and score < 0 and feature_vector:
            br_val = feature_vector.get("billing_ratio", 1.0)
            if br_val < 1.0:
                explanation = "Billing amount is less than the expected cost of the procedure."
            elif br_val > 1.0:
                explanation = "Billing amount is more than the expected cost of the procedure."

        reasons.append(DenialReason(
            rank=rank,
            feature=feature,
            explanation=explanation,
            impact_score=round(score, 4),
            policy_text=top_policy["policy_text"] if top_policy else None,
            policy_source=top_policy["source_doc"] if top_policy else None,
        ))

    return reasons



def get_recommendation(top_feature: str, feature_vector: dict[str, float]) -> dict[str, str]:
    """
    Returns the {recommendation, next_action} for the top denial driver.

    Applies context-specific overrides before the rule table lookup:
    - billing_ratio is only flagged if it actually exceeds 2.0
    - claim_age_days is only flagged if age > 90 days
    """
    # Context-sensitive guard: billing_ratio rule only when ratio exceeds 1.5
    # (1.5 is the high_cost_flag threshold in the feature engineering notebook)
    if top_feature == "billing_ratio" and feature_vector.get("billing_ratio", 0) <= 1.5:
        top_feature = "cost_diff"

    # Context-sensitive guard: claim_age rule only when truly late
    if top_feature == "claim_age_days" and feature_vector.get("claim_age_days", 0) <= 90:
        top_feature = "severity_score"

    return RECOMMENDATION_MAP.get(top_feature, _DEFAULT_RECOMMENDATION)


def build_agent_response(
    request: ClaimRequest,
    ml_result: dict,
    rag_results: dict[str, list[dict]],
) -> dict:
    """
    Orchestrates the full agent response.

    Parameters
    ----------
    request    : ClaimRequest — original user input
    ml_result  : dict         — output from ml_service.predict()
    rag_results: dict         — feature → RAG policy hits

    Returns
    -------
    dict with keys: reasons, recommendation, next_action
    """
    try:
        shap_scores      = ml_result["shap_scores"]
        feature_vector   = ml_result["feature_vector"]
        predicted_status = ml_result.get("predicted_status", "DENIED")

        # Build ranked reasons (SHAP + RAG combined) filtered by status
        reasons = build_denial_reasons(shap_scores, rag_results, predicted_status, top_n=3, feature_vector=feature_vector)

        # For DENIED: top denial driver = most negative SHAP feature
        # For APPROVED: show approval confirmation (no "fix" needed) or a warning recommendation
        denial_drivers  = [r for r in reasons if r.impact_score < 0]
        approval_factors = [r for r in reasons if r.impact_score >= 0]

        if predicted_status == "APPROVED":
            if not denial_drivers:
                top_feature = approval_factors[0].feature if approval_factors else "billing_ratio"
                rec = {
                    "recommendation": "Claim looks solid — all key risk factors are within acceptable ranges.",
                    "next_action":    "Proceed with standard claim submission workflow. No corrections needed.",
                }
            else:
                top_feature = denial_drivers[0].feature
                br = feature_vector.get("billing_ratio", 1.0)
                if br < 1.0:
                    rec = {
                        "recommendation": "Manual review needed: billing amount is less than expected cost.",
                        "next_action":    "Billing amount is less than the expected cost of the procedure. Recheck billing before submission.",
                    }
                else:
                    rec = {
                        "recommendation": "Manual review needed: billing amount is more than expected cost.",
                        "next_action":    "Billing amount is more than the expected cost of the procedure. Recheck billing before submission.",
                    }
        else:
            top_feature = denial_drivers[0].feature if denial_drivers else (reasons[0].feature if reasons else "is_diag_missing")
            rec = get_recommendation(top_feature, feature_vector)

        logger.info(
            "Agent recommendation: feature=%s | rec=%s",
            top_feature, rec["recommendation"][:80],
            extra={"claim_id": request.claim_id},
        )

        return {
            "reasons":        reasons,
            "recommendation": rec["recommendation"],
            "next_action":    rec["next_action"],
        }

    except Exception as exc:
        logger.error(
            "[%s] Agent failed for claim %s: %s",
            ErrorCode.AGENT_BUILD_FAILED, request.claim_id, str(exc),
            exc_info=True,
        )
        raise AgentException(
            code=ErrorCode.AGENT_BUILD_FAILED,
            detail=f"Agent failed to build recommendation: {exc}",
        )
