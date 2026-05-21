"""
api/routers/batch_predict.py — POST /predict-batch
Runs the full predict pipeline for a list of claims in one shot.
"""

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.core.logger import get_logger
from api.core.error_codes import MLException, RAGException
from api.models.request_models import ClaimRequest
from api.models.response_models import ClaimResponse
from api.services import ml_service, rag_service, agent_service

router = APIRouter()
logger = get_logger(__name__)


class BatchClaimRequest(BaseModel):
    claims: List[ClaimRequest]


class BatchClaimResponse(BaseModel):
    total: int
    processed: int
    results: List[dict]


@router.post("/predict-batch", tags=["Predictions"])
async def predict_batch(request: BatchClaimRequest):
    """
    Run the full prediction pipeline for up to 200 claims in one request.
    Each claim goes through: ML inference → RAG → Agent → Response.
    Failed rows get an error_code but do NOT abort the whole batch.
    """
    results = []

    for claim in request.claims:
        row_result = {
            "claim_id": claim.claim_id,
            "error_code": None,
        }

        try:
            # ── Step 1: ML inference ─────────────────────────────────────────
            ml_result = ml_service.predict(claim)

            # ── Step 2: RAG retrieval ────────────────────────────────────────
            shap_scores = ml_result["shap_scores"]
            top_features = sorted(
                shap_scores.items(), key=lambda x: abs(x[1]), reverse=True
            )[:3]
            rag_results: dict = {}
            partial_error_code = None

            for feature, score in top_features:
                msgs = agent_service.REASON_MAP.get(
                    feature, (feature.replace("_", " "), feature.replace("_", " "))
                )
                msg_idx = 0 if score < 0 else 1
                reason_text = msgs[msg_idx] if isinstance(msgs, tuple) else msgs
                try:
                    hits = rag_service.query_policy(reason_text, top_k=2)
                    rag_results[feature] = hits
                except RAGException as exc:
                    rag_results[feature] = []
                    partial_error_code = exc.code

            # ── Step 3: Agent ────────────────────────────────────────────────
            agent_out = agent_service.build_agent_response(claim, ml_result, rag_results)

            # ── Step 4: Assemble ─────────────────────────────────────────────
            reasons = agent_out.get("reasons", [])
            primary_reason = ""
            if reasons:
                first = reasons[0]
                # reasons can be DenialReason objects or dicts
                if hasattr(first, "explanation"):
                    primary_reason = first.explanation
                elif isinstance(first, dict):
                    primary_reason = first.get("explanation") or first.get("message", "")

            row_result.update(
                {
                    "risk_level": ml_result["risk_level"],
                    "denial_prob": round(ml_result["denial_prob"], 4),
                    "predicted_status": ml_result["predicted_status"],
                    "primary_reason": primary_reason,
                    "recommendation": agent_out.get("recommendation", ""),
                    "billing_ratio": round(ml_result["billing_ratio"], 4),
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                    "error_code": partial_error_code,
                }
            )

        except MLException as exc:
            logger.error(
                "[%s] Batch ML failed for claim %s", exc.code, claim.claim_id
            )
            row_result["error_code"] = exc.code
            row_result["predicted_status"] = "ERROR"
            row_result["primary_reason"] = f"ML inference failed: {exc.detail}"

        except Exception as exc:
            logger.exception("Unexpected error in batch for claim %s", claim.claim_id)
            row_result["error_code"] = "E999"
            row_result["predicted_status"] = "ERROR"
            row_result["primary_reason"] = str(exc)

        results.append(row_result)

    return {
        "total": len(request.claims),
        "processed": len(results),
        "results": results,
    }
