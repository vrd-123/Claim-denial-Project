"""
api/core/logger.py
─────────────────────────────────────────────────────────────────────────────
Centralized, structured JSON logging for the Claim Denial Prevention API.

Key design decisions
────────────────────
• JSON format — CloudWatch can parse it natively as structured log events.
• LOG_LEVEL environment variable controls verbosity (no hardcoded levels).
• HIPAA-safe: patient_id, names, and diagnosis codes are NEVER logged.
  Only claim_id is included in log records.
• Log hierarchy:
    DEBUG    → Feature engineering intermediate values
    INFO     → Request received, prediction completed, RAG query run
    WARNING  → Model fallback used, Databricks connection slow
    ERROR    → [CDP-XXX-XXX] Specific failure with error code
    CRITICAL → Model not loaded, API startup failed
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON objects.
    Suitable for CloudWatch Logs Insights queries.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "level":      record.levelname,
            "logger":     record.name,
            "message":    record.getMessage(),
        }

        # Attach structured extras if present (e.g., claim_id, error_code)
        for key in ("claim_id", "endpoint", "response_time_ms", "status_code", "error_code"):
            if hasattr(record, key):
                log_obj[key] = getattr(record, key)

        # Attach exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj)


def get_logger(name: str) -> logging.Logger:
    """
    Returns a module-level logger with JSON formatting.
    Log level is controlled by the LOG_LEVEL environment variable (default: INFO).

    Usage
    -----
        from api.core.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Prediction completed", extra={"claim_id": "CLM-001"})
        logger.error("[CDP-002-002] Prediction failed", extra={"error_code": "CDP-002-002"})
    """
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    logger = logging.getLogger(name)

    # Only add handlers once (avoid duplicate log entries on re-import)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)

    logger.setLevel(log_level)
    logger.propagate = False  # Prevent double-logging via root logger

    return logger


# ── Module-level default logger (for convenience imports) ─────────────────────
logger = get_logger("api")
