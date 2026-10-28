variable "name_prefix" {
  description = "Resource name prefix. PROJECT_PLAN.md §11 fixes this to 'dram-soc'."
  type        = string
  default     = "dram-soc"
}

variable "domain_name" {
  description = "Primary hostname served by CloudFront. Must match the ACM cert subject."
  type        = string
  default     = "dashboard.dram-soc.org"
}

variable "apex_domain_name" {
  description = "Phase 8.5 apex hostname (`dram-soc.org`). Added to the ACM cert as a SAN; Cloudflare CNAME-flatten points it at the same CloudFront distribution."
  type        = string
  default     = "dram-soc.org"
}

variable "www_domain_name" {
  description = "Phase 8.5 www hostname (`www.dram-soc.org`). Added to the ACM cert as a SAN."
  type        = string
  default     = "www.dram-soc.org"
}

variable "billing_alarm_threshold_usd" {
  description = "CloudWatch billing alarm threshold in USD. Phase 8: $10/month."
  type        = number
  default     = 10
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "extra_reader_distribution_arns" {
  description = "Other CloudFront distributions allowed to read the bucket through OAC. The desiramirez.com distribution (showcase repo, infra/site_domain.tf) serves apex/ from here."
  type        = list(string)
  default     = []
}

variable "apex_redirect_to" {
  description = "Origin that apex and www requests are 301-redirected to, path and query kept. The apex page moved to desiramirez.com."
  type        = string
  default     = "https://desiramirez.com"
}
