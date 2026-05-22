# Claim Denial Prevention System (CDP)

> An AI-powered, end-to-end claim denial prediction and remediation platform for healthcare billing analysts.  
> Built with FastAPI · Streamlit · RandomForest + XGBoost · RAG · XAI · Databricks · AWS

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.42-FF4B4B?logo=streamlit)](https://streamlit.io/)
[![Databricks](https://img.shields.io/badge/Databricks-ML%20Platform-orange?logo=databricks)](https://www.databricks.com/)
[![AWS](https://img.shields.io/badge/AWS-EC2%20%7C%20RDS%20%7C%20Secrets%20Manager-232F3E?logo=amazonaws)](https://aws.amazon.com/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## Table of Contents

- [What It Does](#what-it-does)
- [Key Features](#key-features)
- [Architecture Overview](#architecture-overview)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Local Setup](#local-setup)
  - [Environment Variables](#environment-variables)
  - [Running the API](#running-the-api)
  - [Running the UI](#running-the-ui)
- [API Reference](#api-reference)
- [Project Structure](#project-structure)
- [Deployment](#deployment)
- [Where to Get Help](#where-to-get-help)
- [Contributing](#contributing)

---

## What It Does

The **Claim Denial Prevention System (CDP)** is a production-grade AI platform that helps healthcare billing analysts predict whether a medical insurance claim will be **approved or denied** — *before it is submitted*. When a claim is at risk of denial, the system explains *why* and provides specific, actionable steps to fix it.

The end-to-end user flow is:

1. **Submit a Claim** — via the Streamlit UI (manual form, free-text paste, or batch CSV upload)
2. **AI Prediction** — a RandomForest model (with XGBoost fallback) predicts the denial probability and risk level (`LOW` / `MEDIUM` / `HIGH` / `CRITICAL`)
3. **Explainability (XAI)** — SHAP-proxy scores explain *which features* drove the prediction (e.g., overbilling, missing codes, late submission)
4. **Policy Retrieval (RAG)** — for each denial reason, relevant insurance policy text is retrieved from a ChromaDB vector store using semantic search
5. **Agent Recommendation** — a rule-based orchestrator synthesises ML + RAG outputs into one clear recommendation and next action
6. **Audit Trail** — every prediction is logged to AWS RDS PostgreSQL, viewable in the History tab

---

## Key Features

| Feature | Description |
|---|---|
| **ML Prediction** | RandomForest (primary) + XGBoost (fallback) trained on Databricks. 12-feature engineering pipeline with billing ratio, severity score, claim age, provider history, and more |
| **XAI / SHAP** | Feature-importance-weighted SHAP proxy scores translate model decisions into plain English explanations |
| **RAG Policy Retrieval** | ChromaDB vector store with `all-MiniLM-L6-v2` embeddings retrieves the most relevant insurance policy passages for each denial reason |
| **Agent Orchestrator** | Rule-based agent combines ML + RAG outputs to produce a single, prioritised recommendation and step-by-step fix |
| **Text Extraction** | GPT-4o (primary) or regex heuristics (fallback) extract structured claim fields from unstructured free-text |
| **Batch Processing** | Upload a CSV of claims and run the full pipeline across all rows with a single click |
| **Auth** | Supabase (email/password + Google OAuth) with JWT access tokens and refresh token rotation |
| **Databricks Integration** | Queries the Gold Delta Lake table to look up existing claim predictions from the data warehouse |
| **Production AWS Stack** | VPC + public/private subnets, EC2 (Ubuntu 24.04), RDS PostgreSQL, AWS Secrets Manager, SSM Agent, NAT Gateway |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      User (Billing Analyst)                      │
│                   Streamlit UI  (app.py + auth.py)               │
└──────────────────────────┬──────────────────────────────────────┘
                           │  HTTP (REST)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Backend  (api/)                        │
│  POST /predict-claim  ·  POST /batch-predict  ·  GET /health     │
│  GET /claim/{id}      ·  POST /extract        ·  GET /metrics    │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  ml_service  │  │  rag_service │  │   agent_service      │   │
│  │  (RF + XGB)  │  │  (ChromaDB)  │  │  (Rule Orchestrator) │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────────────────┘   │
│         │                 │                                       │
│  ┌──────▼───────┐  ┌──────▼──────────────────────────────────┐  │
│  │  SHAP Proxy  │  │  all-MiniLM-L6-v2 Embeddings + Policy   │  │
│  │  (XAI Layer) │  │  .txt docs (data/policy_docs/)           │  │
│  └──────────────┘  └─────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
          ┌────────────────┼──────────────────┐
          ▼                ▼                  ▼
   ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐
   │  AWS RDS    │  │  Databricks │  │  AWS Secrets     │
   │  PostgreSQL │  │  Gold Table │  │  Manager         │
   └─────────────┘  └─────────────┘  └──────────────────┘
```


---

## Getting Started

### Prerequisites

- Python 3.11+
- pip / virtualenv
- A `.env` file (see [Environment Variables](#environment-variables))
- (Optional) Databricks workspace with the Gold Delta table populated
- (Optional) OpenAI API key for GPT-4o text extraction

### Local Setup

```bash
# 1. Clone the repository
git clone https://github.com/vrd-123/Claim-denial-Project.git
cd Claim-denial-Project

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy the environment template and fill in your values
cp .env.example .env             # edit .env with your credentials
```

> **Note:** Model files (`models/model.pkl`, `models/model.xgb`) are excluded from the repo via `.gitignore` due to size. Pull them from your S3 bucket or train them using the Databricks notebooks in the `Claim-Denial-Prevention/` directory.

### Environment Variables

Create a `.env` file in the project root with the following keys:

```dotenv
# ── FastAPI / General ─────────────────────────────────────────────
API_BASE_URL=http://localhost:8000
ENVIRONMENT=development

# ── Databricks ────────────────────────────────────────────────────
DATABRICKS_HOST=<your-databricks-host>
DATABRICKS_HTTP_PATH=<your-warehouse-http-path>
DATABRICKS_TOKEN=<your-databricks-token>

# ── Supabase Auth ─────────────────────────────────────────────────
SUPABASE_URL=<your-supabase-project-url>
SUPABASE_KEY=<your-supabase-anon-key>

# ── JWT (FastAPI auth) ────────────────────────────────────────────
JWT_SECRET_KEY=<a-long-random-secret>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# ── AWS ───────────────────────────────────────────────────────────
AWS_REGION=us-east-1
AWS_S3_BUCKET=<your-s3-bucket>       # optional

# ── OpenAI (optional — for GPT-4o text extraction) ────────────────
OPENAI_API_KEY=<your-openai-key>     # if not set, regex heuristics are used

# ── Database (PostgreSQL / RDS) ───────────────────────────────────
DB_HOST=<your-rds-or-local-host>
DB_PORT=5432
DB_NAME=cdp
DB_USER=cdpuser
DB_PASSWORD=<your-db-password>
```

> **Never commit your `.env` file.** It is already listed in `.gitignore`.

### Running the API

```bash
# Start the FastAPI backend on port 8000 (with auto-reload)
uvicorn api.main:app --reload --port 8000
```

Interactive API docs are available at:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Health check**: [http://localhost:8000/health](http://localhost:8000/health)

### Running the UI

```bash
# Start the Streamlit UI (in a separate terminal)
streamlit run app.py
```

The UI will open at [http://localhost:8501](http://localhost:8501).

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/predict-claim` | Full pipeline: ML → XAI → RAG → Agent for a single claim |
| `POST` | `/batch-predict` | Run the full pipeline across a list of claims |
| `POST` | `/extract` | Extract structured claim fields from free-text using GPT-4o / regex |
| `GET` | `/claim/{id}` | Look up an existing claim from the Databricks Gold Delta table |
| `GET` | `/health` | Liveness check (reports ML + RAG load status) |
| `GET` | `/metrics` | Real-time error code frequency counts |

**Example: Single Claim Prediction**

```bash
curl -X POST http://localhost:8000/predict-claim \
  -H "Content-Type: application/json" \
  -d '{
    "claim_id": "C1001",
    "patient_id": "P123",
    "provider_id": "PROV_001",
    "procedure_code": "PROC1",
    "diagnosis_code": "D10",
    "policy_id": "POL001",
    "billed_amount": 15000.00,
    "service_date": "2025-01-15"
  }'
```

**Example Response**

```json
{
  "claim_id": "C1001",
  "predicted_status": "DENIED",
  "denial_prob": 0.84,
  "risk_level": "CRITICAL",
  "billing_ratio": 1.76,
  "expected_cost": 8500.0,
  "denial_reasons": [
    {
      "rank": 1,
      "feature": "billing_ratio",
      "explanation": "Claim billed amount is significantly higher than the benchmark expected cost.",
      "impact_score": -0.182,
      "policy_text": "Claims exceeding 150% of the benchmark cost require prior authorization...",
      "policy_source": "general_policy.txt"
    }
  ],
  "recommendation": "Review and reduce the billed amount to within 150% of the benchmark expected cost.",
  "next_action": "Compare the billed amount against the payer's fee schedule and adjust accordingly."
}
```

---

## Project Structure

```
Claim-denial-Project/
│
├── app.py                        # Streamlit UI (single-page, multi-tab)
├── auth.py                       # Supabase + Google OAuth auth helpers
├── requirements.txt              # Pinned Python dependencies
│
├── api/                          # FastAPI backend
│   ├── main.py                   # App entry point, lifespan, middleware
│   ├── core/
│   │   ├── config.py             # Pydantic settings (reads from .env)
│   │   ├── error_codes.py        # Structured CDP error codes + exceptions
│   │   └── logger.py             # Structured JSON logger
│   ├── models/
│   │   ├── request_models.py     # ClaimRequest Pydantic model
│   │   └── response_models.py    # PredictionResponse, DenialReason, etc.
│   ├── routers/
│   │   ├── predict.py            # POST /predict-claim
│   │   ├── batch_predict.py      # POST /batch-predict
│   │   ├── extract.py            # POST /extract
│   │   ├── lookup.py             # GET /claim/{id}
│   │   └── health.py             # GET /health
│   ├── services/
│   │   ├── ml_service.py         # RandomForest + XGBoost inference + SHAP proxy
│   │   ├── rag_service.py        # ChromaDB vector store + policy retrieval
│   │   ├── agent_service.py      # Rule-based orchestrator (SHAP + RAG → recommendation)
│   │   ├── llm_service.py        # GPT-4o / regex field extraction
│   │   ├── databricks_service.py # Databricks SQL connector (Gold table lookup)
│   │   ├── ocr_service.py        # OCR helpers
│   │   └── validation_service.py # Input validation
│   └── middleware/
│       └── logging_middleware.py # Structured JSON request logging
│
├── models/                       # Trained model artifacts (gitignored — pull from S3)
│   ├── model.pkl                 # RandomForest (primary)
│   ├── model.xgb                 # XGBoost (fallback)
│   └── all-MiniLM-L6-v2/        # Sentence transformer for RAG embeddings
│
├── data/                         # Reference data (Medallion architecture)
│   ├── bronze/                   # Raw ingested data
│   ├── silver/                   # Cleaned / feature-engineered data
│   └── gold/                     # Final training-ready tables
│
├── deploy/                       # AWS infrastructure scripts
│   ├── user_data.sh              # EC2 bootstrap script (Ubuntu 24.04)
│   ├── connect.sh                # SSH/SSM connection helper
│   ├── update.sh                 # Pull latest code + restart services on EC2
│   └── init_db.sql               # PostgreSQL DDL (claim_history + audit_trail)
│
├── Claim-Denial-Prevention/      # Databricks notebooks
│   ├── bronze/                   # Data ingestion notebooks
│   ├── silver/                   # Feature engineering notebooks
│   └── gold/                     # ML training, XAI, RAG notebooks
│
└── architecture/                 # Documentation
    ├── architecture_documentation.md   # Full module-by-module technical writeup
    └── generate_diagram.py             # Architecture diagram generator
```

---

## Deployment

The production system runs on **AWS** inside a private VPC. The EC2 instance is bootstrapped automatically using [`deploy/user_data.sh`](deploy/user_data.sh).

**High-level AWS setup:**

1. Create a VPC (`10.0.0.0/16`) with a public subnet (NAT Gateway) and a private app subnet (EC2)
2. Launch an EC2 instance (Ubuntu 24.04, `t3.medium` or larger) in the private subnet
3. Attach an IAM role with `AmazonSSMManagedInstanceCore` + `SecretsManagerReadOnly` policies
4. Store all secrets in AWS Secrets Manager under `cdp/db-credentials` (including DB credentials, Databricks token, Supabase key, JWT secret)
5. Provision an RDS PostgreSQL instance in a private DB subnet; run [`deploy/init_db.sql`](deploy/init_db.sql) to create tables
6. The EC2 bootstrap script (`user_data.sh`) clones this repo, installs dependencies, and launches both FastAPI (`uvicorn`) and Streamlit as `systemd` services

**Updating code on EC2:**

```bash
# From your local machine via SSM
./deploy/connect.sh

# On the EC2 instance
./deploy/update.sh
```

For a detailed step-by-step AWS provisioning guide, see [`architecture/architecture_documentation.md`](architecture/architecture_documentation.md).

---

## Where to Get Help

- **Architecture Docs**: [`architecture/architecture_documentation.md`](architecture/architecture_documentation.md) — detailed explanation of every module, design decision, and AWS component
- **API Docs (local)**: [http://localhost:8000/docs](http://localhost:8000/docs) — interactive Swagger UI once the API is running
- **Databricks Docs**: [docs.databricks.com](https://docs.databricks.com)
- **FastAPI Docs**: [fastapi.tiangolo.com](https://fastapi.tiangolo.com)
- **Streamlit Docs**: [docs.streamlit.io](https://docs.streamlit.io)
- **ChromaDB Docs**: [docs.trychroma.com](https://docs.trychroma.com)
- **Issues**: Open a GitHub Issue for bug reports or feature requests

---

## Contributing

1. **Fork** the repository and create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Make your changes, ensuring all secrets remain in `.env` and are never committed
3. Test locally with both the FastAPI backend and the Streamlit UI
4. Open a **Pull Request** against `main` with a clear description of the changes

**Code style guidelines:**
- Follow PEP 8 for Python code
- Keep service functions focused and independently testable
- All new API endpoints must include Pydantic request/response models
- Structured logging is mandatory — use `get_logger(__name__)` from `api/core/logger.py`
- Never hardcode secrets, thresholds, or model paths — use `api/core/config.py` settings

---

**Maintained by:** [vrd-123](https://github.com/vrd-123)
