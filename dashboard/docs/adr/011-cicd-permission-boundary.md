# ADR-011 — CI/CD permission boundary: human-managed credentials are separate from CI-managed infrastructure

**Status:** Accepted
**Date:** 2026-05-07
**Phase introduced:** Phase 11B-1

## Context

Phase 11B introduces GitHub Actions CI/CD for the SOC honeypot dashboard. The deploy workflow uses GitHub OIDC to assume an AWS IAM role (`dram-soc-github-deploy`) and runs `terraform apply` on every merge to `main` (eventually — currently `workflow_dispatch` only per the lesson Diamond IQ paid for in their Phase 8.5).

The dashboard's terraform owns a wide blast radius: Lambda functions, DynamoDB tables, S3 buckets, CloudFront distributions, IAM roles, EventBridge rules, SNS topics, SQS queues, ACM certificates, and SSM parameters. Most of those are routine application infrastructure — broken-pipeline-recoverable, no standing-privilege expansion if compromised.

But three resource classes from Phase 10 sit in a different category:

1. **`aws_iam_user.fluentbit_pi`** + **`aws_iam_user.fluentbit_droplet`** — the IAM users on the Raspberry Pi and DigitalOcean droplet that ship logs to S3.
2. **`aws_iam_access_key`** for each — the static AWS access keys deployed to `/etc/fluent-bit/aws-credentials` on each host.
3. **`aws_iam_user_policy`** for each — `s3:PutObject` scoped to a single prefix.

The IAM users + keys are human-managed credentials. A compromised CI runner with `iam:CreateUser` + `iam:CreateAccessKey` could mint AWS access keys with arbitrary scope (within the deploy role's grants) and exfiltrate them. Even with prefix-scoped policies on the resulting users, the existence of the capability is the blast radius — a CI compromise becomes a credential-stealing event, not just a "broken pipeline" event.

## Decision

**Split the dashboard's terraform into two trust tiers:**

### CI-deployable infrastructure (`environments/dev/` — terraform-applied by GitHub Actions on push)

Everything except the IAM users + access keys + user policies. Includes the SNS topic, CloudWatch heartbeat alarms, log metric filters, and the SSM Parameter Store entry for the MaxMind license key (the parameter resource itself doesn't grant standing privileges — the value is a license key, not an AWS credential).

The deploy role's IAM policy ([`modules/github-deploy/main.tf`](../../infrastructure/terraform/modules/github-deploy/main.tf)) explicitly **excludes** all `iam:*User*` and `iam:*AccessKey*` actions. It also excludes `ssm:DeleteParameter` so a compromised CI cannot wipe the license key.

### Human-managed credentials (`stacks/edge-shippers-credentials/` — terraform-applied manually from the maintainer's workstation)

The 6 IAM resources moved out of `modules/edge-shippers/`:

- `aws_iam_user.fluentbit_pi` + `aws_iam_user.fluentbit_droplet`
- `aws_iam_user_policy.fluentbit_pi` + `aws_iam_user_policy.fluentbit_droplet`
- The two `data.aws_iam_policy_document` blocks they reference

Stored in a separate terraform state file (`soc-detection-lab/dashboard/edge-shippers-credentials.tfstate` on the same shared S3 backend). CI never sees this state and has no API path to mutate it.

The `aws_iam_access_key` resources are **not** in this stack either — terraform cannot recover the `.secret` after initial creation, so they're managed via direct `aws iam create-access-key` / `aws iam delete-access-key` calls per the [edge-credential-rotation runbook](../runbooks/edge-credential-rotation.md). Keeping access keys out of any terraform state means the `.secret` never lands on disk under any Terraform-state encryption assumption.

## Consequences

**Positive:**

- A compromised CI runner cannot mint AWS access keys. The most damaging plausible attack class is contained.
- The boundary is conceptually clean: "CI manages infrastructure that recovers from being broken; humans manage credentials that don't."
- Rotation cadence (4×/year per the runbook) makes the manual workstation apply acceptable friction.
- Terraform state for the credentials stack is small (3 IAM users + 2 user policies + 2 data sources) and rarely changes — easy to audit.

**Negative:**

- Two terraform stacks to apply. Adding a new edge user requires both: define in `stacks/edge-shippers-credentials/` (manual apply) and reference its name from `modules/edge-shippers/` (CI apply). Acceptable because this is a low-frequency operation.
- One-time state migration (the existing IAM resources start in `modules/edge-shippers/`'s state and need to move to the new stack's state) is a manual operator-driven sequence with risk of accidental destroy if commands are mis-ordered. Documented step-by-step in [`stacks/edge-shippers-credentials/README.md`](../../infrastructure/terraform/stacks/edge-shippers-credentials/README.md).
- Access keys can never go back into terraform state under any Terraform-managed key-rotation tool. Acceptable trade-off — keys live only on the host filesystem at `/etc/fluent-bit/aws-credentials` (mode `0600`) and in the maintainer's password manager during rotation windows.

## Alternatives considered

1. **Put everything in one stack and grant CI all the IAM actions.** Rejected — the original CI-mints-access-keys exposure is exactly what this ADR exists to prevent.
2. **Keep IAM users in the edge-shippers module, exclude `iam:*User*` from the CI policy, accept that CI's terraform plan will fail on those resources.** Rejected — silent terraform-plan failures on every CI run are noise that hides real diffs. Cleaner to remove the resources from CI's view entirely.
3. **Use IAM Roles Anywhere instead of IAM users on the edge hosts.** Considered for Phase 9+. The Pi + droplet are not in AWS, so the auth path requires either IAM Roles Anywhere (with X.509 trust anchors) or static keys. Roles Anywhere eliminates the static-key exposure but adds significant setup complexity (CA management, X.509 cert lifecycle, ACM PCA cost). The static-key path with this ADR's CI-permission boundary is the correct trade-off for a portfolio honeypot at current scale; revisit if/when the project graduates to multi-tenant or commercial use.
4. **Move only the access keys (not the users) to the manual stack.** Rejected — `aws_iam_access_key` references `aws_iam_user.<name>.name`, so the user must exist in the same stack as the key (or be a data source — which still requires the user to exist somewhere terraform can `aws_iam_user` against, with the same iam:GetUser gap on the CI side). Cleaner to move the entire user lifecycle.

## Forward considerations

- **Phase 11B-2** — the GitHub Actions workflows assume the `dram-soc-github-deploy` role. The role's permissions are fixed by this ADR; if a workflow finds a missing grant during the first real deploy, fix it in `modules/github-deploy/main.tf` (with a corresponding ADR amendment if the gap is a meaningful expansion of CI's blast radius).
- **Future fluent-bit edge users** (e.g., a third sensor in Phase 13+) need to be added in `stacks/edge-shippers-credentials/`, then their access key minted manually. The CI deploy role does NOT need updating.
- **Tightening the trust policy from `repo:<repo>:*` to `repo:<repo>:ref:refs/heads/main`** (only `main` branch can assume) is a worth-doing tightening once the workflows are stable and PR-from-fork attack surface is irrelevant. Tracked as a future-work item, not blocking this ADR.

## Amendment — Phase 11B Step 4 (2026-05-07): S3 wildcards + role-policy bootstrap pattern

Phase 11B Step 4's first backend deploys (workflow_dispatch retries against the role created by this ADR) revealed two operational realities the original design didn't anticipate. Documenting them here to cement the patterns for future maintainers.

### S3 bucket-attribute wildcards

Terraform's AWS provider unconditionally queries a long tail of bucket-attribute APIs on every `aws_s3_bucket` refresh: `GetBucketVersioning`, `GetBucketPolicy`, `GetBucketTagging`, `GetBucketPublicAccessBlock`, `GetBucketOwnershipControls`, `GetBucketNotification`, `GetBucketCORS`, `GetBucketAcl`, `GetBucketWebsite`, `GetBucketAccelerateConfiguration`, `GetBucketLogging`, `GetReplicationConfiguration`, `GetBucketObjectLockConfiguration`, `GetIntelligentTieringConfiguration`, etc. — and adds new ones over provider versions.

Phase 11B-1's original policy enumerated a subset of these explicitly. PR #2 (Phase 11B Step 4 amendment #1) added two more (`GetBucketWebsite` + `PutBucketWebsite`). The next refresh hit `GetBucketAccelerateConfiguration`. The whack-a-mole pattern would continue indefinitely.

This amendment replaces the explicit enumeration with `s3:GetBucket*` and `s3:PutBucket*` wildcards in `S3ManageProjectBucketsLevel`. Security envelope:

- `s3:GetObject` is a **separate namespace** and is NOT covered by `s3:GetBucket*`. The role still cannot read object content — the "no object reads on `raw/*` in `honeypot-ingest`" property from this ADR's original design is intact.
- Resource scoping unchanged: only `dram-soc-honeypot-ingest` and `dram-soc-dashboard-frontend`.
- `S3FrontendBundleObjects` SID (object-level Get/Put/Delete on the dashboard-frontend bucket) is unchanged — the asymmetric "object-level only on the frontend bundle, never on the ingest bucket" boundary stays intact.

Future-proof against terraform provider adding new bucket-attribute reads.

### Role-policy bootstrap pattern (chicken-and-egg)

The deploy role's policy explicitly **excludes** `iam:PutRolePolicy` on its own role — by design (this ADR's core boundary: CI cannot widen its own permissions). A side effect surfaced in Phase 11B Step 4: any policy update to `dram-soc-github-deploy` cannot be applied by CI from inside the role being updated, because terraform's plan refresh requires the new permissions to read state, but those permissions only land via apply.

The pattern that resolves this:

1. Land the policy change in code (PR + merge to `main`).
2. From the maintainer workstation (`dramir-admin` or equivalent admin identity), run a targeted apply:
    ```
    cd dashboard/infrastructure/terraform/environments/dev
    terraform apply -target='module.github_deploy.aws_iam_role_policy.deploy' -auto-approve
    ```
3. CI's next workflow run (backend-deploy or tf-plan) refreshes successfully against the now-updated policy.

This is a **deliberate consequence** of this ADR's CI-cannot-update-its-own-policy boundary, not an accidental gap. The original Phase 11B-1 deploy used the same workstation-bootstrap pattern (the role had to exist before CI could use it). The Step 4 retry sequence used it for policy updates.

When to apply this pattern: any change to `modules/github-deploy/main.tf`'s policy document (new statements, action wildcards, scope tightening, etc.). The bootstrap step is documented in [edge-credential-rotation.md](../runbooks/edge-credential-rotation.md) alongside the other manual-bootstrap operations the maintainer owns.

When NOT to apply: changes to dashboard application infrastructure (Lambda code, DynamoDB tables, etc.) that don't touch the deploy role's policy — those go through CI normally.

## Amendment #2 — Phase 11B Step 4 retry #4 (2026-05-08): resource-scoping IS the security boundary

The S3 bucket-attribute wildcard amendment above (`s3:GetBucket*` / `s3:PutBucket*`) didn't fully solve the whack-a-mole because AWS S3's IAM action namespace is **inconsistent**. Documenting the empirical lesson here so future maintainers don't re-discover it.

### What happened

Three rounds of S3 policy amendments were needed to close the action-coverage gap:

| Round | Action set | Result |
|---|---|---|
| Phase 11B-1 (original) | Explicit enumeration of ~22 specific bucket-level actions | Missed `s3:GetBucketWebsite` (terraform refresh always queries it) |
| Step 4 amendment #1 (PR #2) | Added `s3:GetBucketWebsite` + `s3:PutBucketWebsite` explicit | Missed `s3:GetAccelerateConfiguration` on next refresh |
| Step 4 amendment #2 (PR #3) | Replaced explicit Get/Put bucket actions with `s3:GetBucket*` / `s3:PutBucket*` wildcards | **STILL missed** `s3:GetAccelerateConfiguration` because the IAM action name doesn't have "Bucket" in it |
| Step 4 amendment #3 (PR #4 — this amendment) | Simplified to `s3:Get*` / `s3:Put*` on bucket-level resources | All future refresh-time reads covered |

### The AWS quirk

AWS S3's IAM action namespace uses inconsistent naming:

- Some actions: `s3:GetBucketX` (`GetBucketWebsite`, `GetBucketLogging`, `GetBucketAcl`, `GetBucketTagging`, etc.)
- Other actions: `s3:GetX` where X is the configuration type (`GetAccelerateConfiguration`, `GetEncryptionConfiguration`, `GetLifecycleConfiguration`, `GetReplicationConfiguration`, `GetIntelligentTieringConfiguration`, `GetAnalyticsConfiguration`, `GetMetricsConfiguration`, `GetInventoryConfiguration`, etc.)

The API operation names usually have "Bucket" in them (`GetBucketAccelerateConfiguration`), but the corresponding IAM action name often doesn't (`s3:GetAccelerateConfiguration`). `s3:GetBucket*` matched the first set but not the second.

### The architectural lesson

**Resource scoping is the actual security boundary, not action-name enumeration.**

The S3ManageProjectBucketsLevel statement uses bucket-level ARNs only:
```
"arn:aws:s3:::dram-soc-honeypot-ingest"
"arn:aws:s3:::dram-soc-dashboard-frontend"
```
Note: NO `/*` suffix. These are bucket-only resource ARNs.

`s3:GetObject` is in the `s3:Get*` action namespace, but its required resource format is `arn:aws:s3:::bucket/key` (with `/*`). IAM evaluates action AND resource together — bucket-only ARNs don't match the object-level resource pattern, so `s3:GetObject` is denied by resource mismatch even though `s3:Get*` matches the action.

This means `s3:Get*` and `s3:Put*` on bucket-level resources is **safe**:
- All bucket-attribute reads/writes are covered (current + future).
- Object reads are NOT granted because the resource scope doesn't include the object-level ARN namespace.
- Object-level access lives in the SEPARATE `S3FrontendBundleObjects` SID, which scopes to `dram-soc-dashboard-frontend/*` only — NEVER `honeypot-ingest/*`.
- The "no CI reads of attacker payloads in `raw/*`" property from this ADR's original design is preserved by the explicit asymmetry between the two SIDs, not by enumeration of action names.

### Practical implications

Going forward, when designing IAM policies for terraform-managed AWS resources:

- **Lean on resource scoping**, not action enumeration. AWS IAM action names are inconsistent across services and even within services; enumeration is brittle.
- Use action wildcards (`service:Get*`, `service:Put*`) on tightly-scoped resource ARNs to future-proof against AWS adding new refresh-time read APIs.
- Keep object-level / data-plane grants in separate SIDs with object-level resource ARNs — those are the ones that actually need explicit-action discipline because object content is what you're protecting.
- Reserve explicit-enumeration for actions that genuinely DO widen blast radius (e.g., `iam:Create*`, `lambda:InvokeFunction`, etc.) — not for refresh-time read APIs.

The S3FrontendBundleObjects SID (object-level Get/Put/Delete on `dram-soc-dashboard-frontend/*` only) remains the explicit object-access surface — it is the single place a future maintainer needs to audit when reasoning about "what objects can CI read or write." That asymmetry is the ADR's core security property, not the action enumeration on the bucket-level statement.
