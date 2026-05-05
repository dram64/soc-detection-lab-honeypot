output "api_function_name" {
  value = aws_lambda_function.api.function_name
}

output "api_function_arn" {
  value = aws_lambda_function.api.arn
}

output "api_endpoint" {
  description = "Invoke URL for the HTTP API. Append /api/healthz to test."
  value       = aws_apigatewayv2_api.api.api_endpoint
}

output "api_log_group_name" {
  value = aws_cloudwatch_log_group.api.name
}
