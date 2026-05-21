"""
api/routers/lookup.py — GET /claim/{claim_id}
Looks up a claim from the Databricks Gold table.
Falls back gracefully if Databricks is unavailable in dev mode.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.core.error_codes import ErrorCode, DatabricksException
from api.core.logger import get_logger
from api.models.response_models import ClaimLookupResponse
from api.services import databricks_service

router = APIRouter()
logger = get_logger(__name__)


@router.get("/claim/{claim_id}", response_model=ClaimLookupResponse, tags=["Claims"])
async def lookup_claim(claim_id: str) -> ClaimLookupResponse:
    """
    Retrieve a previously processed claim from workspace.gold.gold_claim_policy_explanations.

    - Returns the full explanation, predicted status, and denial probability.
    - If the claim is not found, returns found=False.
    - If Databricks is unavailable (dev mode), returns a graceful offline response.
    """
    logger.info("Claim lookup requested", extra={"claim_id": claim_id})

    try:
        row = databricks_service.lookup_claim(claim_id)
        if row is None:
            logger.info("Claim not found in Gold table", extra={"claim_id": claim_id})
            return ClaimLookupResponse(
                claim_id=claim_id,
                found=False,
                full_explanation=f"Claim {claim_id} was not found in the Gold table. "
                                 "It may not have been processed yet or the claim ID is incorrect.",
            )

        return ClaimLookupResponse(
            claim_id=row.get("claim_id", claim_id),
            predicted_status=row.get("predicted_status"),
            denial_probability=row.get("denial_probability"),
            full_explanation=row.get("full_explanation"),
            processed_at=str(row.get("processed_at", "")),
            found=True,
        )

    except DatabricksException as exc:
        logger.warning(
            "[%s] Databricks unavailable for lookup %s: %s",
            exc.code, claim_id, exc.detail,
            extra={"claim_id": claim_id, "error_code": exc.code},
        )
        return ClaimLookupResponse(
            claim_id=claim_id,
            found=False,
            full_explanation="Databricks connection unavailable. "
                             "Claim lookup requires a live Databricks SQL warehouse connection.",
            error_code=exc.code,
        )
