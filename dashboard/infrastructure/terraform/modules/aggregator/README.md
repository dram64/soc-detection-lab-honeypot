# Terraform module: aggregator

Phase 3 of the dashboard build. Provisions the aggregator Lambda + DynamoDB Streams ESM + EventBridge schedules.

## Resources

- `aws_lambda_function.aggregator` — `dram-soc-aggregator` (Python 3.13, 256 MB, 60s timeout, no reserved concurrency)
- `aws_iam_role.aggregator` — minimum permissions: DDB read/write on the honeypot table + index/*; DDB Streams read on the table's stream; SQS SendMessage on the DLQ; CloudWatch Logs.
- `aws_cloudwatch_log_group.aggregator` — 14-day retention
- `aws_sqs_queue.dlq` — `dram-soc-aggregator-dlq` (separate from Phase 2's ingest DLQ)
- `aws_lambda_event_source_mapping.streams` — DynamoDB Streams → aggregator. BatchSize=100, MaxBatchingWindow=10s, ParallelizationFactor=1, BisectBatchOnFunctionError=true, MaxRetries=3, OnFailure → DLQ.
- `aws_cloudwatch_event_rule.rank_rebuild` — `rate(1 minute)` → invoke aggregator with `{"action": "rank_rebuild"}`
- `aws_cloudwatch_event_rule.daily_summary` — `cron(5 0 * * ? *)` → invoke aggregator with `{"action": "daily_summary"}`
- 5 CloudWatch alarms — errors, throttles, p95 duration, iterator-age, DLQ depth

## Inputs

See [variables.tf](variables.tf). The module needs the DynamoDB table's name + ARN and the stream ARN, which are outputs of the `dynamodb` module.

## Outputs

See [outputs.tf](outputs.tf).
