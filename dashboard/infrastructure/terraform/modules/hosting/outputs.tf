output "frontend_bucket_name" {
  description = "S3 bucket holding the production frontend bundle. Deploy script syncs into this."
  value       = aws_s3_bucket.frontend.id
}

output "frontend_bucket_arn" {
  value = aws_s3_bucket.frontend.arn
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID. Deploy script invalidates against this."
  value       = aws_cloudfront_distribution.frontend.id
}

output "cloudfront_domain_name" {
  description = "CloudFront origin domain. Cloudflare CNAME points dashboard.dram-soc.org at this."
  value       = aws_cloudfront_distribution.frontend.domain_name
}

output "cloudfront_arn" {
  value = aws_cloudfront_distribution.frontend.arn
}

output "acm_certificate_arn" {
  value = aws_acm_certificate.dashboard.arn
}

# Surface the DNS validation record for ACM. The user adds this to Cloudflare
# (DNS-only / grey cloud) before the validation resource finishes.
output "acm_validation_record" {
  description = "CNAME record to add to Cloudflare DNS-only (grey cloud) for ACM cert validation."
  value = {
    for dvo in aws_acm_certificate.dashboard.domain_validation_options : dvo.domain_name => {
      name  = dvo.resource_record_name
      type  = dvo.resource_record_type
      value = dvo.resource_record_value
    }
  }
}

output "billing_alarm_name" {
  value = aws_cloudwatch_metric_alarm.billing.alarm_name
}
