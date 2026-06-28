#!/bin/bash
# Provision the AWS backend for OmniSwarm: an Aurora DSQL cluster + two S3
# buckets. Requires the AWS CLI configured with credentials that can call
# dsql:* and s3:*.
#
# Usage:
#   REGION=us-east-1 \
#   MASTER_BUCKET=omniswarm-master-assets \
#   OUTPUT_BUCKET=omniswarm-localized-output \
#   ./scripts/provision_aws.sh
set -euo pipefail

REGION="${REGION:-us-east-1}"
MASTER_BUCKET="${MASTER_BUCKET:-omniswarm-master-assets}"
OUTPUT_BUCKET="${OUTPUT_BUCKET:-omniswarm-localized-output}"

echo "==> Region: $REGION"

# ── 1. Aurora DSQL cluster ────────────────────────────────────────────────
echo "==> Creating Aurora DSQL cluster..."
CLUSTER_JSON=$(aws dsql create-cluster --region "$REGION" --no-deletion-protection-enabled)
CLUSTER_ID=$(echo "$CLUSTER_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin)['identifier'])")
echo "    Cluster id: $CLUSTER_ID"

echo "==> Waiting for cluster to become ACTIVE (this can take a few minutes)..."
while true; do
  STATUS=$(aws dsql get-cluster --region "$REGION" --identifier "$CLUSTER_ID" \
    | python3 -c "import sys,json;print(json.load(sys.stdin)['status'])")
  echo "    status=$STATUS"
  [ "$STATUS" = "ACTIVE" ] && break
  sleep 15
done

DSQL_ENDPOINT="${CLUSTER_ID}.dsql.${REGION}.on.aws"
echo "    DSQL endpoint: $DSQL_ENDPOINT"

# ── 2. S3 buckets ─────────────────────────────────────────────────────────
create_bucket () {
  local name="$1"
  echo "==> Creating S3 bucket: $name"
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$name" --region "$REGION" 2>/dev/null \
      || echo "    (bucket may already exist)"
  else
    aws s3api create-bucket --bucket "$name" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION" 2>/dev/null \
      || echo "    (bucket may already exist)"
  fi
  # Enable CORS so the browser can PUT/GET via presigned URLs.
  aws s3api put-bucket-cors --bucket "$name" --cors-configuration '{
    "CORSRules": [{
      "AllowedHeaders": ["*"],
      "AllowedMethods": ["GET", "PUT", "HEAD"],
      "AllowedOrigins": ["*"],
      "ExposeHeaders": ["ETag"]
    }]
  }'
}

create_bucket "$MASTER_BUCKET"
create_bucket "$OUTPUT_BUCKET"

# ── 3. Output ─────────────────────────────────────────────────────────────
cat <<EOF

============================================================
✅ Provisioning complete. Set these env vars (Vercel + worker):

APP_AWS_REGION=$REGION
DSQL_ENDPOINT=$DSQL_ENDPOINT
S3_MASTER_BUCKET=$MASTER_BUCKET
S3_OUTPUT_BUCKET=$OUTPUT_BUCKET

Next: apply the schema in web/db/schema.sql to the DSQL cluster, e.g.
  PGSSLMODE=require psql "host=$DSQL_ENDPOINT user=admin dbname=postgres \\
    password=\$(aws dsql generate-db-connect-admin-auth-token --region $REGION --hostname $DSQL_ENDPOINT)" \\
    -f web/db/schema.sql
============================================================
EOF
