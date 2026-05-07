variable "github_repo" {
  description = "GitHub repository (owner/name) authorized to assume the deploy role. Pinned in Phase 11B-1 — this module is purpose-built for the SOC honeypot dashboard, not a reusable component."
  type        = string
  default     = "dram64/soc-detection-lab-honeypot"
}

variable "role_name" {
  description = "Name of the GitHub Actions deploy IAM role."
  type        = string
  default     = "dram-soc-github-deploy"
}

variable "name_prefix" {
  description = "Project name prefix used for ARN scoping. Matches all SOC dashboard resources (dram-soc-honeypot, dram-soc-ingest, etc.)."
  type        = string
  default     = "dram-soc"
}

variable "account_id" {
  description = "AWS account id (for IAM ARN construction)."
  type        = string
}

variable "aws_region" {
  description = "AWS region (for ARN construction)."
  type        = string
  default     = "us-east-1"
}

variable "state_bucket_name" {
  description = "Name of the Terraform state bucket the deploy role can read/write. Same bucket Diamond IQ uses; the lock table is also shared."
  type        = string
  default     = "diamond-iq-tfstate-334856751632"
}

variable "lock_table_name" {
  description = "Name of the Terraform lock table the deploy role can access."
  type        = string
  default     = "diamond-iq-tfstate-locks"
}

variable "tags" {
  type    = map(string)
  default = {}
}
