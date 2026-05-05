locals {
  function_name  = "${var.name_prefix}-api"
  log_group_name = "/aws/lambda/${local.function_name}"
  # Prefer the list-typed allowed_origins; fall back to the legacy
  # single-string allowed_origin for back-compat.
  cors_origins = length(var.allowed_origins) > 0 ? var.allowed_origins : [var.allowed_origin]
}

###############################################################################
# Execution role.
###############################################################################

data "aws_iam_policy_document" "assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api" {
  name               = "${local.function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "api_inline" {
  statement {
    sid    = "DDBReadOnly"
    effect = "Allow"
    actions = [
      "dynamodb:Query",
      "dynamodb:GetItem",
    ]
    resources = [
      var.honeypot_table_arn,
      "${var.honeypot_table_arn}/index/*",
    ]
  }

  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.api.arn}:*"]
  }
}

resource "aws_iam_role_policy" "api_inline" {
  name   = "${local.function_name}-inline"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api_inline.json
}

###############################################################################
# Log group.
###############################################################################

resource "aws_cloudwatch_log_group" "api" {
  name              = local.log_group_name
  retention_in_days = 14
  tags              = var.tags
}

###############################################################################
# Lambda function.
###############################################################################

resource "aws_lambda_function" "api" {
  function_name    = local.function_name
  role             = aws_iam_role.api.arn
  handler          = "functions.api.handler.handler"
  runtime          = "python3.13"
  filename         = var.api_zip_path
  source_code_hash = filebase64sha256(var.api_zip_path)

  memory_size = 256
  timeout     = 30
  # No reserved_concurrent_executions: account quota at floor (PROJECT_PLAN v1.3).

  environment {
    variables = {
      DDB_TABLE = var.honeypot_table_name
      # ALLOWED_ORIGIN is a comma-separated allowlist. The Lambda parses
      # it, then echoes the request's Origin header back if it's in the
      # list (handler.py: ALLOWED_ORIGINS / _select_origin).
      ALLOWED_ORIGIN          = join(",", local.cors_origins)
      GIT_SHA                 = var.git_sha
      LOG_LEVEL               = "INFO"
      POWERTOOLS_SERVICE_NAME = "dram-soc-api"
    }
  }

  tracing_config {
    mode = "PassThrough"
  }

  tags = var.tags

  depends_on = [aws_cloudwatch_log_group.api]
}

###############################################################################
# HTTP API Gateway.
###############################################################################

resource "aws_apigatewayv2_api" "api" {
  name          = "${var.name_prefix}-api"
  protocol_type = "HTTP"
  description   = "Dashboard public read-only API (PROJECT_PLAN.md §5)"

  cors_configuration {
    allow_origins  = local.cors_origins
    allow_methods  = ["GET", "OPTIONS"]
    allow_headers  = ["Content-Type"]
    expose_headers = ["Cache-Control"]
    max_age        = 300
  }

  tags = var.tags
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}

# All 8 routes per PROJECT_PLAN.md §5.
locals {
  routes = [
    "GET /api/healthz",
    "GET /api/summary",
    "GET /api/timeline",
    "GET /api/top/{dimension}",
    "GET /api/events",
    "GET /api/breakdown",
    "GET /api/sessions/{id}",
  ]
}

resource "aws_apigatewayv2_route" "routes" {
  for_each  = toset(local.routes)
  api_id    = aws_apigatewayv2_api.api.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 500
    throttling_rate_limit  = 100
  }

  tags = var.tags
}

resource "aws_lambda_permission" "apigw_invoke" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}

###############################################################################
# Alarms.
###############################################################################

resource "aws_cloudwatch_metric_alarm" "errors" {
  alarm_name          = "${local.function_name}-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions = {
    FunctionName = aws_lambda_function.api.function_name
  }
  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "throttles" {
  alarm_name          = "${local.function_name}-throttles"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions = {
    FunctionName = aws_lambda_function.api.function_name
  }
  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "duration_p95" {
  alarm_name          = "${local.function_name}-duration-p95"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  extended_statistic  = "p95"
  threshold           = 5000
  treat_missing_data  = "notBreaching"
  dimensions = {
    FunctionName = aws_lambda_function.api.function_name
  }
  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${local.function_name}-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "5xx"
  namespace           = "AWS/ApiGateway"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions = {
    ApiId = aws_apigatewayv2_api.api.id
    Stage = aws_apigatewayv2_stage.default.name
  }
  tags = var.tags
}

###############################################################################
# password_raw leak guard — defense in depth.
#
# The API Lambda never logs raw item payloads. If the literal string
# `password_raw` ever appears in a log line, something is wrong: alarm.
###############################################################################

resource "aws_cloudwatch_log_metric_filter" "password_raw_leak" {
  name           = "${local.function_name}-password-raw-leak"
  pattern        = "password_raw"
  log_group_name = aws_cloudwatch_log_group.api.name

  metric_transformation {
    name      = "PasswordRawLogMatches"
    namespace = "DramSoc/Api"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "password_raw_leak" {
  alarm_name          = "${local.function_name}-password-raw-leak"
  alarm_description   = "ADR-005 boundary breach: literal 'password_raw' appeared in API logs."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "PasswordRawLogMatches"
  namespace           = "DramSoc/Api"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  tags                = var.tags
}
