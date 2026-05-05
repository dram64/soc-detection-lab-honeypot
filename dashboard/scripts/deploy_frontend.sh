#!/usr/bin/env bash
###############################################################################
# Build the production dashboard bundle and deploy it to S3 + invalidate
# CloudFront.
#
# Reference: PROJECT_PLAN.md §11 Phase 8.
#
# Reads the bucket name and distribution id from terraform outputs in
# infrastructure/terraform/environments/dev (single-environment v1).
#
# Usage (from repo root or anywhere):
#   ./dashboard/scripts/deploy_frontend.sh
#
# Required env (or auto-discovered):
#   VITE_API_BASE_URL  — API GW invoke URL the frontend hits at runtime.
#                        If unset, read from terraform output api_endpoint.
###############################################################################

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WEB_DIR="$REPO_ROOT/dashboard/web"
TF_DIR="$REPO_ROOT/dashboard/infrastructure/terraform/environments/dev"

cd "$TF_DIR"

bucket_name="$(terraform output -raw frontend_bucket_name)"
distribution_id="$(terraform output -raw cloudfront_distribution_id)"
api_endpoint="${VITE_API_BASE_URL:-$(terraform output -raw api_endpoint)}"

if [[ -z "$bucket_name" || -z "$distribution_id" || -z "$api_endpoint" ]]; then
  echo "fatal: terraform outputs missing — has Phase 8 been applied?" >&2
  exit 1
fi

echo ">> bucket:        $bucket_name"
echo ">> distribution:  $distribution_id"
echo ">> api endpoint:  $api_endpoint"

###############################################################################
# 1) Production build with VITE_API_BASE_URL pinned at compile time.
###############################################################################
cd "$WEB_DIR"
echo ">> building dashboard with VITE_API_BASE_URL=$api_endpoint"
VITE_API_BASE_URL="$api_endpoint" npm run build

###############################################################################
# 2) S3 sync. Two passes:
#    a) hashed assets — long max-age, immutable
#    b) index.html (and anything not hashed) — no-cache, must-revalidate
###############################################################################
echo ">> syncing hashed assets (immutable, 1y)"
aws s3 sync "$WEB_DIR/dist/" "s3://$bucket_name/" \
  --delete \
  --exclude "index.html" \
  --cache-control "public, max-age=31536000, immutable"

echo ">> uploading index.html (no-cache)"
aws s3 cp "$WEB_DIR/dist/index.html" "s3://$bucket_name/index.html" \
  --cache-control "no-cache, no-store, must-revalidate" \
  --content-type "text/html; charset=utf-8"

###############################################################################
# 3) CloudFront invalidation. /index.html is no-cache anyway; /* covers any
#    edge cache that already saw a stale entry point.
###############################################################################
echo ">> invalidating CloudFront"
aws cloudfront create-invalidation \
  --distribution-id "$distribution_id" \
  --paths "/*" \
  --output json | grep -E '"Id"|"Status"' || true

echo ">> done. https://dashboard.dram-soc.org"
