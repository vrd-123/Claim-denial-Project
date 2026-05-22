# Claim Denial Prevention (CDP) System Architecture

This document provides a comprehensive, production-grade overview of the Claim Denial Prevention (CDP) system. The system is designed to assist Billing Analysts in identifying, analyzing, and preventing healthcare claim denials *before* they are submitted to payers. 

## 1. System Overview & User Persona

**User Persona:** The primary user is a **Billing Analyst** or Medical Coder working at a healthcare provider (hospital, clinic). Their goal is to ensure claims are clean, compliant with payer policies, and accurately priced to minimize rejection rates and maximize revenue realization.

**End-to-End User Flow:**
1. **Authentication:** The Billing Analyst logs into the Streamlit UI using their credentials (managed by Supabase/Google OAuth).
2. **Claim Input:** The user uploads a raw medical claim document or manually enters claim details (Procedure Code, Diagnosis Code, Billed Amount, etc.).
3. **Extraction:** If a document is uploaded, the system uses an LLM (OpenAI GPT-4o) or regex heuristics to extract the structured fields.
4. **Prediction & Analysis:** 
   - The FastAPI backend processes the claim.
   - The **ML Model** predicts the probability of denial and calculates SHAP proxy scores to identify the key risk drivers (e.g., missing diagnosis, anomalous billing ratio).
   - The **RAG Engine** retrieves relevant medical policy clauses based on the top risk drivers.
   - The **Agent Orchestrator** synthesizes the ML and RAG outputs into actionable recommendations (e.g., "Add ICD-10-CM code before resubmission").
5. **Review & Action:** The Billing Analyst reviews the AI recommendations, adjusts the claim details in the UI, and finalizes the claim for submission.
6. **Audit & History:** All actions, predictions, and edits are logged in the PostgreSQL database for audit trails and future model retraining.

---

## 2. Core Modules in Detail

### 2.1 User Interface (UI) - Streamlit
- **Why Streamlit?** Allows for rapid development of data-heavy, interactive dashboards without requiring a separate complex frontend framework (like React). It natively supports Python, making integration with the ML backend seamless.
- **Features:** 
  - Dynamic forms for claim input and document upload.
  - Interactive visualizations (SHAP force plots, historical trend charts).
  - Session state management for authentication and multi-step workflows.
  - Sidebar for user profile and navigation.

### 2.2 Authentication & Authorization (Supabase & JWT)
- **Supabase:** Acts as the primary Identity Provider (IdP). Handles user registration, password resets, and Google OAuth integration.
- **Why Supabase?** Provides secure, out-of-the-box authentication flows and OAuth integrations, reducing the overhead of building a custom auth service.
- **JWT (JSON Web Tokens):** Used for securing API endpoints. Once authenticated via Supabase, the backend verifies the user's session. The system uses specific secret keys and the `HS256` algorithm to sign and validate tokens.

### 2.3 Backend API - FastAPI
- **Why FastAPI?** Extremely fast, natively asynchronous, and provides automatic OpenAPI (Swagger) documentation. It's the industry standard for serving Python ML models.
- **Endpoints:**
  - `POST /predict-claim`: The core orchestrator endpoint that chains ML, RAG, and Agent logic.
  - `POST /predict-batch`: Handles batch processing of up to 200 claims asynchronously.
  - `GET /claim/{id}`: Looks up historical claim data from Databricks Gold tables.
  - `GET /health` & `/metrics`: Used by AWS ELB for health checks and operational monitoring.
- **Middleware:** Implements strict request logging. Every request is logged as a structured JSON line containing timestamps, response times, and status codes. Crucially, PHI (Protected Health Information) is stripped from logs to maintain HIPAA compliance.

### 2.4 Machine Learning (ML) Models
- **Primary Model (RandomForest):** A tuned Random Forest Classifier (`model.pkl`) acts as the primary inference engine. It proved to have the best ROC-AUC during training.
- **Fallback Model (XGBoost):** An XGBoost model (`model.xgb`) is loaded as a fallback in case the primary model fails to load.
- **Feature Engineering:** Features include `billing_ratio`, `cost_diff`, `high_cost_flag`, `provider_claim_count`, `severity_score`, and missing field flags. These are computed dynamically using reference lookup tables (loaded from raw CSVs into memory at startup) rather than hardcoded magic numbers.
- **Explainability (XAI):** Instead of running computationally heavy SHAP libraries at inference time, the system computes a **SHAP proxy**. It calculates feature impact scores weighted by the Random Forest's actual `feature_importances_`. This ensures the explanations exactly reflect what the model cares about most.

### 2.5 Retrieval-Augmented Generation (RAG)
- **Purpose:** To provide concrete evidence for denial risks by citing actual insurance policy documents.
- **Architecture:** 
  - **ChromaDB:** An ephemeral, in-memory vector database initialized at startup.
  - **Embeddings:** Uses `all-MiniLM-L6-v2` (via HuggingFace `sentence-transformers`) to vectorize policy text chunks. A custom fallback `DummyEmbeddingFunction` is implemented to bypass offline HuggingFace errors by using exact phrase matching.
- **Workflow:** When the ML model identifies a top denial driver (e.g., "policy_violation"), the RAG service translates this into a human-readable query and searches ChromaDB for the top-2 most relevant policy clauses to present to the user.

### 2.6 Agent Orchestrator (Rule Engine)
- **Role:** Acts as the "medical billing expert" that bridges the gap between raw ML probabilities and actionable human steps.
- **Logic:** It takes the top denial drivers identified by the ML model (via SHAP scores) and maps them to specific, actionable recommendations using a predefined rule engine (`RECOMMENDATION_MAP`). 
- **Example:** If the ML model flags `is_diag_missing` as the top negative driver, the Agent outputs: *Recommendation:* "Add a valid ICD-10-CM diagnosis code." *Next Action:* "Obtain the diagnosis from the treating physician."

### 2.7 Extraction Service (OpenAI API / Heuristics)
- **Primary:** Uses OpenAI's `gpt-4o` to extract structured fields (Claim ID, Patient ID, Billed Amount, Dates) from raw, unstructured clinical text.
- **Fallback:** If the API key is missing or the call fails, it falls back to a robust Regex Heuristics engine that extracts data locally without external dependencies.

### 2.8 Databricks Integration
- **Role:** Acts as the enterprise data warehouse and single source of truth for historical, processed claims.
- **Usage:** The FastAPI backend queries Databricks SQL warehouses (specifically Gold tables like `workspace.gold.gold_claim_policy_explanations`) to retrieve historical claim contexts and past adjudication results.

---

## 3. AWS Infrastructure & Networking

The system is designed with strict security boundaries, ensuring no compute resources are directly exposed to the public internet.

### 3.1 Virtual Private Cloud (VPC) & Subnets
- **VPC (`cdp-vpc`):** A logically isolated network (`10.0.0.0/16`) hosting all application resources.
- **Public Subnet (`10.0.1.0/24`):** Contains the NAT Gateway. It has a route to the Internet Gateway (IGW).
- **Private App Subnet (`10.0.2.0/24`):** Hosts the EC2 instance. It has no public IP and routes outbound traffic through the NAT Gateway.
- **Private Database Subnet (`10.0.3.0/24`):** Hosts the RDS PostgreSQL database. Isolated entirely from the internet.

### 3.2 Compute (EC2) & Tunneling (SSM)
- **EC2 Instance:** An Ubuntu `t3.medium` instance running both the FastAPI backend and the Streamlit UI as `systemd` services.
- **AWS Systems Manager (SSM):** Because the EC2 has no public IP and port 22 (SSH) is closed, access is achieved exclusively via SSM Session Manager. Developers tunnel ports (e.g., 8501 for UI, 8000 for API) securely from their local machines to the EC2 instance using the AWS CLI.

### 3.3 Database (RDS PostgreSQL)
- **RDS Instance:** A managed PostgreSQL database (`db.t3.micro`) replacing the local SQLite file for production readiness.
- **Security Group:** Only allows inbound traffic on port 5432 from the EC2 Security Group.

### 3.4 Security & Secrets Management
- **NAT Gateway:** Allows the private EC2 instance to securely download packages (pip, apt) and communicate with external APIs (Databricks, Supabase, OpenAI) without exposing itself to inbound internet traffic.
- **AWS Secrets Manager:** Database credentials and API keys are stored securely in Secrets Manager. The EC2 instance retrieves them dynamically at boot time via its IAM Instance Profile (`AmazonSSMManagedInstanceCore` + SecretsManager policies), preventing hardcoded secrets in the codebase.

---

## 4. Current Deployment Status & Next Steps

### Current Status: Partially Deployed / Local Hybrid
Based on the provided context, the project is currently in a **Local/Hybrid state transitioning to Production**. 
- The Streamlit UI and FastAPI backend have been developed and run successfully locally using SQLite.
- The AWS infrastructure (VPC, EC2, RDS) deployment scripts and architecture designs (`deploy/user_data.sh`, `deploy/init_db.sql`) are prepared but **require execution by the AWS administrator**.

### Do I need to deploy the project now?
**Yes, if you want the application to be accessible in a production environment.** Currently, it is running locally. To move to production, the AWS deployment steps outlined in your `cdp_aws_vpc_deployment.md` guide must be executed.

### Next Steps for Productionization:

1. **Execute AWS Infrastructure Provisioning:**
   - Create the VPC, Subnets, IGW, and NAT Gateway via AWS Console or Terraform/CloudFormation.
   - Provision the RDS PostgreSQL instance in the private DB subnet.
   - Create the Secrets Manager entry `cdp/db-credentials`.
2. **Launch & Bootstrap EC2:**
   - Launch the EC2 instance using the provided `user_data.sh` script to automate repository cloning, environment setup, and systemd service creation.
3. **Database Migration:**
   - Connect to the RDS instance via SSM port-forwarding and run the `init_db.sql` script to create the required Postgres schemas.
4. **CI/CD Pipeline (Recommended):**
   - Implement GitHub Actions or AWS CodePipeline to automate code deployments to the EC2 instance, replacing the manual `git pull` process over SSM.
5. **Monitoring & Logging:**
   - Configure AWS CloudWatch agent on the EC2 instance to export the FastAPI JSON logs for centralized monitoring and alerting on error metrics.
6. **Load Balancing (Future Scaling):**
   - Once multiple users require access, introduce an Application Load Balancer (ALB) with an ACM SSL Certificate in the public subnet, routing traffic to multiple EC2 instances in an Auto Scaling Group in the private subnets.
