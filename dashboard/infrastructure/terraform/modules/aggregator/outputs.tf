output "aggregator_function_name" {
  value = aws_lambda_function.aggregator.function_name
}

output "aggregator_function_arn" {
  value = aws_lambda_function.aggregator.arn
}

output "aggregator_dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "aggregator_log_group_name" {
  value = aws_cloudwatch_log_group.aggregator.name
}

output "rank_rebuild_rule_arn" {
  value = aws_cloudwatch_event_rule.rank_rebuild.arn
}

output "daily_summary_rule_arn" {
  value = aws_cloudwatch_event_rule.daily_summary.arn
}

output "stream_event_source_mapping_uuid" {
  value = aws_lambda_event_source_mapping.streams.uuid
}
