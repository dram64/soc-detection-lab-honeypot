output "honeypot_table_name" {
  description = "DynamoDB table for raw events + aggregates."
  value       = module.honeypot_table.table_name
}

output "honeypot_table_arn" {
  value = module.honeypot_table.table_arn
}

output "honeypot_stream_arn" {
  description = "Stream ARN — wired to the aggregator Lambda in Phase 3."
  value       = module.honeypot_table.stream_arn
}

output "ingest_bucket_name" {
  description = "S3 bucket where the Pi shipper PUTs gzipped Cowrie events."
  value       = module.ingest.ingest_bucket_name
}

output "ingest_function_name" {
  value = module.ingest.ingest_function_name
}

output "ingest_dlq_url" {
  value = module.ingest.ingest_dlq_url
}

output "aggregator_function_name" {
  value = module.aggregator.aggregator_function_name
}

output "aggregator_dlq_url" {
  value = module.aggregator.aggregator_dlq_url
}

output "rank_rebuild_rule_arn" {
  value = module.aggregator.rank_rebuild_rule_arn
}

output "api_function_name" {
  value = module.api.api_function_name
}

output "api_endpoint" {
  description = "Invoke this for live testing: <api_endpoint>/api/healthz"
  value       = module.api.api_endpoint
}

output "frontend_bucket_name" {
  description = "S3 bucket holding the production dashboard bundle."
  value       = module.hosting.frontend_bucket_name
}

output "cloudfront_distribution_id" {
  value = module.hosting.cloudfront_distribution_id
}

output "cloudfront_domain_name" {
  description = "Cloudflare CNAME target. dashboard.dram-soc.org -> this."
  value       = module.hosting.cloudfront_domain_name
}

output "acm_certificate_arn" {
  value = module.hosting.acm_certificate_arn
}

output "acm_validation_record" {
  description = "Add this CNAME in Cloudflare DNS-only (grey cloud) to validate the ACM cert."
  value       = module.hosting.acm_validation_record
}

###############################################################################
# Phase 10 — edge shippers (Pi + droplet).
###############################################################################

output "fluentbit_pi_credentials" {
  description = "Pi-side fluent-bit credentials. Copy to /etc/fluent-bit/aws-credentials on the Pi (mode 0600)."
  value       = module.edge_shippers.fluentbit_pi_credentials
  sensitive   = true
}

output "fluentbit_droplet_credentials" {
  description = "Droplet-side fluent-bit credentials. Copy to /etc/fluent-bit/aws-credentials on the droplet (mode 0600)."
  value       = module.edge_shippers.fluentbit_droplet_credentials
  sensitive   = true
}

output "edge_alarm_topic_arn" {
  description = "SNS topic for Pi/droplet heartbeat alarms. Subscribe an email after first apply."
  value       = module.edge_shippers.edge_alarm_topic_arn
}

output "maxmind_ssm_parameter_name" {
  value = module.edge_shippers.maxmind_ssm_parameter_name
}
