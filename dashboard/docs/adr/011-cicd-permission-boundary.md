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
