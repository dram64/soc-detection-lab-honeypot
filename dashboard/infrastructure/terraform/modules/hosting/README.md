# Terraform module: hosting

Phase 8 — Production hosting (PROJECT_PLAN.md §11, ADR-007).

## Resources

- `aws_acm_certificate.dashboard` — TLS cert in us-east-1 (CloudFront requirement) with DNS validation
- `aws_acm_certificate_validation.dashboard` — blocks apply until cert is ISSUED (60m timeout)
- `aws_s3_bucket.frontend` + 4 ancillary configs (public-access-block, versioning, SSE, ownership)
- `aws_cloudfront_origin_access_control.frontend` — OAC sigv4
- `aws_cloudfront_distribution.frontend` — alias `dashboard.dram-soc.org`, S3 origin via OAC, SPA fallback, two cache behaviors (default = CachingOptimized; `/index.html` = CachingDisabled)
- `aws_s3_bucket_policy.frontend` — only the OAC principal can GetObject
- `aws_cloudwatch_metric_alarm.billing` — $10/month threshold

No AWS WAF — see ADR-007. Cloudflare proxied DNS (orange cloud) is the edge.

## Apply choreography

The cert + validation + CloudFront chain has a manual DNS-record step in the middle, so `terraform apply` is run in two passes:

1. `terraform apply -target=module.hosting.aws_acm_certificate.dashboard -auto-approve`
   — creates only the cert resource; the `acm_validation_record` output is now populated.
2. `terraform output -json acm_validation_record` — surface the CNAME to add in Cloudflare (DNS-only / grey cloud).
3. After the user confirms the record is live, `terraform apply -auto-approve`
   — `aws_acm_certificate_validation` waits for ISSUED, then CloudFront builds (~10–30 min).
4. After CloudFront reaches `Status=Deployed`, the user adds the final `dashboard.dram-soc.org` CNAME → `<distribution>.cloudfront.net` in Cloudflare (proxied / orange cloud).

## Notes

- `price_class = "PriceClass_100"` (US/EU/IL only) keeps egress cheap; recruiter audience is largely US.
- SPA fallback returns `index.html` with HTTP 200 for 403/404 — TanStack Router handles deep links client-side.
- `/index.html` uses CachingDisabled so users always pick up the latest entry pointing at the freshly-hashed asset bundle. Default behavior (`/*`) uses CachingOptimized — Vite hashes asset filenames so cache-busting is automatic.
- Billing alarm is a CloudWatch metric in `AWS/Billing`. Account-level "Receive Billing Alerts" must be toggled on once in Billing Preferences for `EstimatedCharges` to publish.
