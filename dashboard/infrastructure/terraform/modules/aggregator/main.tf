locals {
  function_name  = "${var.name_prefix}-aggregator"
  dlq_name       = "${var.name_prefix}-aggregator-dlq"
  log_group_name = "/aws/lambda/${local.function_name}"
}

###############################################################################
# DLQ for the Streams Event Source Mapping (whole-batch failures).
###############################################################################

resource "aws_sqs_queue" "dlq" {
  name                      = local.dlq_name
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true
  tags                      = var.tags
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

resource "aws_iam_role" "aggregator" {
  name               = "${local.function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "aggregator_inline" {
  statement {
    sid    = "DDBHoneypotTable"
    effect = "Allow"
    actions = [
      "dynamodb:BatchWriteItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:Query",
      "dynamodb:GetItem",
      "dynamodb:DescribeTable",
    ]
    resources = [
      var.honeypot_table_arn,
      "${var.honeypot_table_arn}/index/*",
    ]
  }

  statement {
    sid    = "DDBStreamsRead"
    effect = "Allow"
    actions = [
      "dynamodb:DescribeStream",
      "dynamodb:GetRecords",
      "dynamodb:GetShardIterator",
      "dynamodb:ListStreams",
    ]
    resources = [var.honeypot_stream_arn]
  }

  statement {
    sid       = "DLQSend"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }

  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.aggregator.arn}:*"]
  }
}

resource "aws_iam_role_policy" "aggregator_inline" {
  name   = "${local.function_name}-inline"
  role   = aws_iam_role.aggregator.id
  policy = data.aws_iam_policy_document.aggregator_inline.json
}

###############################################################################
# Log group.
###############################################################################

resource "aws_cloudwatch_log_group" "aggregator" {
  name              = local.log_group_name
  retention_in_days = 14
  tags              = var.tags
}

###############################################################################
# Lambda function.
###############################################################################

resource "aws_lambda_function" "aggregator" {
  function_name    = local.function_name
  role             = aws_iam_role.aggregator.arn
  handler          = "functions.aggregator.handler.handler"
  runtime          = "python3.13"
  filename         = var.aggregator_zip_path
  source_code_hash = filebase64sha256(var.aggregator_zip_path)

  memory_size = 256
  timeout     = 60
  # No reserved_concurrent_executions: account quota at the 10-unit floor
  # forbids any positive reservation. See PROJECT_PLAN.md v1.3 changelog.

  environment {
    variables = {
      DDB_TABLE               = var.honeypot_table_name
      HOURLY_TTL_DAYS         = "60"
      RANK_TTL_HOURS          = "26"
      SUMMARY_TTL_DAYS        = "365"
      RANK_TOP_N              = "25"
      LOG_LEVEL               = "INFO"
      POWERTOOLS_SERVICE_NAME = "dram-soc-aggregator"
    }
  }

  tracing_config {
    mode = "PassThrough"
  }

  tags = var.tags

  depends_on = [aws_cloudwatch_log_group.aggregator]
}

###############################################################################
# DynamoDB Streams Event Source Mapping.
###############################################################################

resource "aws_lambda_event_source_mapping" "streams" {
  event_source_arn = var.honeypot_stream_arn
  function_name    = aws_lambda_function.aggregator.arn
  # TRIM_HORIZON: read from the oldest available record in the stream (24h
  # retention). LATEST silently drops records that are in-flight when the
  # ESM is created or recreated — see PHASE_3_LOG.md for the live race
  # condition that surfaced this.
  starting_position = "TRIM_HORIZON"

  batch_size                         = 100
  maximum_batching_window_in_seconds = 10
  parallelization_factor             = 1
  bisect_batch_on_function_error     = true
  maximum_retry_attempts             = 3
  maximum_record_age_in_seconds      = 3600

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.dlq.arn
    }
  }
}

###############################################################################
# EventBridge — rank rebuild every minute.
###############################################################################

resource "aws_cloudwatch_event_rule" "rank_rebuild" {
  name                = "${var.name_prefix}-rank-rebuild"
  description         = "Trigger aggregator rank rebuild every 60 seconds (PROJECT_PLAN.md §4)"
  schedule_expression = "rate(1 minute)"
  tags                = var.tags
}

resource "aws_cloudwatch_event_target" "rank_rebuild" {
  rule      = aws_cloudwatch_event_rule.rank_rebuild.name
  target_id = "aggregator-rank-rebuild"
  arn       = aws_lambda_function.aggregator.arn
  input     = jsonencode({ action = "rank_rebuild" })
}

resource "aws_lambda_permission" "rank_rebuild" {
  statement_id  = "AllowExecutionFromEventBridgeRankRebuild"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.aggregator.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.rank_rebuild.arn
}

###############################################################################
# EventBridge — daily summary at 00:05 UTC.
###############################################################################

resource "aws_cloudwatch_event_rule" "daily_summary" {
  name                = "${var.name_prefix}-daily-summary"
  description         = "Trigger daily summary rebuild at 00:05 UTC each day"
  schedule_expression = "cron(5 0 * * ? *)"
  tags                = var.tags
}

resource "aws_cloudwatch_event_target" "daily_summary" {
  rule      = aws_cloudwatch_event_rule.daily_summary.name
  target_id = "aggregator-daily-summary"
  arn       = aws_lambda_function.aggregator.arn
  input     = jsonencode({ action = "daily_summary" })
}

resource "aws_lambda_permission" "daily_summary" {
  statement_id  = "AllowExecutionFromEventBridgeDailySummary"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.aggregator.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_summary.arn
}

###############################################################################
# Alarms.
###############################################################################

resource "aws_cloudwatch_metric_alarm" "errors" {
  alarm_name          = "${local.function_name}-errors"
  alarm_description   = "Aggregator Lambda errors > 0 over 5 minutes."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions = {
    FunctionName = aws_lambda_function.aggregator.function_name
  }
  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "throttles" {
  alarm_name          = "${local.function_name}-throttles"
  alarm_description   = "Aggregator Lambda throttles > 0 over 5 minutes."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions = {
    FunctionName = aws_lambda_function.aggregator.function_name
  }
  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "duration_p95" {
  alarm_name          = "${local.function_name}-duration-p95"
  alarm_description   = "Aggregator Lambda p95 duration > 30s — investigate."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  extended_statistic  = "p95"
  threshold           = 30000
  treat_missing_data  = "notBreaching"
  dimensions = {
    FunctionName = aws_lambda_function.aggregator.function_name
  }
  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "iterator_age" {
  alarm_name          = "${local.function_name}-iterator-age"
  alarm_description   = "DynamoDB Stream iterator age > 60s — aggregator is falling behind."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "IteratorAge"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Maximum"
  threshold           = 60000
  treat_missing_data  = "notBreaching"
  dimensions = {
    FunctionName = aws_lambda_function.aggregator.function_name
  }
  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  alarm_name          = "${local.function_name}-dlq-depth"
  alarm_description   = "Aggregator ESM-side failures landing in the DLQ."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions = {
    QueueName = aws_sqs_queue.dlq.name
  }
  tags = var.tags
}
