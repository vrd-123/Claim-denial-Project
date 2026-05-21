"""
api/main.py
─────────────────────────────────────────────────────────────────────────────
FastAPI application entrypoint for the Claim Denial Prevention system.

Endpoints
─────────
  POST /predict-claim   — full pipeline (ML → XAI → RAG → Agent)
  GET  /claim/{id}      — lookup from Databricks Gold table
  GET  /health          — liveness check for AWS ELB
  GET  /metrics         — error code frequency counts

Run locally
───────────
  uvicorn api.main:app --reload --port 8000

Middleware
──────────
  All requests are logged as structured JSON with:
  timestamp, claim_id, endpoint, response_time_ms, status_code, error_code
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.core.config import get_settings
from api.core.error_codes import ClaimDenialException, ErrorCode
from api.core.logger import get_logger
from api.middleware.logging_middleware import RequestLoggingMiddleware, get_metrics
from api.models.response_models import MetricsResponse
from api.routers import health, lookup, predict, extract, batch_predict
from api.services import ml_service, rag_service

logger = get_logger("api.main")
cfg    = get_settings()


# ── Startup / Shutdown lifespan ────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Loads ML models and RAG collection ONCE at startup.
    Failures here are CRITICAL — the API cannot serve predictions without them.
    """
    logger.info("=== Claim Denial Prevention API — startup BEGIN ===")
    logger.info("Environment: %s", cfg.environment)

    # Load ML models
    try:
        ml_service.load_models()
        logger.info("✅ ML models loaded successfully")
    except Exception as exc:
        logger.critical(
            "[%s] FATAL: ML model load failed at startup: %s",
            ErrorCode.MODEL_NOT_LOADED, str(exc),
        )
        # Don't crash the process — health endpoint will reflect models_loaded=False
        # and prediction requests will return CDP-002-001 errors.

    # Load RAG collection
    try:
        rag_service.load_rag()
        logger.info("✅ RAG collection loaded successfully")
    except Exception as exc:
        logger.critical(
            "[%s] FATAL: RAG load failed at startup: %s",
            ErrorCode.POLICY_LOAD_FAILED, str(exc),
        )
        # Same pattern — prediction requests without RAG will get partial_error_code set.

    logger.info("=== API startup COMPLETE — listening on port %s ===", cfg.api_port)
    yield  # ← application runs here
    logger.info("=== API shutdown ===")


# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Claim Denial Prevention API",
    description=(
        "Production FastAPI backend for the AI-Powered Claim Denial Prevention system. "
        "Exposes ML inference, RAG policy retrieval, and agent recommendation endpoints."
    ),
    version="1.0.0",
    docs_url="/docs",       # Swagger UI — auto-generated
    redoc_url="/redoc",     # ReDoc UI
    lifespan=lifespan,
)

# ── Middleware ─────────────────────────────────────────────────────────────────
app.add_middleware(RequestLoggingMiddleware)

# ── Global exception handler — never expose raw Python tracebacks ─────────────
@app.exception_handler(ClaimDenialException)
async def cdp_exception_handler(request: Request, exc: ClaimDenialException):
    logger.error(
        "[%s] %s",
        exc.code, exc.detail,
        extra={"error_code": exc.code},
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": exc.code, "detail": exc.detail},
        headers={"X-Error-Code": exc.code},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(
        "[%s] Unhandled exception: %s",
        ErrorCode.INVALID_INPUT, str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "CDP-001-000",
            "detail":     "An unexpected server error occurred. Please contact support.",
        },
    )


# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(predict.router)
app.include_router(lookup.router)
app.include_router(extract.router)
app.include_router(batch_predict.router)


# ── Metrics endpoint ───────────────────────────────────────────────────────────
@app.get("/metrics", response_model=MetricsResponse, tags=["Ops"])
async def get_request_metrics() -> MetricsResponse:
    """
    Returns real-time error code frequency counts.
    Answers the manager question: 'What are the most frequent errors in the system?'
    Metric filters in CloudWatch map to these CDP error code prefixes.
    """
    data = get_metrics()
    return MetricsResponse(**data)


# ── Root redirect to docs ──────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def root():
    return JSONResponse(
        content={
            "service": "Claim Denial Prevention API",
            "version": "1.0.0",
            "docs":    "/docs",
            "health":  "/health",
        }
    )
