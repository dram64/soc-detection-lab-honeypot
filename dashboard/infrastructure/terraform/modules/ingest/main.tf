locals {
  function_name      = "${var.name_prefix}-ingest"
  bucket_name        = "${var.name_prefix}-honeypot-ingest"
  dlq_name           = "${var.name_prefix}-ingest-dlq"
  layer_name         = "${var.name_prefix}-geolite2"
  log_group_name     = "/aws/lambda/${local.function_name}"
  package_path       = "${path.module}/build/ingest.zip"
  layer_package_path = "${path.module}/build/geolite2-layer.zip"
}

###############################################################################
# Ingest S3 bucket — Cowrie events land here as gzipped NDJSON.
###############################################################################

resource "aws_s3_bucket" "ingest" {
  bucket        = local.bucket_name
  force_destroy = false
  tags          = var.tags
}

resource "aws_s3_bucket_versioning" "ingest" {
  bucket = aws_s3_bucket.ingest.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ingest" {
  bucket = aws_s3_bucket.ingest.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "ingest" {
  bucket                  = aws_s3_bucket.ingest.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "ingest" {
  bucket = aws_s3_bucket.ingest.id

  rule {
    id     = "raw-events-lifecycle"
    status = "Enabled"

    filter {
      prefix = "raw/"
    }

    transition {
      days          = 30
      storage_class = "GLACIER"
    }

    expiration {
      days = 90
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

###############################################################################
# Dead-letter queue for whole-object ingest failures.
###############################################################################

resource "aws_sqs_queue" "dlq" {
  name                      = local.dlq_name
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true
  tags                      = var.tags
}

###############################################################################
# Lambda execution role — minimum permissions per PROJECT_PLAN.md §10.
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

resource "aws_iam_role" "ingest" {
  name               = "${local.function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "ingest_inline" {
  statement {
    sid       = "S3ReadIngestRawPrefix"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.ingest.arn}/raw/*"]
  }

  statement {
    sid    = "DDBWriteHoneypotTable"
    effect = "Allow"
    actions = [
      "dynamodb:BatchWriteItem",
      "dynamodb:PutItem",
      "dynamodb:Query",
      # UpdateItem is needed for the Phase 10 backward correlation pass
      # (handler._backward_correlate). The conditional update is the
      # bidirectional half of timestamp-window correlation per ADR-010.
      "dynamodb:UpdateItem",
    ]
    resources = [
      var.honeypot_table_arn,
      "${var.honeypot_table_arn}/index/*",
    ]
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
    resources = ["${aws_cloudwatch_log_group.ingest.arn}:*"]
  }
}

resource "aws_iam_role_policy" "ingest_inline" {
  name   = "${local.function_name}-inline"
  role   = aws_iam_role.ingest.id
  policy = data.aws_iam_policy_document.ingest_inline.json
}

###############################################################################
# CloudWatch log group with explicit retention (14 d per §9 cost control).
###############################################################################

resource "aws_cloudwatch_log_group" "ingest" {
  name              = local.log_group_name
  retention_in_days = 14
  tags              = var.tags
}

###############################################################################
# GeoLite2 Lambda layer.
#
# .mmdb files are fetched by `download_geolite2.sh` before terraform apply.
# We assert they exist via a data source rather than embedding them in git.
###############################################################################

resource "aws_lambda_layer_version" "geolite2" {
  count               = var.geolite2_layer_zip_path != null ? 1 : 0
  layer_name          = local.layer_name
  filename            = var.geolite2_layer_zip_path
  source_code_hash    = filebase64sha256(var.geolite2_layer_zip_path)
  compatible_runtimes = ["python3.13"]
  description         = "MaxMind GeoLite2 Country + ASN .mmdb files. Refresh quarterly via download_geolite2.sh; Phase 9 automates."
}

###############################################################################
# Ingest Lambda.
###############################################################################

resource "aws_lambda_function" "ingest" {
  function_name    = local.function_name
  role             = aws_iam_role.ingest.arn
  handler          = "functions.ingest.handler.handler"
  runtime          = "python3.13"
  filename         = var.ingest_zip_path
  source_code_hash = filebase64sha256(var.ingest_zip_path)

  memory_size = 256
  timeout     = 60

  layers = compact([
    var.geolite2_layer_zip_path != null ? aws_lambda_layer_version.geolite2[0].arn : null,
  ])

  environment {
    variables = {
      DDB_TABLE               = var.honeypot_table_name
      RAW_TTL_DAYS            = "90"
      SENSOR_NAME             = "honeypot"
      LOG_LEVEL               = "INFO"
      POWERTOOLS_SERVICE_NAME = "dram-soc-ingest"
    }
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.dlq.arn
  }

  tracing_config {
    mode = "PassThrough"
  }

  tags = var.tags

  depends_on = [aws_cloudwatch_log_group.ingest]
}

###############################################################################
# S3 → Lambda event notification.
###############################################################################

resource "aws_lambda_permission" "s3_invoke" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.ingest.arn
}

resource "aws_s3_bucket_notification" "ingest" {
  bucket = aws_s3_bucket.ingest.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.ingest.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "raw/"
    filter_suffix       = ".json.gz"
  }

  depends_on = [aws_lambda_permission.s3_invoke]
}

###############################################################################
# CloudWatch alarms (PROJECT_PLAN.md §9 / §11 Phase 9).
###############################################################################

resource "aws_cloudwatch_metric_alarm" "errors" {
  alarm_name          = "${local.function_name}-errors"
  alarm_description   = "Ingest Lambda errors > 0 over 5 minutes."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions = {
    FunctionName = aws_lambda_function.ingest.function_name
  }
  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "throttles" {
  alarm_name          = "${local.function_name}-throttles"
  alarm_description   = "Ingest Lambda throttle invocations > 0 over 5 minutes."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions = {
    FunctionName = aws_lambda_function.ingest.function_name
  }
  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "duration_p95" {
  alarm_name          = "${local.function_name}-duration-p95"
  alarm_description   = "Ingest Lambda p95 duration > 30s — investigate before timeout."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  extended_statistic  = "p95"
  threshold           = 30000
  treat_missing_data  = "notBreaching"
  dimensions = {
    FunctionName = aws_lambda_function.ingest.function_name
  }
  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  alarm_name          = "${local.function_name}-dlq-depth"
  alarm_description   = "Whole-object ingest failures landing in the DLQ."
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
