variable "name_prefix" {
  description = "Resource name prefix."
  type        = string
  default     = "dram-soc"
}

variable "honeypot_table_name" {
  type = string
}

variable "honeypot_table_arn" {
  type = string
}

variable "api_zip_path" {
  type = string
}

variable "allowed_origin" {
  description = "DEPRECATED in Phase 8.5 — use allowed_origins. Kept for back-compat: when allowed_origins is empty, the module falls back to a single-element list of this value."
  type        = string
  default     = "https://dashboard.dram-soc.org"
}

variable "allowed_origins" {
  description = "CORS allow-list. Phase 8.5 added the apex + www origins alongside the dashboard subdomain. The Lambda echoes the request Origin if it's in this list; API GW preflight uses the same set."
  type        = list(string)
  default     = []
}

variable "git_sha" {
  description = "Git SHA surfaced via /api/healthz."
  type        = string
  default     = "dev"
}

variable "tags" {
  type    = map(string)
  default = {}
}
