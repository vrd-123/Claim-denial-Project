"""
api/models/response_models.py
─────────────────────────────────────────────────────────────────────────────
Pydantic output schemas for the Claim Denial Prevention API.
"""

from pydantic import BaseModel, Field
from typing import Optional


class DenialReason(BaseModel):
    """
    A single ranked reason why a claim was (or may be) denied.
    Combines SHAP XAI output with a matched policy passage from ChromaDB RAG.
    """
    rank:          int            = Field(..., description="Priority rank (1 = most impactful)")
    feature:       str            = Field(..., description="Feature name from the ML model")
    explanation:   str            = Field(..., description="Human-readable reason sentence")
    impact_score:  float          = Field(..., description="SHAP proxy score (negative = toward denial)")
    policy_text:   Optional[str]  = Field(None, description="Matched policy passage from ChromaDB")
    policy_source: Optional[str]  = Field(None, description="Policy document filename")


class ClaimResponse(BaseModel):
    """
    Full prediction response returned by POST /predict-claim.
    Combines: ML prediction + SHAP reasons + RAG policy hits + Agent recommendation.
    """
    claim_id:         str               = Field(..., description="Echo of the input claim ID")
    risk_level:       str               = Field(..., description="LOW / MEDIUM / HIGH / CRITICAL")
    denial_prob:      float             = Field(..., ge=0, le=1, description="Denial probability (0.0–1.0)")
    predicted_status: str               = Field(..., description="APPROVED or DENIED")
    reasons:          list[DenialReason] = Field(..., description="Top denial reasons (max 3)")
    recommendation:   str               = Field(..., description="Agent-generated fix instruction")
    next_action:      str               = Field(..., description="Specific actionable step for the billing agent")
    billing_ratio:    float             = Field(..., description="billed_amount / expected_cost")
    processed_at:     str               = Field(..., description="UTC ISO-8601 timestamp")
    error_code:       Optional[str]     = Field(None, description="CDP error code if a partial failure occurred")

    class Config:
        json_schema_extra = {
            "example": {
                "claim_id":         "CLM-001",
                "risk_level":       "HIGH",
                "denial_prob":      0.82,
                "predicted_status": "DENIED",
                "reasons": [
                    {
                        "rank":         1,
                        "feature":      "is_diag_missing",
                        "explanation":  "The medical diagnosis code is missing or invalid in the claim submission.",
                        "impact_score": -0.45,
                        "policy_text":  "POLICY 2.1 — All claims MUST contain a valid ICD-10-CM diagnosis code...",
                        "policy_source": "policy_claim_adjudication.txt",
                    }
                ],
                "recommendation": "Add a valid ICD-10-CM diagnosis code before resubmission.",
                "next_action":    "Obtain the diagnosis from the treating physician and attach to claim.",
                "billing_ratio":  1.1,
                "processed_at":   "2026-05-14T14:00:00Z",
                "error_code":     None,
            }
        }


class HealthResponse(BaseModel):
    """Response for GET /health — used by AWS ELB health checks."""
    status:      str  = "ok"
    environment: str  = "development"
    models_loaded: bool = False
    rag_loaded:    bool = False
    version:       str  = "1.0.0"


class MetricsResponse(BaseModel):
    """Response for GET /metrics — error code frequency for operational monitoring."""
    total_requests:   int
    total_errors:     int
    error_rate_pct:   float
    error_code_counts: dict[str, int]


class ClaimLookupResponse(BaseModel):
    """Response for GET /claim/{claim_id} — Databricks Gold table lookup."""
    claim_id:          str
    predicted_status:  Optional[str]  = None
    denial_probability: Optional[float] = None
    full_explanation:  Optional[str]  = None
    processed_at:      Optional[str]  = None
    found:             bool           = True
    error_code:        Optional[str]  = None
