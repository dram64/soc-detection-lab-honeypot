# Terraform module: api

Phase 4 — public read-only HTTP API for the dashboard.

## Resources

- `aws_lambda_function.api` — `dram-soc-api` (Python 3.13, 256 MB, 30 s)
- `aws_iam_role.api` + inline policy — `dynamodb:Query`/`GetItem` on the table + GSIs (read-only)
- `aws_cloudwatch_log_group.api` (14d retention)
- `aws_apigatewayv2_api.api` — HTTP API with CORS scoped to `var.allowed_origin`
- `aws_apigatewayv2_integration.api` — AWS_PROXY → Lambda
- `aws_apigatewayv2_route.routes` — 7 routes (PROJECT_PLAN.md §5)
- `aws_apigatewayv2_stage.default` — `$default` with 100 RPS / 500 burst throttle
- `aws_lambda_permission.apigw_invoke`
- 4 CloudWatch alarms — errors, throttles, p95 duration, API GW 5xx
- `aws_cloudwatch_log_metric_filter.password_raw_leak` + alarm — defense-in-depth for ADR-005
