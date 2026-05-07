variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "name_prefix" {
  type    = string
  default = "dram-soc"
}

variable "ingest_bucket_arn" {
  description = "ARN of the dram-soc-honeypot-ingest bucket. Used to scope per-host PutObject grants. Hardcoded default since this stack is purpose-built for the SOC dashboard."
  type        = string
  default     = "arn:aws:s3:::dram-soc-honeypot-ingest"
}

variable "tags" {
  type = map(string)
  default = {
    Project     = "soc-detection-lab"
    Component   = "dashboard"
    Environment = "dev"
    ManagedBy   = "terraform"
    Stack       = "edge-shippers-credentials"
  }
}
