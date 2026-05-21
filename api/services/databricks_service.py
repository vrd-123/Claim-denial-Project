"""
api/services/databricks_service.py
─────────────────────────────────────────────────────────────────────────────
Databricks SQL service — queries Gold/Silver tables for claim lookups.
Falls back gracefully when Databricks is unavailable (dev/local mode).
"""

import os
from typing import Optional

from api.core.config import get_settings
from api.core.error_codes import ErrorCode, DatabricksException
from api.core.logger import get_logger

logger = get_logger(__name__)
cfg    = get_settings()

_QUERY_TIMEOUT = 30  # seconds


def _get_connection():
    """Create a Databricks SQL connector connection."""
    try:
        from databricks import sql as dbsql
        conn = dbsql.connect(
            server_hostname=cfg.databricks_host,
            http_path=cfg.databricks_http_path,
            access_token=cfg.databricks_token,
        )
        return conn
    except ImportError:
        raise DatabricksException(
            ErrorCode.DB_CONNECT_FAILED,
            "databricks-sql-connector not installed.",
        )
    except Exception as exc:
        logger.error("[%s] Databricks connect failed: %s", ErrorCode.DB_CONNECT_FAILED, str(exc))
        raise DatabricksException(ErrorCode.DB_CONNECT_FAILED, str(exc))


def lookup_claim(claim_id: str) -> Optional[dict]:
    """
    Look up a claim from workspace.gold.gold_claim_policy_explanations.
    Returns None if claim not found or Databricks is unavailable.
    """
    if not cfg.databricks_token or not cfg.databricks_host:
        logger.warning("Databricks not configured — skipping Gold table lookup for %s", claim_id)
        return None

    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    claim_id,
                    predicted_status,
                    denial_probability,
                    full_explanation,
                    processed_at
                FROM workspace.gold.gold_claim_policy_explanations
                WHERE claim_id = ?
                LIMIT 1
                """,
                [claim_id],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            cols = [desc[0] for desc in cursor.description]
            return dict(zip(cols, row))
    except DatabricksException:
        raise
    except Exception as exc:
        logger.error(
            "[%s] Gold table query failed for claim %s: %s",
            ErrorCode.DB_QUERY_FAILED, claim_id, str(exc),
            exc_info=True,
        )
        raise DatabricksException(ErrorCode.DB_QUERY_FAILED, f"Query failed: {exc}")
