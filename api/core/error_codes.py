"""
api/core/error_codes.py
─────────────────────────────────────────────────────────────────────────────
Centralized error-code registry for the Claim Denial Prevention system.

Format: CDP-<LAYER>-<NUMBER>
  001 = API Layer
  002 = ML Layer
  003 = RAG Layer
  004 = Agent Layer
  005 = Databricks Layer

Usage
-----
  raise ClaimDenialException(ErrorCode.MODEL_NOT_LOADED, "XGBoost file not found")

  # In FastAPI exception handler:
  except ClaimDenialException as e:
      logger.error("[%s] %s", e.code, e.detail)
      return JSONResponse({"error_code": e.code, "detail": e.detail}, status_code=e.status_code)
"""

from fastapi import HTTPException


# ── Error Code Registry ───────────────────────────────────────────────────────
class ErrorCode:
    # ── API Layer (001) ───────────────────────────────────────────────────────
    INVALID_INPUT        = "CDP-001-001"
    MISSING_CLAIM_ID     = "CDP-001-002"
    VALIDATION_ERROR     = "CDP-001-003"
    REQUEST_TIMEOUT      = "CDP-001-004"
    API_CONNECTION_ERROR = "CDP-001-005"

    # ── ML Layer (002) ───────────────────────────────────────────────────────
    MODEL_NOT_LOADED     = "CDP-002-001"
    PREDICTION_FAILED    = "CDP-002-002"
    FEATURE_MISMATCH     = "CDP-002-003"
    SCALER_NOT_LOADED    = "CDP-002-004"

    # ── RAG Layer (003) ──────────────────────────────────────────────────────
    POLICY_LOAD_FAILED   = "CDP-003-001"
    CHROMADB_ERROR       = "CDP-003-002"
    RAG_QUERY_FAILED     = "CDP-003-003"

    # ── Agent Layer (004) ────────────────────────────────────────────────────
    AGENT_BUILD_FAILED   = "CDP-004-001"
    RECOMMENDATION_FAILED = "CDP-004-002"

    # ── Databricks Layer (005) ───────────────────────────────────────────────
    DB_CONNECT_FAILED    = "CDP-005-001"
    DB_QUERY_FAILED      = "CDP-005-002"
    DB_TIMEOUT           = "CDP-005-003"


# ── Human-readable descriptions for each code ────────────────────────────────
ERROR_DESCRIPTIONS: dict[str, str] = {
    ErrorCode.INVALID_INPUT:         "The request payload contains invalid or malformed data.",
    ErrorCode.MISSING_CLAIM_ID:      "The claim_id field is required but was not provided.",
    ErrorCode.VALIDATION_ERROR:      "Request failed Pydantic schema validation.",
    ErrorCode.REQUEST_TIMEOUT:       "The request timed out before a response was generated.",
    ErrorCode.API_CONNECTION_ERROR:  "Could not connect to the downstream API service.",

    ErrorCode.MODEL_NOT_LOADED:      "The ML model file could not be loaded from disk.",
    ErrorCode.PREDICTION_FAILED:     "An error occurred during model inference.",
    ErrorCode.FEATURE_MISMATCH:      "The feature vector does not match the model's expected input.",
    ErrorCode.SCALER_NOT_LOADED:     "The feature scaler (StandardScaler) could not be loaded.",

    ErrorCode.POLICY_LOAD_FAILED:    "Failed to load policy documents from the configured directory.",
    ErrorCode.CHROMADB_ERROR:        "ChromaDB collection initialization or query failed.",
    ErrorCode.RAG_QUERY_FAILED:      "RAG retrieval query encountered an unexpected error.",

    ErrorCode.AGENT_BUILD_FAILED:    "The recommendation agent could not build a response.",
    ErrorCode.RECOMMENDATION_FAILED: "Agent failed to produce a recommendation for this claim.",

    ErrorCode.DB_CONNECT_FAILED:     "Failed to connect to the Databricks SQL warehouse.",
    ErrorCode.DB_QUERY_FAILED:       "A Databricks SQL query returned an error.",
    ErrorCode.DB_TIMEOUT:            "The Databricks query exceeded the allowed timeout.",
}


# ── Custom Exception Class ────────────────────────────────────────────────────
class ClaimDenialException(HTTPException):
    """
    Structured exception that carries a CDP error code.
    Inherits from HTTPException so FastAPI can handle it natively.

    Attributes
    ----------
    code        : str   — CDP-XXX-XXX identifier (never generic)
    detail      : str   — human-readable message for logs / API response
    status_code : int   — HTTP status code (default 500)
    """

    def __init__(
        self,
        code: str,
        detail: str | None = None,
        status_code: int = 500,
    ):
        self.code = code
        description = detail or ERROR_DESCRIPTIONS.get(code, "An unexpected error occurred.")
        super().__init__(status_code=status_code, detail=f"[{code}] {description}")

    def __str__(self) -> str:
        return f"ClaimDenialException({self.code}): {self.detail}"


# ── Layer-specific convenience sub-classes ───────────────────────────────────
class APIException(ClaimDenialException):
    """Raised for input validation and API-layer errors."""
    def __init__(self, code: str = ErrorCode.INVALID_INPUT, detail: str | None = None):
        super().__init__(code=code, detail=detail, status_code=400)


class MLException(ClaimDenialException):
    """Raised when the ML inference pipeline fails."""
    def __init__(self, code: str = ErrorCode.PREDICTION_FAILED, detail: str | None = None):
        super().__init__(code=code, detail=detail, status_code=503)


class RAGException(ClaimDenialException):
    """Raised when the RAG / ChromaDB layer fails."""
    def __init__(self, code: str = ErrorCode.CHROMADB_ERROR, detail: str | None = None):
        super().__init__(code=code, detail=detail, status_code=503)


class AgentException(ClaimDenialException):
    """Raised when the recommendation agent fails."""
    def __init__(self, code: str = ErrorCode.AGENT_BUILD_FAILED, detail: str | None = None):
        super().__init__(code=code, detail=detail, status_code=503)


class DatabricksException(ClaimDenialException):
    """Raised for Databricks connectivity or query errors."""
    def __init__(self, code: str = ErrorCode.DB_CONNECT_FAILED, detail: str | None = None):
        super().__init__(code=code, detail=detail, status_code=503)
