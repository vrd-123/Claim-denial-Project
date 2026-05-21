"""
api/routers/health.py — GET /health liveness check for AWS ELB.
"""

from fastapi import APIRouter
from api.models.response_models import HealthResponse
from api.services import ml_service, rag_service
from api.core.config import get_settings

router  = APIRouter()
cfg     = get_settings()


@router.get("/health", response_model=HealthResponse, tags=["Ops"])
async def health_check() -> HealthResponse:
    """
    Liveness endpoint polled by AWS ELB every 30s.
    Returns HTTP 200 when the service is running.
    Models/RAG loaded status helps diagnose cold-start issues.
    """
    return HealthResponse(
        status="ok",
        environment=cfg.environment,
        models_loaded=ml_service.is_loaded(),
        rag_loaded=rag_service.is_loaded(),
        version="1.0.0",
    )
