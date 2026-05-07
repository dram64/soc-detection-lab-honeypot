# Phase 11B-1 + ADR-011: IAM user + access-key outputs moved to
# stacks/edge-shippers-credentials/. This module no longer surfaces
# any credential values; it owns only CI-deployable infrastructure.

output "maxmind_ssm_parameter_name" {
  description = "SSM Parameter Store path holding the MaxMind license key. Read from the deployer machine via `aws ssm get-parameter --name <this> --with-decryption`."
  value       = aws_ssm_parameter.maxmind_license_key.name
}

output "edge_alarm_topic_arn" {
  description = "SNS topic alarms publish to. Subscribe an email/Slack/PagerDuty endpoint to it after first apply."
  value       = local.effective_alarm_topic_arn
}

output "cowrie_heartbeat_alarm_name" {
  value = aws_cloudwatch_metric_alarm.cowrie_heartbeat.alarm_name
}

output "haproxy_heartbeat_alarm_name" {
  value = aws_cloudwatch_metric_alarm.haproxy_heartbeat.alarm_name
}
