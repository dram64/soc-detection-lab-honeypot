variable "name_prefix" {
  description = "Resource name prefix."
  type        = string
  default     = "dram-soc"
}

variable "ingest_log_group_name" {
  description = "CloudWatch log group of the ingest Lambda. Used by the heartbeat metric filters that watch for `object_processed` log lines per source."
  type        = string
}

variable "alarm_topic_arn" {
  description = "Optional pre-existing SNS topic ARN to route alarm notifications to. When null, this module creates a topic named <name_prefix>-edge-alarms with no subscriptions; subscribe an email manually after apply."
  type        = string
  default     = null
}

variable "heartbeat_period_minutes" {
  description = "Window over which a missing source-prefix object trips the heartbeat alarm."
  type        = number
  default     = 15
}

variable "maxmind_license_key" {
  description = "MaxMind GeoLite2 license key. Stored in SSM Parameter Store SecureString. NEVER committed; pass via TF_VAR_maxmind_license_key. Empty default keeps `terraform plan` runnable in environments where the key isn't available; an empty-string apply will produce a no-op SSM parameter (refresh manually before relying on it)."
  type        = string
  default     = ""
  sensitive   = true
}

variable "tags" {
  type    = map(string)
  default = {}
}
