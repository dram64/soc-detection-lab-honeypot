###############################################################################
# DynamoDB single-table for the Honeypot Visualizer Dashboard
#
# Schema authority: PROJECT_PLAN.md §4 + dashboard/docs/adr/003-single-table-design.md
#
# - Single table, on-demand capacity
# - 3 GSIs (by IP, by day-bucket, by rank) all projecting ALL
# - Streams: NEW_IMAGE for the aggregator Lambda
# - PITR: ON
# - TTL on `ttl` attribute (raw events expire at 90 days)
###############################################################################

resource "aws_dynamodb_table" "honeypot" {
  name         = var.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  attribute {
    name = "gsi1pk"
    type = "S"
  }

  attribute {
    name = "gsi1sk"
    type = "S"
  }

  attribute {
    name = "gsi2pk"
    type = "S"
  }

  attribute {
    name = "gsi2sk"
    type = "S"
  }

  attribute {
    name = "gsi3pk"
    type = "S"
  }

  attribute {
    name = "gsi3sk"
    type = "S"
  }

  global_secondary_index {
    name            = "gsi1"
    hash_key        = "gsi1pk"
    range_key       = "gsi1sk"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "gsi2"
    hash_key        = "gsi2pk"
    range_key       = "gsi2sk"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "gsi3"
    hash_key        = "gsi3pk"
    range_key       = "gsi3sk"
    projection_type = "ALL"
  }

  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"

  point_in_time_recovery {
    enabled = true
  }

  ttl {
    enabled        = true
    attribute_name = "ttl"
  }

  server_side_encryption {
    enabled = true
  }

  deletion_protection_enabled = var.deletion_protection

  tags = var.tags
}
