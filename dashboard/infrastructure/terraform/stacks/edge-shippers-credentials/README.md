# Stack: edge-shippers-credentials

Phase 11B-1 + ADR-011 — human-managed IAM users + policies for the fluent-bit shippers running on the Pi and the DigitalOcean droplet (Phase 10).

This stack lives outside CI's reach. The CI deploy role ([`modules/github-deploy/`](../../modules/github-deploy/)) does not have `iam:*User*` or `iam:*AccessKey*` actions in its policy. Apply this stack only from the maintainer's workstation.

## Why this is split out

A compromised CI runner with access-key-creation permissions would be able to mint AWS credentials with whatever scope the deploy role can grant. Even with prefix-scoped user policies, the existence of the capability is the blast radius. The 4×/year rotation cadence makes manual workstation apply acceptable friction in exchange.

See [ADR-011](../../../docs/adr/011-cicd-permission-boundary.md) for the full reasoning.

## What lives here

- `aws_iam_user.fluentbit_pi` — `dram-soc-fluentbit-pi`
- `aws_iam_user.fluentbit_droplet` — `dram-soc-fluentbit-droplet`
- `aws_iam_user_policy` for each — scoped `s3:PutObject` on a single prefix
- The associated `data.aws_iam_policy_document` blocks

**Not** here: access keys (managed manually via the rotation runbook to keep the secret out of terraform state), the SNS topic (CI-managed in `modules/edge-shippers/`), heartbeat alarms (same), MaxMind SSM parameter (same — the parameter resource doesn't grant standing privileges).

## State

Same S3 bucket as the dev environment, separate state key:

```
bucket = diamond-iq-tfstate-334856751632
key    = soc-detection-lab/dashboard/edge-shippers-credentials.tfstate
```

## Apply choreography (one-time migration from the dev env)

The original Phase 10 IAM resources are currently in the dev environment's terraform state under `module.edge_shippers.aws_iam_user.*` etc. They need to move to this stack's state without destroying the live AWS resources (which would invalidate the Pi + droplet credentials).

```bash
# Step 1 — drop from dev env state (state-only, AWS untouched)
cd dashboard/infrastructure/terraform/environments/dev
terraform state rm module.edge_shippers.data.aws_iam_policy_document.fluentbit_pi
terraform state rm module.edge_shippers.data.aws_iam_policy_document.fluentbit_droplet
terraform state rm module.edge_shippers.aws_iam_user_policy.fluentbit_pi
terraform state rm module.edge_shippers.aws_iam_user_policy.fluentbit_droplet
terraform state rm module.edge_shippers.aws_iam_access_key.fluentbit_pi
terraform state rm module.edge_shippers.aws_iam_access_key.fluentbit_droplet
terraform state rm module.edge_shippers.aws_iam_user.fluentbit_pi
terraform state rm module.edge_shippers.aws_iam_user.fluentbit_droplet

# Step 2 — initialize this stack
cd ../../stacks/edge-shippers-credentials
terraform init

# Step 3 — import the existing AWS resources
terraform import aws_iam_user.fluentbit_pi      dram-soc-fluentbit-pi
terraform import aws_iam_user.fluentbit_droplet dram-soc-fluentbit-droplet
terraform import aws_iam_user_policy.fluentbit_pi      dram-soc-fluentbit-pi:dram-soc-fluentbit-pi-s3
terraform import aws_iam_user_policy.fluentbit_droplet dram-soc-fluentbit-droplet:dram-soc-fluentbit-droplet-s3

# Step 4 — verify both stacks are drift-free
terraform plan          # in this stack — expect "No changes."
cd ../../environments/dev
terraform plan          # expect no IAM-user diffs
```

## Routine apply (post-migration)

After the one-time migration, this stack only changes when:
- Adding/removing edge users (currently 2; might add a third if the Phase 10 architecture grows)
- Tweaking the prefix-scoped policies

Run `terraform apply` from the maintainer's workstation as needed. Document each rotation in `dashboard/docs/runbooks/edge-credential-rotation.md`.
