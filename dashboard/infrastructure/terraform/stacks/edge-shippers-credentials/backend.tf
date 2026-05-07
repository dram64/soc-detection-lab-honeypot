###############################################################################
# Separate terraform state for the human-managed edge-shipper credentials.
#
# ADR-011: this stack lives outside CI's reach. Same S3 backend bucket as
# the dev environment, different state key. The CI deploy role grants
# (modules/github-deploy) intentionally exclude all iam:*User* and
# iam:*AccessKey* actions, so even if CI is compromised it cannot mint
# AWS access keys.
#
# Apply choreography:
#   cd dashboard/infrastructure/terraform/stacks/edge-shippers-credentials
#   terraform init
#   terraform plan          # expect 0 changes after the Phase 11B-1 import
#   # rotation: see dashboard/docs/runbooks/edge-credential-rotation.md
###############################################################################

terraform {
  backend "s3" {
    bucket         = "diamond-iq-tfstate-334856751632"
    key            = "soc-detection-lab/dashboard/edge-shippers-credentials.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "diamond-iq-tfstate-locks"
  }
}
