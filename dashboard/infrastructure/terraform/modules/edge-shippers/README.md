# Terraform module: edge-shippers

Phase 10 — fluent-bit on Pi (Cowrie) + droplet (HAProxy). See [ADR-010](../../../docs/adr/010-fluent-bit-edge-shippers.md).

## Resources

- 2 IAM users (`-fluentbit-pi`, `-fluentbit-droplet`) under `/edge/` path
- 2 IAM access keys (one per user, sensitive outputs)
- 2 IAM user policies (each scoped to `s3:PutObject` on its prefix only)
- 1 SSM Parameter Store SecureString for the MaxMind GeoLite2 license key
- 1 SNS topic for edge alarms (skipped if `var.alarm_topic_arn` supplied)
- 2 CloudWatch metric filters on the ingest Lambda's log group
- 2 CloudWatch alarms (cowrie + haproxy heartbeat, fire when no new objects in `heartbeat_period_minutes`)

## Inputs

- `name_prefix` — defaults to `dram-soc`
- `ingest_bucket_name` / `ingest_bucket_arn` — pass through from the `ingest` module's outputs
- `ingest_log_group_name` — pass through from the `ingest` module
- `alarm_topic_arn` — optional. Bring-your-own SNS topic if a project-wide one already exists; otherwise the module creates `${name_prefix}-edge-alarms`.
- `heartbeat_period_minutes` — defaults to 15
- `maxmind_license_key` — passed via `TF_VAR_maxmind_license_key`. Empty default keeps `terraform plan` runnable when the key isn't available.

## After apply

1. **Subscribe an email** to the alarm topic:
   ```
   aws sns subscribe --topic-arn $(terraform output -raw edge_alarm_topic_arn) \
     --protocol email --notification-endpoint you@example.com
   ```
   Confirm the subscription email.
2. **Copy credentials to each host** at `/etc/fluent-bit/aws-credentials` (mode `0600`, owned by `fluent-bit:fluent-bit`):
   ```
   terraform output -raw fluentbit_pi_credentials | ssh pi "sudo tee /etc/fluent-bit/aws-credentials > /dev/null && sudo chown fluent-bit:fluent-bit /etc/fluent-bit/aws-credentials && sudo chmod 0600 /etc/fluent-bit/aws-credentials"
   ```
   Same for droplet.
3. **Rotation cadence:** 90 days. See `docs/runbooks/edge-credential-rotation.md`.
