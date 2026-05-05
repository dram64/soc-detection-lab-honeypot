# Runbook: Terraform state bootstrap

The dashboard's Terraform configuration uses an S3 remote backend with a DynamoDB lock table. These resources must exist before `terraform init` will succeed against `infrastructure/terraform/environments/dev`.

This is a **one-time manual step** performed outside the dashboard's managed Terraform configuration to avoid a chicken-and-egg loop.

---

## Path A — Reuse the existing Diamond IQ state bucket (NOT recommended for this project)

The Diamond IQ project in the same AWS account (334856751632) has an existing state bucket:

- Bucket: `diamond-iq-tfstate-334856751632`
- Lock table: `diamond-iq-tfstate-locks`
- Tags: `Project=diamond-iq`

**To use this bucket**, edit `dashboard/infrastructure/terraform/environments/dev/backend.tf`:

```hcl
terraform {
  backend "s3" {
    bucket         = "diamond-iq-tfstate-334856751632"
    key            = "dashboard/dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "diamond-iq-tfstate-locks"
    encrypt        = true
  }
}
```

**Tradeoff:** the bucket carries the `Project=diamond-iq` tag. Storing SOC dashboard state here muddies the cost / blast-radius boundary between projects. Acceptable if you treat the state bucket as account-level shared infra; not acceptable if you want clean project isolation. PROJECT_PLAN.md §16 is built around `Project=soc-detection-lab` tagging discipline.

---

## Path B — Dedicated `dram-soc-terraform-state` bucket (recommended; current backend.tf default)

Run these commands with the same AWS credentials you'll use for `terraform apply`. Region: `us-east-1`.

```bash
# 1. Create the state bucket (versioned, SSE-S3 encrypted, public access fully blocked)
aws s3api create-bucket \
  --bucket dram-soc-terraform-state \
  --region us-east-1

aws s3api put-bucket-versioning \
  --bucket dram-soc-terraform-state \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket dram-soc-terraform-state \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
      "BucketKeyEnabled": true
    }]
  }'

aws s3api put-public-access-block \
  --bucket dram-soc-terraform-state \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

aws s3api put-bucket-tagging \
  --bucket dram-soc-terraform-state \
  --tagging 'TagSet=[{Key=Project,Value=soc-detection-lab},{Key=Component,Value=tfstate},{Key=ManagedBy,Value=manual-bootstrap}]'

# 2. Create the DynamoDB lock table (on-demand)
aws dynamodb create-table \
  --table-name dram-soc-terraform-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1 \
  --tags Key=Project,Value=soc-detection-lab Key=Component,Value=tfstate Key=ManagedBy,Value=manual-bootstrap

# 3. Wait for the lock table to become ACTIVE (usually < 30 s)
aws dynamodb wait table-exists --table-name dram-soc-terraform-locks --region us-east-1

# 4. Verify
aws s3api head-bucket --bucket dram-soc-terraform-state
aws dynamodb describe-table --table-name dram-soc-terraform-locks --region us-east-1 --query 'Table.TableStatus'
```

Expected total cost of bootstrap: **< $0.10/month** (single-digit-MB state file, on-demand DDB lock contention).

---

## After bootstrap

```bash
cd dashboard/infrastructure/terraform/environments/dev
terraform init    # downloads provider, configures S3 backend with no migration prompt
terraform plan    # should be clean
```

`terraform apply` is **NOT** part of bootstrap — it is the explicit per-phase operator step that follows once each phase's plan is reviewed.

---

## Decommissioning

Both paths' state buckets persist for the life of the project. To decommission:

1. `terraform destroy` everything in the dashboard's main stack first.
2. Empty the state bucket (`aws s3 rm s3://<bucket>/dashboard/ --recursive`).
3. If the bucket is dedicated to this project, `aws s3 rb s3://dram-soc-terraform-state` and `aws dynamodb delete-table --table-name dram-soc-terraform-locks`.
4. If reusing Diamond IQ's bucket, leave it alone.

The state bucket is **not** managed by the dashboard's Terraform — destroying the dashboard's resources will not delete the state bucket.
