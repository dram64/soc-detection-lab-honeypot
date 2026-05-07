output "fluentbit_pi_user_name" {
  value = aws_iam_user.fluentbit_pi.name
}

output "fluentbit_pi_credentials" {
  description = "Pi-side fluent-bit AWS credentials. Copy onto the Pi at /etc/fluent-bit/aws-credentials (mode 0600). Format ready for the AWS shared-credentials file."
  value       = <<-EOT
    [default]
    aws_access_key_id = ${aws_iam_access_key.fluentbit_pi.id}
    aws_secret_access_key = ${aws_iam_access_key.fluentbit_pi.secret}
  EOT
  sensitive   = true
}

output "fluentbit_droplet_user_name" {
  value = aws_iam_user.fluentbit_droplet.name
}

output "fluentbit_droplet_credentials" {
  description = "Droplet-side fluent-bit AWS credentials. Copy onto the droplet at /etc/fluent-bit/aws-credentials (mode 0600)."
  value       = <<-EOT
    [default]
    aws_access_key_id = ${aws_iam_access_key.fluentbit_droplet.id}
    aws_secret_access_key = ${aws_iam_access_key.fluentbit_droplet.secret}
  EOT
  sensitive   = true
}

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
