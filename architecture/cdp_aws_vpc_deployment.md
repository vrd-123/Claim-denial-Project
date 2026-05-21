# CDP Deployment Guide — AWS VPC (No Public IPs)

**Project:** Claim Denial Prevention System  
**Stack:** Streamlit · FastAPI · SQLite → RDS PostgreSQL · Supabase Auth (cloud) · Databricks  
**Deployment target:** AWS VPC, private subnets only, no public IP on any compute resource  
**Access model:** Solo developer via AWS SSM Session Manager (no VPN server required)

---

## 0. What You Are Building

```
Your laptop
    │
    │  AWS SSM Session Manager tunnel (port-forward, no SSH keys needed)
    ▼
┌─────────────────────────────────────────────────────────┐
│  AWS VPC (e.g. 10.0.0.0/16)                            │
│                                                         │
│  Private Subnet A (10.0.1.0/24)                        │
│  ┌────────────────────────┐                             │
│  │  EC2 — App Server      │  ← no public IP            │
│  │  · Streamlit :8501     │                             │
│  │  · FastAPI   :8000     │                             │
│  └────────┬───────────────┘                             │
│           │ private connection                          │
│  Private Subnet B (10.0.2.0/24)                        │
│  ┌────────────────────────┐                             │
│  │  RDS PostgreSQL        │  ← no public IP            │
│  │  claim_history DB      │                             │
│  └────────────────────────┘                             │
│                                                         │
│  NAT Gateway (in a public subnet)                       │
│  └── allows EC2 to call outbound: Supabase, Databricks  │
└─────────────────────────────────────────────────────────┘
```

Nothing in this architecture has a public IP. You reach the app by tunnelling through AWS Systems Manager — no bastion host, no open port 22, no inbound security group rules on the EC2.

---

## 1. Prerequisites

Install these on your local machine before starting:

```bash
# AWS CLI v2
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip && sudo ./aws/install

# SSM Session Manager plugin (lets you tunnel ports via SSM)
# Mac:
brew install --cask session-manager-plugin
# Linux: download from https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html

# Configure your AWS credentials
aws configure
# Enter: Access Key ID, Secret Access Key, region (e.g. ap-south-1 for Mumbai), output format: json
```

---

## 2. VPC Setup

### 2.1 Create the VPC

In the AWS Console → VPC → Create VPC:

| Field | Value |
|---|---|
| Name | `cdp-vpc` |
| IPv4 CIDR | `10.0.0.0/16` |
| Tenancy | Default |

### 2.2 Create Subnets

You need at least three subnets across two Availability Zones (RDS requires two AZs even for a single instance):

| Name | CIDR | AZ | Type |
|---|---|---|---|
| `cdp-public-1a` | `10.0.0.0/24` | `ap-south-1a` | Public (for NAT Gateway only) |
| `cdp-private-app-1a` | `10.0.1.0/24` | `ap-south-1a` | Private (EC2 lives here) |
| `cdp-private-db-1b` | `10.0.2.0/24` | `ap-south-1b` | Private (RDS lives here) |

**Do not enable "Auto-assign public IPv4" on any private subnet.**

### 2.3 Internet Gateway + NAT Gateway

The EC2 needs to make outbound calls to Supabase and Databricks. It does this through a NAT Gateway (which has a public IP) — the EC2 itself still has no public IP.

```
Internet Gateway → attach to cdp-vpc
NAT Gateway      → create in cdp-public-1a, allocate an Elastic IP
```

### 2.4 Route Tables

**Public route table** (attached to `cdp-public-1a`):
```
Destination     Target
0.0.0.0/0       igw-xxxxxxxx   ← Internet Gateway
```

**Private route table** (attached to both private subnets):
```
Destination     Target
0.0.0.0/0       nat-xxxxxxxx   ← NAT Gateway (outbound only)
10.0.0.0/16     local
```

---

## 3. Security Groups

Create three security groups inside `cdp-vpc`. The critical point: **no inbound rule from 0.0.0.0/0 anywhere**.

### SG 1 — `cdp-ec2-sg` (App server)

| Direction | Protocol | Port | Source | Purpose |
|---|---|---|---|---|
| Inbound | TCP | 8501 | `cdp-ec2-sg` (self) | Streamlit health checks |
| Inbound | TCP | 8000 | `cdp-ec2-sg` (self) | FastAPI internal calls |
| Outbound | All | All | 0.0.0.0/0 | Supabase, Databricks, pip installs |

> There is intentionally no inbound rule for your laptop. You reach the EC2 via SSM tunnelling — SSM uses outbound HTTPS from the EC2 to AWS endpoints, so no inbound port needs to be open at all.

### SG 2 — `cdp-rds-sg` (Database)

| Direction | Protocol | Port | Source | Purpose |
|---|---|---|---|---|
| Inbound | TCP | 5432 | `cdp-ec2-sg` | Postgres from app server only |
| Outbound | None | — | — | RDS does not need outbound |

### SG 3 — `cdp-ssm-sg` (VPC Endpoints — if using interface endpoints)

Only needed if you use SSM interface endpoints instead of the NAT Gateway for SSM traffic. Can be skipped for now — the NAT Gateway handles SSM traffic too.

---

## 4. IAM Role for EC2

The EC2 must have an IAM role that allows SSM to manage it (this is how you connect to it without SSH keys or a public IP).

### 4.1 Create the role

IAM → Roles → Create role:

- Trusted entity: **EC2**
- Attach policies:
  - `AmazonSSMManagedInstanceCore` ← required for SSM Session Manager
  - `AmazonRDSFullAccess` ← if you want the EC2 to manage RDS (optional, can be scoped down)

Name the role `cdp-ec2-role`.

### 4.2 What AmazonSSMManagedInstanceCore does

It allows the EC2 instance to register itself with AWS Systems Manager and accept tunnelled sessions from your laptop. No port 22, no SSH key pair, no inbound security group rules needed.

---

## 5. EC2 Instance

### 5.1 Launch settings

| Field | Value |
|---|---|
| AMI | Ubuntu 24.04 LTS (latest) |
| Instance type | `t3.medium` (2 vCPU, 4 GB RAM — enough for Streamlit + FastAPI) |
| Key pair | **No key pair** (you use SSM, not SSH) |
| VPC | `cdp-vpc` |
| Subnet | `cdp-private-app-1a` |
| Auto-assign public IP | **Disabled** |
| Security group | `cdp-ec2-sg` |
| IAM instance profile | `cdp-ec2-role` |
| Storage | 20 GB gp3 |

### 5.2 User data script (runs once on first boot)

Paste this into the "User data" field when launching. It installs everything your app needs:

```bash
#!/bin/bash
set -e

# System packages
apt-get update -y
apt-get install -y python3-pip python3-venv git unzip

# Install AWS SSM agent (usually pre-installed on Ubuntu AMIs, this ensures it)
snap install amazon-ssm-agent --classic
systemctl enable snap.amazon-ssm-agent.amazon-ssm-agent.service
systemctl start snap.amazon-ssm-agent.amazon-ssm-agent.service

# Create app user and directory
useradd -m -s /bin/bash cdpapp
mkdir -p /opt/cdp
chown cdpapp:cdpapp /opt/cdp

# Clone your project (replace with your actual repo URL)
# If private repo: add a deploy key or use CodeCommit
sudo -u cdpapp git clone https://github.com/YOUR_ORG/YOUR_REPO.git /opt/cdp/app

# Python virtual environment
sudo -u cdpapp python3 -m venv /opt/cdp/venv
sudo -u cdpapp /opt/cdp/venv/bin/pip install --upgrade pip
sudo -u cdpapp /opt/cdp/venv/bin/pip install -r /opt/cdp/app/requirements.txt

# Environment variables — populated from Secrets Manager in Section 6
cat > /etc/cdp.env << 'ENV'
API_BASE_URL=http://localhost:8000
DATABRICKS_HOST=<your-databricks-host>
DATABRICKS_HTTP_PATH=<your-http-path>
SUPABASE_URL=<your-supabase-url>
SUPABASE_ANON_KEY=<your-supabase-anon-key>
DB_HOST=<rds-endpoint-from-section-6>
DB_PORT=5432
DB_NAME=cdp
DB_USER=cdpuser
DB_PASSWORD=<from-secrets-manager>
ENV
chmod 600 /etc/cdp.env

# Systemd service — FastAPI
cat > /etc/systemd/system/cdp-api.service << 'SVC'
[Unit]
Description=CDP FastAPI Backend
After=network.target

[Service]
User=cdpapp
WorkingDirectory=/opt/cdp/app
EnvironmentFile=/etc/cdp.env
ExecStart=/opt/cdp/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVC

# Systemd service — Streamlit
cat > /etc/systemd/system/cdp-streamlit.service << 'SVC'
[Unit]
Description=CDP Streamlit UI
After=cdp-api.service

[Service]
User=cdpapp
WorkingDirectory=/opt/cdp/app
EnvironmentFile=/etc/cdp.env
ExecStart=/opt/cdp/venv/bin/streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVC

systemctl daemon-reload
systemctl enable cdp-api cdp-streamlit
systemctl start cdp-api cdp-streamlit
```

> **Note:** Both services bind to `127.0.0.1`, not `0.0.0.0`. This means they are not reachable even from within the VPC directly — only via your SSM tunnel from your laptop. This is intentional.

---

## 6. RDS PostgreSQL (replacing SQLite)

### 6.1 Create a DB Subnet Group

RDS → Subnet Groups → Create:

- Name: `cdp-db-subnet-group`
- VPC: `cdp-vpc`
- Subnets: `cdp-private-app-1a` and `cdp-private-db-1b` (must be two AZs)

### 6.2 Launch RDS

| Field | Value |
|---|---|
| Engine | PostgreSQL 16 |
| Template | Free tier (or Dev/Test for slightly more resources) |
| DB identifier | `cdp-db` |
| Master username | `cdpuser` |
| Master password | Generate and save — store in Secrets Manager (see 6.3) |
| Instance class | `db.t3.micro` (sufficient for this workload) |
| Storage | 20 GB gp2, no auto-scaling needed yet |
| VPC | `cdp-vpc` |
| Subnet group | `cdp-db-subnet-group` |
| Public access | **No** |
| VPC security group | `cdp-rds-sg` |
| Database name | `cdp` |

After creation, note the endpoint — it looks like `cdp-db.xxxxxx.ap-south-1.rds.amazonaws.com`. This goes into `/etc/cdp.env` as `DB_HOST`.

### 6.3 Store credentials in AWS Secrets Manager

Never put DB passwords in environment files on disk in plaintext. Store them in Secrets Manager and pull them at startup instead:

```bash
aws secretsmanager create-secret \
  --name cdp/db-credentials \
  --secret-string '{"username":"cdpuser","password":"YOUR_PASSWORD","host":"cdp-db.xxxx.rds.amazonaws.com","dbname":"cdp"}'
```

Then in your user data script, replace the plaintext env vars with a call to fetch from Secrets Manager:

```bash
# Fetch DB credentials from Secrets Manager at startup
SECRET=$(aws secretsmanager get-secret-value \
  --secret-id cdp/db-credentials \
  --query SecretString --output text)

DB_HOST=$(echo $SECRET | python3 -c "import sys,json; print(json.load(sys.stdin)['host'])")
DB_PASSWORD=$(echo $SECRET | python3 -c "import sys,json; print(json.load(sys.stdin)['password'])")

# Write to env file
echo "DB_HOST=$DB_HOST" >> /etc/cdp.env
echo "DB_PASSWORD=$DB_PASSWORD" >> /etc/cdp.env
```

Add `SecretsManagerReadWrite` or a scoped `secretsmanager:GetSecretValue` policy to `cdp-ec2-role`.

### 6.4 Migrate your SQLite schema to Postgres

On the EC2, after it is running, run this once to create the `claim_history` table in Postgres:

```sql
-- Connect: psql -h $DB_HOST -U cdpuser -d cdp
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

CREATE INDEX idx_claim_history_submitted_by ON claim_history(submitted_by);
CREATE INDEX idx_claim_history_claim_id ON claim_history(claim_id);
CREATE INDEX idx_claim_history_submitted_at ON claim_history(submitted_at DESC);
```

### 6.5 Update your app to use psycopg2 instead of sqlite3

In `app.py` and anywhere else `sqlite3.connect(...)` is called, replace the connection with:

```python
import psycopg2
import psycopg2.extras
import os

def _get_db_conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ.get("DB_NAME", "cdp"),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )
```

Replace `?` placeholders in all SQL with `%s` (psycopg2 uses `%s`, not `?`):

```python
# SQLite style — change this:
cur.execute("SELECT * FROM claim_history WHERE claim_id = ?", (claim_id,))

# Postgres style — to this:
cur.execute("SELECT * FROM claim_history WHERE claim_id = %s", (claim_id,))
```

Add `psycopg2-binary` to your `requirements.txt`.

---

## 7. Connecting to the App — SSM Port Forwarding

This is how you open the app in your browser from your laptop, with no public IP on the EC2.

### 7.1 Find the EC2 instance ID

```bash
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=cdp-app" \
  --query "Reservations[0].Instances[0].InstanceId" \
  --output text
# Returns something like: i-0abc1234def56789
```

### 7.2 Open the tunnels

Run both commands in separate terminals:

```bash
# Terminal 1 — tunnel Streamlit
aws ssm start-session \
  --target i-0abc1234def56789 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8501"],"localPortNumber":["8501"]}'

# Terminal 2 — tunnel FastAPI (optional, useful for debugging)
aws ssm start-session \
  --target i-0abc1234def56789 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8000"],"localPortNumber":["8000"]}'
```

Now open `http://localhost:8501` in your browser. You are talking to the Streamlit app running inside the private VPC with no public IP exposed anywhere.

### 7.3 Make the tunnel command easier

Add this to your `~/.bashrc` or `~/.zshrc`:

```bash
alias cdp-connect='aws ssm start-session \
  --target i-0abc1234def56789 \
  --document-name AWS-StartPortForwardingSession \
  --parameters "{\"portNumber\":[\"8501\"],\"localPortNumber\":[\"8501\"]}"'
```

Then just run `cdp-connect` to open the tunnel.

---

## 8. Supabase Auth — What Changes (Almost Nothing)

Supabase cloud (`cloud.supabase.com`) sits outside your VPC. Your EC2 calls it outbound over HTTPS via the NAT Gateway. From your app's perspective, nothing changes:

- `SUPABASE_URL` and `SUPABASE_ANON_KEY` stay in your env file exactly as they are locally.
- The Supabase dashboard, user management, and RLS policies are all unchanged.
- The only thing to verify: Supabase does not have an IP allowlist that would block the NAT Gateway's Elastic IP. If it does, add the NAT Gateway EIP to the Supabase allowed IPs.

**Do not attempt to self-host Supabase inside the VPC** for this project. The operational cost far outweighs any benefit at this scale.

---

## 9. Databricks — What Changes (Nothing)

Same pattern as Supabase. Your FastAPI backend calls the Databricks serving endpoint outbound over HTTPS via the NAT Gateway. `DATABRICKS_HOST`, `DATABRICKS_HTTP_PATH`, and `DATABRICKS_TOKEN` go into the env file as-is. Databricks handles its own auth.

If Databricks has IP allowlisting, add the NAT Gateway Elastic IP there too.

---

## 10. Updating the App After Deployment

Since there's no CI/CD pipeline, the update flow is:

### 10.1 SSM into the EC2 as a shell (not a port-forward)

```bash
aws ssm start-session --target i-0abc1234def56789
# This opens a bash shell on the EC2
```

### 10.2 Pull latest code and restart services

```bash
# On the EC2 via SSM shell
cd /opt/cdp/app
sudo -u cdpapp git pull origin main

# If requirements changed:
sudo -u cdpapp /opt/cdp/venv/bin/pip install -r requirements.txt

# Restart both services
sudo systemctl restart cdp-api cdp-streamlit

# Verify they came back up
sudo systemctl status cdp-api cdp-streamlit
```

### 10.3 Check logs if something breaks

```bash
sudo journalctl -u cdp-streamlit -n 100 --no-pager
sudo journalctl -u cdp-api -n 100 --no-pager
```

---

## 11. Step-by-Step Execution Order

Do these in order. Each step depends on the previous one.

```
[ ] Step 1   Create VPC (cdp-vpc, 10.0.0.0/16)
[ ] Step 2   Create 3 subnets (1 public, 2 private)
[ ] Step 3   Create Internet Gateway, attach to VPC
[ ] Step 4   Create NAT Gateway in public subnet, allocate EIP
[ ] Step 5   Create route tables and associate subnets
[ ] Step 6   Create 2 security groups (cdp-ec2-sg, cdp-rds-sg)
[ ] Step 7   Create IAM role cdp-ec2-role with AmazonSSMManagedInstanceCore
[ ] Step 8   Store DB credentials in Secrets Manager
[ ] Step 9   Create RDS Postgres (cdp-db) in private subnet
[ ] Step 10  Launch EC2 in private subnet with user-data script
             (wait ~5 minutes for user-data to complete)
[ ] Step 11  Verify SSM connectivity: aws ssm start-session --target i-xxxx
[ ] Step 12  Run DB migration SQL on RDS via SSM shell
[ ] Step 13  Update app.py connection strings (sqlite3 → psycopg2)
[ ] Step 14  Push updated code to git repo
[ ] Step 15  On EC2 via SSM: git pull, pip install, restart services
[ ] Step 16  Open SSM port-forward tunnel to :8501
[ ] Step 17  Open http://localhost:8501 — app should be live
```

---

## 12. What This Architecture Does NOT Include (and When to Add It)

| Feature | Why excluded now | When to add it |
|---|---|---|
| Application Load Balancer | No external users, only you via SSM | When external users or a custom domain are needed |
| HTTPS / ACM certificate | No ALB, no public endpoint | Same time as ALB |
| Multi-AZ RDS | Cost; single instance is fine for one user | When the system goes to production with real patient data |
| Auto Scaling Group | Single EC2 is fine for one user | When concurrent users exceed ~10 |
| CI/CD (GitHub Actions) | Manual git pull is simpler for solo dev | When update frequency increases or team grows |
| WAF | No public endpoint to protect | When ALB is added |
| VPC Flow Logs | Useful but not critical right now | When you want network audit trails for compliance |
| AWS Client VPN | SSM tunnel is simpler and cheaper | Only needed if multiple developers need simultaneous access |

---

## 13. Estimated Monthly Cost (ap-south-1, Mumbai)

| Resource | Type | ~Monthly cost |
|---|---|---|
| EC2 | t3.medium, on-demand | ~$30 |
| RDS | db.t3.micro, single-AZ | ~$15 |
| NAT Gateway | data processing + hourly | ~$35 |
| Secrets Manager | 1 secret | ~$0.40 |
| SSM Session Manager | free for EC2 | $0 |
| **Total** | | **~$80–90 / month** |

> The NAT Gateway dominates the cost. If budget is a concern, the cheapest alternative is to put a single `t3.nano` EC2 as a "NAT instance" instead of using the managed NAT Gateway. However, the managed NAT Gateway is significantly more reliable and the right choice for anything that matters.
