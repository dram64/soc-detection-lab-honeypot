# Terraform module: github-deploy

Phase 11B-1. The OIDC trust + deploy IAM role that GitHub Actions assumes (via `aws-actions/configure-aws-credentials`) to apply terraform / update Lambda code / sync the frontend bundle.

Reference: [ADR-011 — CI/CD permission boundary](../../../docs/adr/011-cicd-permission-boundary.md). Trust policy is a literal copy of Diamond IQ's working module (one `var.github_repo` substitution); deploy permissions are adapted from Diamond IQ's surface minus what SOC doesn't have (WAFv2, apigateway-cw-logs role) and plus what SOC does (ACM cert, SSM Parameter Store, Lambda layer, CloudFront OAC/headers/function management).

## Resources

- `data.aws_iam_openid_connect_provider.github` — reads the existing account-shared OIDC provider (Diamond IQ created it; SOC does not own it)
- `aws_iam_role.deploy` — `dram-soc-github-deploy`
- `aws_iam_role_policy.deploy` — 19-statement scoped deploy policy

## What this role can NOT do (by design)

- **Manage IAM users.** `iam:*User*` and `iam:*AccessKey*` actions are NOT granted. The fluent-bit edge users (`dram-soc-fluentbit-pi`, `-droplet`) live in [`stacks/edge-shippers-credentials/`](../../stacks/edge-shippers-credentials/), applied manually from the maintainer's workstation. ADR-011 explains why.
- **Delete SSM parameters.** `ssm:DeleteParameter` is excluded; a compromised CI cannot wipe the MaxMind license key (or any other dram-soc-namespaced secret).
- **Touch AWS WAF.** ADR-007 — no AWS WAF in any phase.
- **Decrypt arbitrary KMS keys.** Only the AWS-managed `aws/ssm` key is implicitly available for SSM SecureString reads.

## Inputs

- `github_repo` (default `dram64/soc-detection-lab-honeypot`) — repo allowed to assume the role.
- `role_name` (default `dram-soc-github-deploy`)
- `name_prefix` (default `dram-soc`) — ARN scoping prefix for all resources the role can manage.
- `account_id` (required) — AWS account id for ARN construction.
- `aws_region` (default `us-east-1`)
- `state_bucket_name` (default `diamond-iq-tfstate-334856751632`) — shared with Diamond IQ.
- `lock_table_name` (default `diamond-iq-tfstate-locks`) — shared.

## After apply

1. Capture the role ARN: `terraform output -raw role_arn` → expect `arn:aws:iam::334856751632:role/dram-soc-github-deploy`.
2. Use that ARN in Phase 11B-2's GitHub Actions workflows as `AWS_ROLE_ARN` (the env var the `aws-actions/configure-aws-credentials` step reads).
3. The first workflow run that calls `aws sts get-caller-identity` should print `Arn: arn:aws:sts::334856751632:assumed-role/dram-soc-github-deploy/...` — that's the OIDC handshake working end-to-end.
