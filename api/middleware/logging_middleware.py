"""
api/middleware/logging_middleware.py
─────────────────────────────────────────────────────────────────────────────
Request/response logging middleware.

Logs every request as a structured JSON line with:
  timestamp, claim_id (if present), endpoint, response_time_ms,
  status_code, error_code (if any).

HIPAA compliance: patient_id, diagnosis codes, and names are NEVER logged.
"""

import json
import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from api.core.logger import get_logger

logger = get_logger("api.middleware")

# Global in-process metrics counter (resets on restart)
# In production, replace with Prometheus or CloudWatch metrics
_metrics: dict[str, int] = {
    "total_requests": 0,
    "total_errors":   0,
}
_error_code_counts: dict[str, int] = {}


def get_metrics() -> dict:
    """Return a snapshot of current request/error metrics."""
    total = _metrics["total_requests"]
    errors = _metrics["total_errors"]
    rate = round((errors / total * 100), 2) if total > 0 else 0.0
    return {
        "total_requests":   total,
        "total_errors":     errors,
        "error_rate_pct":   rate,
        "error_code_counts": dict(_error_code_counts),
    }


def _extract_claim_id(body_bytes: bytes) -> str:
    """Safely extract claim_id from request body without logging PHI."""
    try:
        body = json.loads(body_bytes)
        return str(body.get("claim_id", ""))
    except Exception:
        return ""


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Starlette BaseHTTPMiddleware that logs every request/response pair
    as a structured JSON line suitable for CloudWatch Logs Insights.
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.monotonic()
        _metrics["total_requests"] += 1

        # Read body for claim_id extraction (POST endpoints only)
        claim_id = ""
        if request.method == "POST":
            body_bytes = await request.body()
            claim_id   = _extract_claim_id(body_bytes)
            # Re-attach body so the route handler can still read it
            async def receive():
                return {"type": "http.request", "body": body_bytes}
            request = Request(request.scope, receive)

        # Process request
        error_code = None
        try:
            response = await call_next(request)
        except Exception as exc:
            elapsed_ms = round((time.monotonic() - start_time) * 1000, 1)
            _metrics["total_errors"] += 1
            logger.error(
                "Unhandled exception in middleware",
                extra={
                    "claim_id":        claim_id,
                    "endpoint":        str(request.url.path),
                    "response_time_ms": elapsed_ms,
                    "status_code":     500,
                    "error_code":      "CDP-001-000",
                },
                exc_info=True,
            )
            raise

        elapsed_ms = round((time.monotonic() - start_time) * 1000, 1)
        status     = response.status_code

        # Extract error_code header if set by exception handlers
        error_code = response.headers.get("X-Error-Code", None)

        # Track error codes
        if status >= 400:
            _metrics["total_errors"] += 1
            if error_code:
                _error_code_counts[error_code] = _error_code_counts.get(error_code, 0) + 1

        # Structured log line
        logger.info(
            "%s %s → %d (%.1fms)",
            request.method, request.url.path, status, elapsed_ms,
            extra={
                "claim_id":         claim_id or None,
                "endpoint":         str(request.url.path),
                "response_time_ms": elapsed_ms,
                "status_code":      status,
                "error_code":       error_code,
            },
        )

        return response
