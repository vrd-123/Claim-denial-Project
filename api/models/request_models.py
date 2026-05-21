"""
api/models/request_models.py
─────────────────────────────────────────────────────────────────────────────
Pydantic input schemas for the Claim Denial Prevention API.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import date


class ClaimRequest(BaseModel):
    """
    Incoming claim payload for POST /predict-claim.

    Only claim_id is required — all other fields are optional because
    the ML service will look up defaults from Databricks Silver tables
    when a field is missing and set the corresponding is_*_missing flag.
    """
    claim_id:       str             = Field(..., description="Unique claim identifier (e.g. CLM-001)")
    patient_id:     Optional[str]   = Field(None, description="Patient identifier — NOT logged (HIPAA)")
    provider_id:    Optional[str]   = Field(None, description="Provider NPI or internal ID")
    diagnosis_code: Optional[str]   = Field(None, description="ICD-10-CM diagnosis code (e.g. I21.0)")
    procedure_code: Optional[str]   = Field(None, description="CPT procedure code (e.g. 93010)")
    policy_id:      Optional[str]   = Field(None, description="Policy ID attached to the claim")
    billed_amount:  Optional[float] = Field(None, ge=0, description="Billed amount in USD (must be ≥ 0)")
    service_date:   Optional[date]  = Field(None, description="Date of service (YYYY-MM-DD)")

    class Config:
        json_schema_extra = {
            "example": {
                "claim_id":       "CLM-001",
                "provider_id":    "PRV-001",
                "diagnosis_code": "I21.0",
                "procedure_code": "93010",
                "billed_amount":  1500.0,
                "service_date":   "2026-01-15",
            }
        }


class ClaimLookupRequest(BaseModel):
    """Path-based lookup; claim_id comes from the URL parameter."""
    claim_id: str = Field(..., description="Claim ID to look up in the Gold table")
