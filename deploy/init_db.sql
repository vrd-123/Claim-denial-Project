-- PostgreSQL DDL for Claim Denial Prevention System Database
-- Run this once on your RDS PostgreSQL instance to initialize the tables.

CREATE TABLE IF NOT EXISTS claim_history (
    id                SERIAL PRIMARY KEY,
    claim_id          TEXT NOT NULL,
    submitted_by      TEXT NOT NULL,
    submitted_at      TIMESTAMPTZ DEFAULT NOW(),
    predicted_status  TEXT,
    risk_level        TEXT,
    denial_prob       REAL,
    error_codes       TEXT,
    primary_reason    TEXT,
    recommendation    TEXT,
    ml_called         INTEGER DEFAULT 0,
    full_response     TEXT,
    billing_ratio     REAL,
    billed_amount     REAL,
    procedure_code    TEXT,
    diagnosis_code    TEXT,
    provider_id       TEXT,
    service_date      DATE,
    policy_id         TEXT,
    patient_id        TEXT
);

CREATE INDEX IF NOT EXISTS idx_claim_history_submitted_by ON claim_history(submitted_by);
CREATE INDEX IF NOT EXISTS idx_claim_history_claim_id ON claim_history(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_history_submitted_at ON claim_history(submitted_at DESC);

CREATE TABLE IF NOT EXISTS audit_trail (
    id          SERIAL PRIMARY KEY,
    claim_id    TEXT NOT NULL,
    user_email  TEXT NOT NULL,
    action      TEXT NOT NULL,
    timestamp   TIMESTAMPTZ DEFAULT NOW(),
    details     TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_trail_claim_id ON audit_trail(claim_id);
CREATE INDEX IF NOT EXISTS idx_audit_trail_user_email ON audit_trail(user_email);
