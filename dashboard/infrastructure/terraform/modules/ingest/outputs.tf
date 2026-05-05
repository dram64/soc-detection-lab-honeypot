output "ingest_bucket_name" {
  value = aws_s3_bucket.ingest.bucket
}

output "ingest_bucket_arn" {
  value = aws_s3_bucket.ingest.arn
}

output "ingest_function_name" {
  value = aws_lambda_function.ingest.function_name
}

output "ingest_function_arn" {
  value = aws_lambda_function.ingest.arn
}

output "ingest_dlq_name" {
  value = aws_sqs_queue.dlq.name
}

output "ingest_dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "ingest_log_group_name" {
  value = aws_cloudwatch_log_group.ingest.name
}

output "geolite2_layer_arn" {
  value = var.geolite2_layer_zip_path != null ? aws_lambda_layer_version.geolite2[0].arn : null
}
