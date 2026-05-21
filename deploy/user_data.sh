#!/bin/bash
# ==============================================================================
# AWS EC2 Bootstrap User Data Script for Claim Denial Prevention System (CDP)
# Target OS: Ubuntu 24.04 LTS (x86_64)
# ==============================================================================

set -e

echo "=== CDP Bootstrapping: Started ==="

# 1. Update and install system dependencies
apt-get update -y
apt-get install -y python3-pip python3-venv git unzip curl jq

# 2. Install AWS CLI v2 (if not already installed)
if ! command -v aws &> /dev/null; then
    echo "Installing AWS CLI v2..."
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
    unzip awscliv2.zip
    ./aws/install
    rm -rf awscliv2.zip aws/
fi

# 3. Ensure AWS SSM Agent is active (pre-installed on standard Ubuntu AMIs)
echo "Checking AWS SSM Agent..."
snap install amazon-ssm-agent --classic || true
systemctl enable snap.amazon-ssm-agent.amazon-ssm-agent.service
systemctl start snap.amazon-ssm-agent.amazon-ssm-agent.service

# 4. Create application user and working directories
echo "Creating application user and directories..."
if ! id -u cdpapp &>/dev/null; then
    useradd -m -s /bin/bash cdpapp
fi
mkdir -p /opt/cdp/app
chown -R cdpapp:cdpapp /opt/cdp

# 5. Clone the project repository
# NOTE: Replace the URL below with your actual repository URL.
# If it is a private repo, ensure your IAM instance profile or SSM agent has
# git access or pre-configure deploy keys/tokens.
REPO_URL="https://github.com/vrd-123/Claim-denial-Project.git" # Standard placeholder
echo "Cloning repository from $REPO_URL..."
sudo -u cdpapp git clone "$REPO_URL" /opt/cdp/app || {
    echo "WARNING: Clone failed, creating fallback folder."
    # If the clone fails (e.g. repo not pushed yet), we will just let it create a dummy/empty folder
    # so that the systemd services don't completely crash at install time.
    mkdir -p /opt/cdp/app
    chown -R cdpapp:cdpapp /opt/cdp/app
}

# 6. Python Virtual Environment Setup
echo "Setting up Python virtual environment..."
sudo -u cdpapp python3 -m venv /opt/cdp/venv
sudo -u cdpapp /opt/cdp/venv/bin/pip install --upgrade pip

if [ -f "/opt/cdp/app/requirements.txt" ]; then
    echo "Installing requirements..."
    sudo -u cdpapp /opt/cdp/venv/bin/pip install -r /opt/cdp/app/requirements.txt
fi

# 7. Secure Environment Variables configuration from Secrets Manager
# We fetch DB secrets from Secrets Manager at boot time.
# Policy 'SecretsManagerReadWrite' or a custom scoped policy must be attached to the IAM role.
echo "Fetching database secrets from Secrets Manager..."
SECRET_NAME="cdp/db-credentials"
AWS_REGION="us-east-1" # Default region matching the implementation plan

# Fetch secret value
SECRET_JSON=$(aws secretsmanager get-secret-value \
  --secret-id "$SECRET_NAME" \
  --region "$AWS_REGION" \
  --query SecretString \
  --output text || echo "FAILED")

if [ "$SECRET_JSON" != "FAILED" ]; then
    DB_HOST=$(echo "$SECRET_JSON" | jq -r '.host')
    DB_USER=$(echo "$SECRET_JSON" | jq -r '.username')
    DB_PASS=$(echo "$SECRET_JSON" | jq -r '.password')
    DB_NAME=$(echo "$SECRET_JSON" | jq -r '.dbname')
else
    echo "WARNING: Secrets Manager retrieval failed. Using template environment variables."
    DB_HOST="YOUR_RDS_ENDPOINT_HERE"
    DB_USER="cdpuser"
    DB_PASS="YOUR_DB_PASSWORD"
    DB_NAME="cdp"
fi

# Generate env file securely
cat > /etc/cdp.env << ENV
API_BASE_URL=http://localhost:8000
DATABRICKS_HOST=dbc-a2e56a8a-ad64.cloud.databricks.com
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/1cb48defb84223fa
DATABRICKS_TOKEN=
SUPABASE_URL=https://iekklcobusdbvqckijqr.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlla2tsY29idXNkYnZxY2tpanFyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg5MDg0NTMsImV4cCI6MjA5NDQ4NDQ1M30.d2qx6tnkTsGjY1CSH2OPbWwaO_g5fbIgo66r5x97TLY
JWT_SECRET_KEY=ed56c064a3868be3601371081c715e7064bb8775e48b32c5422eb4ddb732b1a1
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_HOURS=24
AWS_REGION=us-east-1
ENVIRONMENT=production

# Database Settings
DB_HOST=$DB_HOST
DB_PORT=5432
DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASS
ENV

chmod 600 /etc/cdp.env
chown root:root /etc/cdp.env

# 8. Create systemd units for API and Streamlit
echo "Creating systemd services..."

# FastAPI Backend Service
cat > /etc/systemd/system/cdp-api.service << 'SVC'
[Unit]
Description=CDP FastAPI Backend
After=network.target

[Service]
User=cdpapp
WorkingDirectory=/opt/cdp/app
EnvironmentFile=/etc/cdp.env
ExecStart=/opt/cdp/venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVC

# Streamlit Frontend Service
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

# 9. Enable and start services
echo "Starting services..."
systemctl daemon-reload
systemctl enable cdp-api.service cdp-streamlit.service || true
systemctl start cdp-api.service cdp-streamlit.service || true

echo "=== CDP Bootstrapping: Completed Successfully ==="
