# ============ Custom domain (DNS at Namecheap) ============
# Two records are added at Namecheap by hand:
#   1. the certificate's validation CNAME (acm_validation_record output)
#   2. a CNAME from the subdomain to the CloudFront domain (cloudfront_domain output)
# First apply only the certificate:  terraform apply -target=aws_acm_certificate.site
# then add record 1 at Namecheap, then run a normal terraform apply.

resource "aws_acm_certificate" "site" {
  count             = local.custom_domain ? 1 : 0
  provider          = aws.us_east_1
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "site" {
  count           = local.custom_domain ? 1 : 0
  provider        = aws.us_east_1
  certificate_arn = aws_acm_certificate.site[0].arn

  timeouts {
    create = "30m"
  }
}
