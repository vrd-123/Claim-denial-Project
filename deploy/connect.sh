#!/bin/bash
# ==============================================================================
# Helper script to establish AWS SSM Session Manager Port Forwarding Tunnel.
# Connects local port 8501 and 8000 to the private EC2 instance inside AWS VPC.
# ==============================================================================

# Exit on error
set -e

# Region definition (default ap-south-1/us-east-1)
REGION="us-east-1"

echo "Querying EC2 instance running inside cdp-vpc..."
INSTANCE_ID=$(aws ec2 describe-instances \
  --region "$REGION" \
  --filters "Name=tag:Name,Values=cdp-app" "Name=instance-state-name,Values=running" \
  --query "Reservations[0].Instances[0].InstanceId" \
  --output text)

if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" == "None" ]; then
  echo "❌ Error: Could not find a running EC2 instance with the Name tag 'cdp-app' in region '$REGION'."
  echo "Please check your EC2 dashboard or make sure your instance is running and tagged correctly."
  exit 1
fi

echo "✅ Found Running App Server: $INSTANCE_ID"
echo "--------------------------------------------------------"
echo "Starting SSM Port Forwarding Session..."
echo "Streamlit UI will be accessible locally at http://localhost:8501"
echo "FastAPI API Docs will be accessible locally at http://localhost:8000/docs"
echo "--------------------------------------------------------"
echo "Press Ctrl+C to terminate the tunnel session when done."
echo "--------------------------------------------------------"

aws ssm start-session \
  --region "$REGION" \
  --target "$INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8501"],"localPortNumber":["8501"]}'
