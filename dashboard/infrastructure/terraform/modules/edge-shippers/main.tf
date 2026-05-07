###############################################################################
# Edge log shippers — fluent-bit on Pi (Cowrie) + droplet (HAProxy).
#
# Per-host IAM users with PutObject scoped to their prefix only. SSM Parameter
# Store SecureString for the MaxMind license key. Two CloudWatch heartbeat
# alarms (one per source) fed by metric filters on the ingest Lambda's log
# group. SNS topic for alarm fan-out (subscribe an email manually after apply).
#
# Reference: ADR-010 (supersedes part of ADR-002).
###############################################################################

locals {
  pi_prefix      = "raw/cowrie/"
  droplet_prefix = "raw/haproxy/"

  pi_resource_arn      = "${var.ingest_bucket_arn}/${local.pi_prefix}*"
  droplet_resource_arn = "${var.ingest_bucket_arn}/${local.droplet_prefix}*"
}

###############################################################################
# IAM users + access keys + user policies for the Pi and droplet shippers
# moved to stacks/edge-shippers-credentials/ in Phase 11B-1 per ADR-011.
# This module keeps the SNS topic, heartbeat alarms, metric filters, and the
# MaxMind SSM parameter — all CI-deployable. The IAM user lifecycle is
# human-managed only.
#
# `local.pi_resource_arn` and `local.droplet_resource_arn` remain above as
# inert constants in case a future change wants to reference the same
# scoping; they cost nothing to leave in place.
###############################################################################

###############################################################################
# MaxMind GeoLite2 license key — SSM Parameter Store SecureString.
#
# Phase 10: consumed manually by `download_geolite2.sh` when the deployer
# rebuilds the layer. Future (Phase 9 or later): a scheduled refresher Lambda
# will read this and rotate the layer weekly. ADR-010 §Future work explains
# why SSM beats Secrets Manager today.
###############################################################################

resource "aws_ssm_parameter" "maxmind_license_key" {
  name        = "/${var.name_prefix}/maxmind/license_key"
  description = "MaxMind GeoLite2 license key. Used by download_geolite2.sh + (future) the scheduled GeoIP-refresher Lambda."
  type        = "SecureString"
  value       = var.maxmind_license_key
  tier        = "Standard"
  tags        = var.tags
}

###############################################################################
# SNS topic for edge-pipeline alarms (heartbeats below).
#
# When `alarm_topic_arn` is supplied, this module routes to it and skips
# creating its own. Otherwise a fresh topic is created with no subscriptions —
# subscribe an email manually after the first apply.
###############################################################################

resource "aws_sns_topic" "edge_alarms" {
  count = var.alarm_topic_arn == null ? 1 : 0
  name  = "${var.name_prefix}-edge-alarms"
  tags  = var.tags
}

locals {
  effective_alarm_topic_arn = var.alarm_topic_arn != null ? var.alarm_topic_arn : aws_sns_topic.edge_alarms[0].arn
}

###############################################################################
# Heartbeat metric filters + alarms.
#
# The ingest Lambda already logs structured `object_processed` lines that
# include the bucket key. Two metric filters count `object_processed` lines
# under each source prefix, producing two metrics. Two alarms fire when the
# count is zero over the heartbeat window.
#
# Why metric-filter-on-Lambda-log-group rather than CloudTrail S3 data events:
# data events run ~$0.10 per 100k events at the AWS object scale we operate;
# the Lambda already invokes per-object so the log-group filter is free
# beyond the existing log-ingestion costs.
###############################################################################

resource "aws_cloudwatch_log_metric_filter" "cowrie_objects" {
  name           = "${var.name_prefix}-cowrie-objects"
  log_group_name = var.ingest_log_group_name
  pattern        = "{ $.event = \"object_processed\" && $.key = \"raw/cowrie/*\" }"

  metric_transformation {
    name          = "CowrieObjectsProcessed"
    namespace     = "DramSoc/Edge"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_log_metric_filter" "haproxy_objects" {
  name           = "${var.name_prefix}-haproxy-objects"
  log_group_name = var.ingest_log_group_name
  pattern        = "{ $.event = \"object_processed\" && $.key = \"raw/haproxy/*\" }"

  metric_transformation {
    name          = "HaproxyObjectsProcessed"
    namespace     = "DramSoc/Edge"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "cowrie_heartbeat" {
  alarm_name          = "${var.name_prefix}-cowrie-heartbeat-missing"
  alarm_description   = "No new Cowrie objects ingested in the last ${var.heartbeat_period_minutes} minutes. Either fluent-bit on the Pi is wedged, the autossh tunnel is down, or no traffic is reaching Cowrie. ADR-010."
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "CowrieObjectsProcessed"
  namespace           = "DramSoc/Edge"
  period              = var.heartbeat_period_minutes * 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "breaching"
  alarm_actions       = [local.effective_alarm_topic_arn]
  ok_actions          = [local.effective_alarm_topic_arn]
  tags                = var.tags
}

resource "aws_cloudwatch_metric_alarm" "haproxy_heartbeat" {
  alarm_name          = "${var.name_prefix}-haproxy-heartbeat-missing"
  alarm_description   = "No new HAProxy objects ingested in the last ${var.heartbeat_period_minutes} minutes. fluent-bit on the droplet is wedged, the droplet is offline, or HAProxy isn't logging. Correlation breaks without this source. ADR-010."
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "HaproxyObjectsProcessed"
  namespace           = "DramSoc/Edge"
  period              = var.heartbeat_period_minutes * 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "breaching"
  alarm_actions       = [local.effective_alarm_topic_arn]
  ok_actions          = [local.effective_alarm_topic_arn]
  tags                = var.tags
}
