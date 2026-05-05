output "table_name" {
  description = "Name of the created DynamoDB table."
  value       = aws_dynamodb_table.honeypot.name
}

output "table_arn" {
  description = "ARN of the created DynamoDB table."
  value       = aws_dynamodb_table.honeypot.arn
}

output "stream_arn" {
  description = "ARN of the table's DynamoDB Stream (NEW_IMAGE)."
  value       = aws_dynamodb_table.honeypot.stream_arn
}
