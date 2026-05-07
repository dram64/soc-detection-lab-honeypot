locals {
  common_tags = {
    Project     = "soc-detection-lab"
    Component   = "dashboard"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

module "honeypot_table" {
  source = "../../modules/dynamodb"

  table_name          = "${var.name_prefix}-honeypot"
  deletion_protection = true
  tags                = local.common_tags
}

module "ingest" {
  source = "../../modules/ingest"

  name_prefix             = var.name_prefix
  honeypot_table_name     = module.honeypot_table.table_name
  honeypot_table_arn      = module.honeypot_table.table_arn
  ingest_zip_path         = var.ingest_zip_path
  geolite2_layer_zip_path = var.geolite2_layer_zip_path

  tags = local.common_tags
}

module "aggregator" {
  source = "../../modules/aggregator"

  name_prefix         = var.name_prefix
  honeypot_table_name = module.honeypot_table.table_name
  honeypot_table_arn  = module.honeypot_table.table_arn
  honeypot_stream_arn = module.honeypot_table.stream_arn
  aggregator_zip_path = var.aggregator_zip_path

  tags = local.common_tags
}

module "api" {
  source = "../../modules/api"

  name_prefix         = var.name_prefix
  honeypot_table_name = module.honeypot_table.table_name
  honeypot_table_arn  = module.honeypot_table.table_arn
  api_zip_path        = var.api_zip_path
  allowed_origins     = var.allowed_origins
  git_sha             = var.git_sha

  tags = local.common_tags
}

module "hosting" {
  source = "../../modules/hosting"

  name_prefix                 = var.name_prefix
  domain_name                 = var.domain_name
  billing_alarm_threshold_usd = var.billing_alarm_threshold_usd

  tags = local.common_tags
}

module "edge_shippers" {
  source = "../../modules/edge-shippers"

  name_prefix           = var.name_prefix
  ingest_bucket_name    = module.ingest.ingest_bucket_name
  ingest_bucket_arn     = module.ingest.ingest_bucket_arn
  ingest_log_group_name = module.ingest.ingest_log_group_name
  maxmind_license_key   = var.maxmind_license_key

  tags = local.common_tags
}

###############################################################################
# Phase 11B-1: GitHub Actions OIDC deploy role.
#
# Permits workflows in github.com/dram64/soc-detection-lab-honeypot to
# assume an AWS role and apply terraform / update Lambda code / deploy
# the frontend bundle. Trust policy is a literal copy of Diamond IQ's
# working module (one repo string changed); deploy permissions are
# scoped to dram-soc-* ARN patterns. ADR-011 explains the human-vs-CI
# permission boundary — IAM users live in the separate
# stacks/edge-shippers-credentials/ stack, not here.
###############################################################################

data "aws_caller_identity" "current" {}

module "github_deploy" {
  source = "../../modules/github-deploy"

  account_id = data.aws_caller_identity.current.account_id
  aws_region = var.aws_region

  tags = local.common_tags
}
