#!/bin/bash
# ==============================================================================
# Code deployment update script. Run this on your local machine to trigger
# git pull, requirements installation, and service restarts on the EC2 instance.
# ==============================================================================

# Exit on error
set -e

REGION="us-east-1"

echo "Querying EC2 instance running inside cdp-vpc..."
INSTANCE_ID=$(aws ec2 describe-instances \
  --region "$REGION" \
  --filters "Name=tag:Name,Values=cdp-app" "Name=instance-state-name,Values=running" \
  --query "Reservations[0].Instances[0].InstanceId" \
  --output text)

if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" == "None" ]; then
  echo "❌ Error: Could not find a running EC2 instance with Name 'cdp-app'."
  exit 1
fi

echo "✅ Found Running App Server: $INSTANCE_ID"
echo "Sending update commands via AWS SSM Run Command..."

COMMAND="cd /opt/cdp/app && \
sudo -u cdpapp git pull origin main && \
sudo -u cdpapp /opt/cdp/venv/bin/pip install -r requirements.txt && \
sudo systemctl restart cdp-api.service cdp-streamlit.service && \
echo 'Update completed successfully!'"

aws ssm send-command \
  --region "$REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[\"$COMMAND\"]" \
  --comment "Updating CDP application source and restarting services"

echo "✅ Update command dispatched successfully!"
echo "You can check status in AWS Console under Systems Manager -> Run Command."
