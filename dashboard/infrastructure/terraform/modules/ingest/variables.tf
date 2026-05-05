variable "name_prefix" {
  description = "Resource name prefix; PROJECT_PLAN.md §11 fixes this to 'dram-soc'."
  type        = string
  default     = "dram-soc"
}

variable "honeypot_table_name" {
  description = "Name of the dashboard's DynamoDB table (output of the dynamodb module)."
  type        = string
}

variable "honeypot_table_arn" {
  description = "ARN of the dashboard's DynamoDB table."
  type        = string
}

variable "ingest_zip_path" {
  description = "Path to the packaged ingest Lambda .zip. Built by ../../../scripts/package_lambdas.sh before terraform apply."
  type        = string
}

variable "geolite2_layer_zip_path" {
  description = "Path to the packaged GeoLite2 layer .zip (mmdb files). Optional during initial bring-up; alarms still fire if absent."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags applied to all created resources."
  type        = map(string)
  default     = {}
}
