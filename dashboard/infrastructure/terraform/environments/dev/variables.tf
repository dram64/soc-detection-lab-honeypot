variable "aws_region" {
  description = "Primary AWS region for the dashboard. PROJECT_PLAN.md fixes this to us-east-1."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Resource name prefix. PROJECT_PLAN.md §11 fixes this to 'dram-soc-'."
  type        = string
  default     = "dram-soc"
}

variable "environment" {
  description = "Environment label (dev / prod). Used in tags only — single-environment v1."
  type        = string
  default     = "dev"
}

variable "ingest_zip_path" {
  description = "Path to the packaged ingest Lambda .zip. See dashboard/scripts/package_lambdas.sh."
  type        = string
  default     = "../../modules/ingest/build/ingest.zip"
}

variable "geolite2_layer_zip_path" {
  description = "Path to the GeoLite2 layer .zip. Optional; absent during initial bring-up."
  type        = string
  default     = null
}

variable "aggregator_zip_path" {
  description = "Path to the packaged aggregator Lambda .zip."
  type        = string
  default     = "../../modules/aggregator/build/aggregator.zip"
}

variable "api_zip_path" {
  description = "Path to the packaged api Lambda .zip."
  type        = string
  default     = "../../modules/api/build/api.zip"
}

variable "allowed_origin" {
  description = "DEPRECATED in Phase 8.5 — use allowed_origins."
  type        = string
  default     = "https://dashboard.dram-soc.org"
}

variable "allowed_origins" {
  description = "CORS allow-list for the API. Phase 8.5: dashboard subdomain + apex + www."
  type        = list(string)
  default = [
    "https://dashboard.dram-soc.org",
    "https://dram-soc.org",
    "https://www.dram-soc.org",
  ]
}

variable "git_sha" {
  description = "Git SHA surfaced via /api/healthz."
  type        = string
  default     = "phase-4-dev"
}

variable "domain_name" {
  description = "Public hostname served by CloudFront. Phase 8."
  type        = string
  default     = "dashboard.dram-soc.org"
}

variable "billing_alarm_threshold_usd" {
  description = "Account-wide CloudWatch billing alarm threshold (USD)."
  type        = number
  default     = 10
}
