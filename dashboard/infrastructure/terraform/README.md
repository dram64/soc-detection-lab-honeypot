# Dashboard infrastructure

Terraform configurations for the Honeypot Visualizer Dashboard (PROJECT_PLAN.md §11).

## Layout

```
infrastructure/terraform/
├── environments/
│   └── dev/                 # Single-environment v1
│       ├── backend.tf       # S3 remote state config
│       ├── providers.tf     # AWS provider + default tags
│       ├── versions.tf      # Terraform + provider version pins
│       ├── variables.tf     # aws_region, name_prefix, environment
│       ├── main.tf          # Module instantiations
│       └── outputs.tf       # Stable outputs surfaced to other phases
└── modules/
    ├── dynamodb/            # Phase 1 — single-table per ADR-003
    ├── lambda/              # Phase 2/3/4 — stub
    ├── api-gateway/         # Phase 4 — stub
    ├── cloudfront/          # Phase 8 — stub (no AWS WAF; ADR-007)
    └── alarms/              # Phase 9 — stub
```

## Bootstrap (one-time, manual — not yet performed)

The S3 backend (`dram-soc-tfstate`) and DynamoDB lock table (`dram-soc-tfstate-locks`)
referenced in `environments/dev/backend.tf` must exist before `terraform init`
will succeed. Bootstrap is **not** performed in Phase 1 — it requires a
deliberate operator step and is outside this Terraform configuration's
managed resources to avoid a chicken-and-egg loop.

When ready (post-Phase-1 review), the bootstrap recipe is:

```bash
aws s3api create-bucket \
  --bucket dram-soc-tfstate --region us-east-1 \
  --tagging "TagSet=[{Key=Project,Value=soc-detection-lab},{Key=Component,Value=tfstate}]"
aws s3api put-bucket-versioning \
  --bucket dram-soc-tfstate --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket dram-soc-tfstate \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws dynamodb create-table \
  --table-name dram-soc-tfstate-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --tags Key=Project,Value=soc-detection-lab Key=Component,Value=tfstate
```

## Phase 1 acceptance

`terraform plan` (after bootstrap) should output exactly one resource to add:
the DynamoDB table `dram-soc-honeypot` plus its 8 attributes / 3 GSIs / streams /
PITR / TTL / SSE. No `apply` is performed in Phase 1.
