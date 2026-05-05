# Terraform module: ingest

Phase 2 of the dashboard build. Provisions the S3 → Lambda → DynamoDB ingest path.

## Resources

- `aws_s3_bucket.ingest` — `dram-soc-honeypot-ingest`, versioning ON, SSE-S3, public-access block, lifecycle (Glacier @30d, expire @90d)
- `aws_sqs_queue.dlq` — `dram-soc-ingest-dlq`, 14-day retention, SSE managed
- `aws_lambda_function.ingest` — `dram-soc-ingest`, Python 3.13, 256 MB, 60s timeout, Reserved Concurrency = 20
- `aws_lambda_layer_version.geolite2` — `dram-soc-geolite2` (optional; depends on `geolite2_layer_zip_path`)
- `aws_iam_role.ingest` — minimum-permission execution role (see PROJECT_PLAN.md §10)
- `aws_cloudwatch_log_group.ingest` — 14-day retention
- `aws_cloudwatch_metric_alarm` × 4 — errors, throttles, p95 duration, DLQ depth
- `aws_s3_bucket_notification.ingest` — `s3:ObjectCreated:*` on `raw/*.json.gz` → ingest Lambda

## Build prerequisites

Before `terraform apply`:

```bash
# 1. Fetch GeoLite2 databases (.mmdb files; not in git)
MAXMIND_LICENSE_KEY=xxxx ../../../functions/layers/geolite2/download_geolite2.sh

# 2. Package the ingest Lambda + GeoLite2 layer .zip files
../../../scripts/package_lambdas.sh
```

The package script writes:
- `modules/ingest/build/ingest.zip`
- `modules/ingest/build/geolite2-layer.zip`

These paths are passed to the module via `ingest_zip_path` and `geolite2_layer_zip_path`.

## Inputs

See [variables.tf](variables.tf).

## Outputs

See [outputs.tf](outputs.tf). Phase 3 (aggregator) reads `honeypot_stream_arn` from the dynamodb module; Phase 4 (api) reads `honeypot_table_name`. The ingest path itself surfaces the bucket / function / DLQ / log group names.
