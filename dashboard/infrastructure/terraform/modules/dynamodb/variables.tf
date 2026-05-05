variable "table_name" {
  description = "DynamoDB table name (must be unique per account/region)."
  type        = string
}

variable "deletion_protection" {
  description = "Enable deletion protection. Should be true in production."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags applied to the table. Project / Component tags should always be included."
  type        = map(string)
  default     = {}
}
