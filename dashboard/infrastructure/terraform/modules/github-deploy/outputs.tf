output "role_arn" {
  description = "ARN of the dram-soc-github-deploy IAM role. Use as AWS_ROLE_ARN in GitHub Actions workflows."
  value       = aws_iam_role.deploy.arn
}

output "role_name" {
  value = aws_iam_role.deploy.name
}

output "oidc_provider_arn" {
  description = "ARN of the (Diamond-IQ-owned) GitHub Actions OIDC provider this role's trust policy depends on."
  value       = data.aws_iam_openid_connect_provider.github.arn
}
