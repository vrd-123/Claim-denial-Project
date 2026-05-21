"""
api/core/config.py
─────────────────────────────────────────────────────────────────────────────
Application settings loaded from the .env file via pydantic-settings.
No secrets are hardcoded here — all values come from environment variables.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Pydantic settings model.
    All fields map directly to keys in the .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignore unknown .env keys
    )

    # ── Databricks ────────────────────────────────────────────────────────────
    databricks_host:      str = ""
    databricks_http_path: str = ""
    databricks_token:     str = ""

    # ── Model paths ───────────────────────────────────────────────────────────
    model_xgb_path: str = "models/model.xgb"
    model_lr_path:  str = "models/model.pkl"

    # ── Policy docs ───────────────────────────────────────────────────────────
    policy_docs_dir:  str = "data/policy_docs"
    claim_history_db: str = "data/claim_history.db"

    # ── API ───────────────────────────────────────────────────────────────────
    api_host:    str = "0.0.0.0"
    api_port:    int = 8000
    log_level:   str = "INFO"
    environment: str = "development"

    # ── AWS ───────────────────────────────────────────────────────────────────
    aws_s3_bucket: str = ""
    aws_region:    str = "us-east-1"
    s3_enabled:    bool = False

    # ── Feature columns (must match training notebook exactly) ────────────────
    @property
    def feature_cols(self) -> list[str]:
        return [
            "billing_ratio",
            "cost_diff",
            "high_cost_flag",
            "provider_claim_count",
            "provider_specialty_enc",
            "severity_score",
            "diag_claim_count",
            "diag_category_enc",
            "is_billed_missing",
            "is_proc_missing",
            "is_diag_missing",
            "claim_age_days",
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Returns a cached singleton Settings instance.
    Use this everywhere instead of importing Settings directly.

    Usage
    -----
        from api.core.config import get_settings
        cfg = get_settings()
        print(cfg.model_xgb_path)
    """
    return Settings()
