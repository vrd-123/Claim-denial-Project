"""
api/routers/predict.py — POST /predict-claim
Full pipeline: ML inference → SHAP proxy → RAG policy retrieval → Agent recommendation.
"""

from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.core.error_codes import ErrorCode, ClaimDenialException, MLException, RAGException
from api.core.logger import get_logger
from api.models.request_models import ClaimRequest
from api.models.response_models import ClaimResponse
from api.services import ml_service, rag_service, agent_service

router = APIRouter()
logger = get_logger(__name__)


@router.post("/predict-claim", response_model=ClaimResponse, tags=["Predictions"])
async def predict_claim(request: ClaimRequest) -> ClaimResponse:
    """
    Full prediction pipeline for a single claim.

    Flow
    ────
    1. ML inference (XGBoost) → denial_prob, predicted_status, shap_scores
    2. RAG retrieval (ChromaDB) → policy passages for each denial reason
    3. Agent service → ranked DenialReasons + recommendation + next_action
    4. Return structured ClaimResponse

    Error codes are embedded in the response (not HTTP 500) so the Streamlit UI
    can display them to the billing agent.
    """
    logger.info(
        "Prediction request received",
        extra={"claim_id": request.claim_id},
    )

    partial_error_code = None

    # ── Step 1: ML inference ─────────────────────────────────────────────────
    try:
        ml_result = ml_service.predict(request)
    except MLException as exc:
        logger.error(
            "[%s] ML prediction failed for claim %s",
            exc.code, request.claim_id,
            extra={"claim_id": request.claim_id, "error_code": exc.code},
        )
        return JSONResponse(
            status_code=503,
            content={
                "claim_id":   request.claim_id,
                "error_code": exc.code,
                "detail":     exc.detail,
            },
            headers={"X-Error-Code": exc.code},
        )

    # ── Step 2: RAG retrieval for each top SHAP feature ───────────────────────
    shap_scores = ml_result["shap_scores"]
    predicted_status = ml_result["predicted_status"]

    # Top-3 by absolute SHAP magnitude (most impactful features for either direction)
    top_features = sorted(shap_scores.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
    rag_results: dict[str, list[dict]] = {}

    for feature, score in top_features:
        msgs = agent_service.REASON_MAP.get(feature, (feature.replace("_", " "), feature.replace("_", " ")))
        # Use denial message for negative SHAP (pushes toward DENY),
        # approval message for positive SHAP (pushes toward APPROVE)
        msg_idx = 0 if score < 0 else 1
        reason_text = msgs[msg_idx] if isinstance(msgs, tuple) else msgs
        try:
            hits = rag_service.query_policy(reason_text, top_k=2)
            rag_results[feature] = hits
        except RAGException as exc:
            logger.warning(
                "[%s] RAG query failed for feature %s — proceeding without policy text",
                exc.code, feature,
                extra={"claim_id": request.claim_id, "error_code": exc.code},
            )
            rag_results[feature] = []
            partial_error_code = exc.code


    # ── Step 3: Agent builds ranked reasons + recommendation ──────────────────
    agent_out = agent_service.build_agent_response(request, ml_result, rag_results)

    # ── Step 4: Assemble final response ───────────────────────────────────────
    response = ClaimResponse(
        claim_id=request.claim_id,
        risk_level=ml_result["risk_level"],
        denial_prob=round(ml_result["denial_prob"], 4),
        predicted_status=ml_result["predicted_status"],
        reasons=agent_out["reasons"],
        recommendation=agent_out["recommendation"],
        next_action=agent_out["next_action"],
        billing_ratio=round(ml_result["billing_ratio"], 4),
        processed_at=datetime.now(timezone.utc).isoformat(),
        error_code=partial_error_code,
    )

    logger.info(
        "Prediction complete: %s → %s (risk=%s, p=%.3f)",
        request.claim_id,
        ml_result["predicted_status"],
        ml_result["risk_level"],
        ml_result["denial_prob"],
        extra={"claim_id": request.claim_id},
    )

    return response
