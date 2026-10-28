#!/usr/bin/env bash
###############################################################################
# Deploy the apex portfolio (dram-soc.org) from dashboard/frontend-apex/ to
# s3://<bucket>/apex/ and invalidate CloudFront.
#
# The apex page shares the dashboard's bucket and distribution; the
# host-router CloudFront Function maps dram-soc.org/* and www.dram-soc.org/*
# onto apex/*. Everything here writes under apex/ only, so the dashboard SPA
# at the bucket root is never touched. The same apex/ prefix is also the
# root of desiramirez.com, served by a distribution in the showcase repo's
# Terraform (infra/site_domain.tf); it gets invalidated too.
#
# Usage (from repo root or anywhere):
#   ./dashboard/scripts/deploy_apex.sh             # deploy
#   ./dashboard/scripts/deploy_apex.sh --dry-run   # show what would change
#
# Preview locally first: node dashboard/scripts/serve_apex.mjs
###############################################################################

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APEX_DIR="$REPO_ROOT/dashboard/frontend-apex"
BUCKET="dram-soc-dashboard-frontend"
APEX_HOST="dram-soc.org"
SITE_HOST="desiramirez.com"
CACHE_CONTROL="public, max-age=300, must-revalidate"

# The bucket lives in us-east-1; respect an explicit override.
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

dry_run=""
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run="--dryrun"
fi

# Cloudflare's Email Obfuscation rewrites mailto: links at the edge. A page
# saved from the live site carries those rewrites, which only work behind
# the proxy (the 2026-09-19 import of index.html did this). Ship the plain
# source; Cloudflare re-applies the obfuscation on the way out.
if grep -rq --include="*.html" "cdn-cgi" "$APEX_DIR"; then
  echo "fatal: frontend-apex/ contains Cloudflare edge markup (/cdn-cgi/)." >&2
  echo "       Restore plain mailto: links before deploying." >&2
  exit 1
fi

distribution_for() {
  aws cloudfront list-distributions \
    --query "DistributionList.Items[?Aliases.Items != null && contains(Aliases.Items, '$1')].Id | [0]" \
    --output text
}

distribution_id="$(distribution_for "$APEX_HOST")"
if [[ -z "$distribution_id" || "$distribution_id" == "None" ]]; then
  echo "fatal: no CloudFront distribution has the alias $APEX_HOST" >&2
  exit 1
fi

site_distribution_id="$(distribution_for "$SITE_HOST")"
if [[ "$site_distribution_id" == "None" ]]; then
  site_distribution_id=""
fi

echo ">> source:        $APEX_DIR"
echo ">> target:        s3://$BUCKET/apex/"
echo ">> distribution:  $distribution_id ($APEX_HOST)"
echo ">> distribution:  ${site_distribution_id:-none yet} ($SITE_HOST)"

###############################################################################
# 1) S3 sync. --delete is scoped to apex/, so a file removed locally comes
#    down from the site too. Pages go up in their own pass to pin the charset.
###############################################################################
echo ">> syncing assets"
aws s3 sync "$APEX_DIR/" "s3://$BUCKET/apex/" $dry_run \
  --delete \
  --exclude "*.html" \
  --exclude ".*" \
  --exclude "*/.*" \
  --cache-control "$CACHE_CONTROL"

echo ">> syncing pages"
aws s3 sync "$APEX_DIR/" "s3://$BUCKET/apex/" $dry_run \
  --delete \
  --exclude "*" \
  --include "*.html" \
  --cache-control "$CACHE_CONTROL" \
  --content-type "text/html; charset=utf-8"

if [[ -n "$dry_run" ]]; then
  echo ">> dry run: nothing uploaded, no invalidation"
  exit 0
fi

###############################################################################
# 2) CloudFront invalidation, same /* as deploy_frontend.sh. Cloudflare may
#    hold static assets (not HTML) for up to the 300 s max-age on top of this.
###############################################################################
for id in "$distribution_id" $site_distribution_id; do
  echo ">> invalidating CloudFront $id"
  aws cloudfront create-invalidation \
    --distribution-id "$id" \
    --paths "/*" \
    --output json | grep -E '"Id"|"Status"' || true
done

live_host="$APEX_HOST"
if [[ -n "$site_distribution_id" ]]; then
  live_host="$SITE_HOST"
fi
echo ">> done. https://$live_host"
