# Runbook — Rotating fluent-bit edge credentials

**Cadence:** every 90 days. Calendar reminder; rotation is manual.

The Pi and the DigitalOcean droplet each carry a static AWS access key for fluent-bit's S3 output. Each key is scoped to `s3:PutObject` on a single prefix only (`raw/cowrie/*` for Pi, `raw/haproxy/*` for droplet) — see [ADR-010](../adr/010-fluent-bit-edge-shippers.md). Rotation is the primary mitigation for the static-key exposure surface.

## Why rotate

- The keys live on `/etc/fluent-bit/aws-credentials` (mode `0600`) on hosts that are exposed to internet attack traffic.
- The Pi is a residential network endpoint; the droplet runs the public SSH honeypot. Both are higher-risk than typical AWS-internal compute.
- AWS IAM access keys never expire on their own; if a key is exfiltrated, the only TTL on the leak is your rotation cadence.

## Steps (per host)

The flow is the same for the Pi and the droplet — just substitute the host name.

1. **Bump the access key in Terraform.** `aws_iam_access_key` rotates by `taint`-ing the resource; the next apply produces a fresh secret.
   ```
   cd dashboard/infrastructure/terraform/environments/dev
   terraform apply -replace=module.edge_shippers.aws_iam_access_key.fluentbit_pi -auto-approve
   # (or fluentbit_droplet)
   ```
   The old IAM access key resource is destroyed and a new one created. The IAM user itself is not touched, so the policy attachment remains.

2. **Read the new credentials** and write them to the host:
   ```
   terraform output -raw fluentbit_pi_credentials | \
     ssh -p 22022 jackal@192.168.1.253 \
       'sudo tee /etc/fluent-bit/aws-credentials >/dev/null && \
        sudo chown fluent-bit:fluent-bit /etc/fluent-bit/aws-credentials && \
        sudo chmod 0600 /etc/fluent-bit/aws-credentials'
   ```

3. **Restart fluent-bit** to pick up the new credentials:
   ```
   ssh -p 22022 jackal@192.168.1.253 'sudo systemctl restart soc-fluent-bit.service'
   ```

4. **Verify** within 60 seconds:
   ```
   aws s3 ls s3://dram-soc-honeypot-ingest/raw/cowrie/ --recursive | tail -3
   ```
   Should show fresh objects with timestamps after the restart. If not, check `journalctl -u soc-fluent-bit.service -n 50` on the host for `AccessDenied` or signature errors.

5. **Confirm the heartbeat alarm stays OK** (or returns to OK if it fired during the brief restart window):
   ```
   aws cloudwatch describe-alarms \
       --alarm-names dram-soc-cowrie-heartbeat-missing dram-soc-haproxy-heartbeat-missing \
       --query 'MetricAlarms[*].{name:AlarmName,state:StateValue}' \
       --output table
   ```

## When rotation goes wrong

- **`AccessDenied` after restart.** The new credentials didn't write correctly. Re-run step 2; check ownership (`fluent-bit:fluent-bit`) and mode (`0600`).
- **`InvalidClientTokenId`.** AWS IAM rejected the new key. Either Terraform didn't actually create it (check `terraform output`), or the AWS clock on the host is skewed >5 min from real time. Run `timedatectl` on the host.
- **fluent-bit restarts but no objects appear in S3 within 5 min.** Check fluent-bit's storage queue: `ls -lh /var/lib/fluent-bit/storage`. If the queue is growing, network egress is broken or AWS is throttling — separate issue, not rotation.

## Out-of-band: emergency revoke

If a key is suspected compromised before the next rotation:

```
aws iam list-access-keys --user-name dram-soc-fluentbit-pi
aws iam delete-access-key --user-name dram-soc-fluentbit-pi --access-key-id AKIAxxxxxxxxxxxxxxxx
```

Then run steps 1–5 above to mint a replacement. The host will fail-loop on `InvalidClientTokenId` until the new credentials are in place — that's the desired behavior; pause shipping rather than ship under a maybe-compromised identity.

## Audit log

Each rotation should be logged in `dashboard/docs/PHASE_10_LOG.md` (or its successor) under a "Credential rotations" section: date, host, reason (scheduled / emergency).

## Phase 10 chat-disclosed credentials — accelerated one-time rotation

Three secrets were transmitted in plain text during the Phase 10 Claude Code chat session on **2026-05-07**:

- **Pi fluent-bit AWS access key** `AKIAU35YERIIJXYDFHF6`
- **Droplet fluent-bit AWS access key** `AKIAU35YERIIKOGZX6B3`
- **MaxMind GeoLite2 license key** (stored at SSM `/dram-soc/maxmind/license_key`)

All three must be rotated **within 7 days** of Phase 10 going live as a one-time accelerated rotation, then resume the normal 90-day cadence below.

**Future iterations:** never echo a secret back into chat. Instruct the user to retrieve via `terraform output -raw` directly, or read from SSM via `aws ssm get-parameter --with-decryption`. The agent should reference the value path, not the value.

## MaxMind license key — Phase 10 deploy hygiene

The MaxMind GeoLite2 license key was provided in a Claude Code chat session at Phase 10 deploy time and stored into SSM Parameter Store `/dram-soc/maxmind/license_key` via `TF_VAR_maxmind_license_key`. **That value is considered chat-disclosed and must be rotated within 7 days of Phase 10 going live.**

Steps to rotate:

1. Sign in to <https://www.maxmind.com/en/accounts/current/license-key> and revoke the old key + generate a new one.
2. Update SSM:
   ```
   aws ssm put-parameter --name /dram-soc/maxmind/license_key \
       --type SecureString --overwrite --value 'NEW_KEY_VALUE'
   ```
3. The next scheduled GeoIP-layer refresh (Phase 9 work, or the manual `download_geolite2.sh` run) will pick up the new key from SSM. There is no fluent-bit / Lambda restart required — neither service reads the SSM parameter directly.

Record the rotation date in PHASE_10_LOG.md "Credential rotations" along with the per-host fluent-bit key rotations.

---

## Role-policy bootstrap (Phase 11B Step 4 amendment)

The `dram-soc-github-deploy` IAM role's policy is managed by terraform (`modules/github-deploy/main.tf`) but applied by CI from inside the very role being updated. Per [ADR-011](../adr/011-cicd-permission-boundary.md), CI explicitly **cannot** update its own policy via its own runs — the role lacks `iam:PutRolePolicy` on itself, by design.

Any change to the deploy role's policy document (new statements, action wildcards, scope tightening, etc.) requires a one-time manual apply from the maintainer workstation BEFORE CI can use the new permissions. Without this bootstrap step, CI's next backend-deploy run will fail at `terraform plan` with `AccessDenied` errors on whichever new permissions the change introduced.

Steps after merging a policy-changing PR to `main`:

1. Pull the merged change locally:
   ```
   git checkout main && git pull origin main
   ```
2. From the maintainer workstation, with admin AWS credentials (`dramir-admin` or equivalent), run a targeted apply on JUST the role-policy resource:
   ```
   cd dashboard/infrastructure/terraform/environments/dev
   terraform apply -target='module.github_deploy.aws_iam_role_policy.deploy' -auto-approve
   ```
3. Verify the new statements / actions are live on the role:
   ```
   aws iam get-role-policy \
       --role-name dram-soc-github-deploy \
       --policy-name dram-soc-github-deploy-policy \
       --output text
   ```
   Grep for the SID names or action strings the policy change introduced.
4. Re-trigger the CI workflow that was blocked (e.g., `gh workflow run dashboard-backend-deploy.yml --field reason="<context>"`).

Same pattern was used for the original Phase 11B-1 role create (the role had to exist before CI could assume it) and twice during the Phase 11B Step 4 retry sequence (PR #2 IAM amendments + PR #3 S3 wildcard amendment). It is the documented escape hatch for policy bootstrapping; not a workaround.
