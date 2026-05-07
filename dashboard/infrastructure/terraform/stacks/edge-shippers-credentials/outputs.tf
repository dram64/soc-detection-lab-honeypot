output "fluentbit_pi_user_name" {
  value = aws_iam_user.fluentbit_pi.name
}

output "fluentbit_droplet_user_name" {
  value = aws_iam_user.fluentbit_droplet.name
}
# Access keys are NOT outputted — they're manually managed via the
# rotation runbook (aws iam create-access-key / delete-access-key) and
# never exposed in terraform state. ADR-011.
