variable "name_prefix" {
  description = "Resource name prefix; PROJECT_PLAN.md fixes this to 'dram-soc'."
  type        = string
  default     = "dram-soc"
}

variable "honeypot_table_name" {
  description = "DynamoDB table name (output of the dynamodb module)."
  type        = string
}

variable "honeypot_table_arn" {
  description = "DynamoDB table ARN."
  type        = string
}

variable "honeypot_stream_arn" {
  description = "DynamoDB Streams ARN (NEW_IMAGE)."
  type        = string
}

variable "aggregator_zip_path" {
  description = "Path to the packaged aggregator Lambda .zip."
  type        = string
}

variable "tags" {
  description = "Tags applied to all created resources."
  type        = map(string)
  default     = {}
}
