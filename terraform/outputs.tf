output "cloudfront_domain" {
  description = "Live URL until the custom domain is pointed at it (and the CNAME target for Namecheap)"
  value       = aws_cloudfront_distribution.app.domain_name
}

output "custom_domain_url" {
  value = local.custom_domain ? "https://${var.domain_name}" : ""
}

output "acm_validation_record" {
  description = "Add this CNAME at Namecheap (Host = name without .moshikseetloo.com) so the certificate can be issued"
  value = local.custom_domain ? [
    for o in aws_acm_certificate.site[0].domain_validation_options : {
      type  = o.resource_record_type
      name  = o.resource_record_name
      value = o.resource_record_value
    }
  ] : []
}

output "lambda_function_name" {
  description = "Store as the LAMBDA_FUNCTION_NAME secret in GitHub"
  value       = aws_lambda_function.app.function_name
}

output "github_deploy_role_arn" {
  description = "Store as the AWS_DEPLOY_ROLE_ARN secret in GitHub"
  value       = aws_iam_role.github_deploy.arn
}

output "data_bucket" {
  value = aws_s3_bucket.data.id
}
