###############################################################################
# Phase 11B-1 + ADR-011: human-managed edge-shipper credentials.
#
# These IAM resources were originally in modules/edge-shippers/ alongside the
# SNS topic + heartbeat alarms + SSM parameter. Phase 11B-1 split them into
# this separate stack so the CI deploy role (modules/github-deploy/) can
# manage all the dashboard infrastructure WITHOUT having permission to mint
# AWS access keys.
#
# Apply choreography for the initial migration (one-time):
#   1. From dev environment: terraform state rm module.edge_shippers.aws_iam_user.fluentbit_pi
#                            terraform state rm module.edge_shippers.aws_iam_user.fluentbit_droplet
#                            terraform state rm module.edge_shippers.aws_iam_access_key.fluentbit_pi
#                            terraform state rm module.edge_shippers.aws_iam_access_key.fluentbit_droplet
#                            terraform state rm module.edge_shippers.aws_iam_user_policy.fluentbit_pi
#                            terraform state rm module.edge_shippers.aws_iam_user_policy.fluentbit_droplet
#                            terraform state rm module.edge_shippers.data.aws_iam_policy_document.fluentbit_pi
#                            terraform state rm module.edge_shippers.data.aws_iam_policy_document.fluentbit_droplet
#   2. Here: terraform init
#   3. Here: terraform import aws_iam_user.fluentbit_pi      dram-soc-fluentbit-pi
#            terraform import aws_iam_user.fluentbit_droplet dram-soc-fluentbit-droplet
#            terraform import aws_iam_user_policy.fluentbit_pi      dram-soc-fluentbit-pi:dram-soc-fluentbit-pi-s3
#            terraform import aws_iam_user_policy.fluentbit_droplet dram-soc-fluentbit-droplet:dram-soc-fluentbit-droplet-s3
#   4. terraform plan in BOTH stacks should show 0 changes (drift-free).
#
# Access keys are NOT imported because their `.secret` is unrecoverable
# after the initial creation. The deployed keys on the Pi + droplet
# remain valid; rotate via the runbook (taint + apply HERE) when due.
###############################################################################

locals {
  pi_prefix      = "raw/cowrie/"
  droplet_prefix = "raw/haproxy/"

  pi_resource_arn      = "${var.ingest_bucket_arn}/${local.pi_prefix}*"
  droplet_resource_arn = "${var.ingest_bucket_arn}/${local.droplet_prefix}*"
}

###############################################################################
# Pi-side IAM user.
###############################################################################

resource "aws_iam_user" "fluentbit_pi" {
  name = "${var.name_prefix}-fluentbit-pi"
  path = "/edge/"
  tags = merge(var.tags, { Role = "edge-shipper", Host = "pi" })
}

# Access key managed manually outside terraform — terraform import cannot
# recover the .secret after initial creation. Rotation runbook uses
# `aws iam create-access-key` + `aws iam delete-access-key` directly.
# See dashboard/docs/runbooks/edge-credential-rotation.md.

data "aws_iam_policy_document" "fluentbit_pi" {
  statement {
    sid       = "PiPutCowriePrefix"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = [local.pi_resource_arn]
  }
}

resource "aws_iam_user_policy" "fluentbit_pi" {
  name   = "${var.name_prefix}-fluentbit-pi-s3"
  user   = aws_iam_user.fluentbit_pi.name
  policy = data.aws_iam_policy_document.fluentbit_pi.json
}

###############################################################################
# Droplet-side IAM user.
###############################################################################

resource "aws_iam_user" "fluentbit_droplet" {
  name = "${var.name_prefix}-fluentbit-droplet"
  path = "/edge/"
  tags = merge(var.tags, { Role = "edge-shipper", Host = "droplet" })
}

data "aws_iam_policy_document" "fluentbit_droplet" {
  statement {
    sid       = "DropletPutHaproxyPrefix"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = [local.droplet_resource_arn]
  }
}

resource "aws_iam_user_policy" "fluentbit_droplet" {
  name   = "${var.name_prefix}-fluentbit-droplet-s3"
  user   = aws_iam_user.fluentbit_droplet.name
  policy = data.aws_iam_policy_document.fluentbit_droplet.json
}
