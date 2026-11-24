# ============ CloudFront in front of the function URL ============
# Adds the origin secret, serves the custom domain, never caches.

# CloudFront only forwards the viewer's Authorization header (the site's Basic
# Auth login) on GET/HEAD if it's part of the cache key, which the managed
# CachingDisabled policy can't do. So: a policy that keys on Authorization but
# keeps TTLs at zero -- nothing is cached unless the app asks (it never does).
resource "aws_cloudfront_cache_policy" "app" {
  name        = "${local.name}-no-cache-forward-auth"
  min_ttl     = 0
  default_ttl = 0
  max_ttl     = 1

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true

    headers_config {
      header_behavior = "whitelist"
      headers {
        items = ["Authorization"]
      }
    }
    cookies_config {
      cookie_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "all"
    }
  }
}

resource "aws_cloudfront_distribution" "app" {
  enabled     = true
  comment     = "Resume Tailor"
  aliases     = local.custom_domain ? [var.domain_name] : []
  price_class = "PriceClass_100"

  origin {
    domain_name = replace(replace(aws_lambda_function_url.app.function_url, "https://", ""), "/", "")
    origin_id   = "lambda-url"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      origin_read_timeout    = 60 # max without a quota increase; analysis runs in the background
    }

    custom_header {
      name  = "x-origin-secret"
      value = random_password.origin_secret.result
    }
  }

  default_cache_behavior {
    target_origin_id       = "lambda-url"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    cache_policy_id          = aws_cloudfront_cache_policy.app.id
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # Managed-AllViewerExceptHostHeader

    response_headers_policy_id = aws_cloudfront_response_headers_policy.auth_challenge.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = local.custom_domain ? null : true
    acm_certificate_arn            = local.custom_domain ? aws_acm_certificate_validation.site[0].certificate_arn : null
    ssl_support_method             = local.custom_domain ? "sni-only" : null
    minimum_protocol_version       = local.custom_domain ? "TLSv1.2_2021" : null
  }
}

# Lambda function URLs rename a WWW-Authenticate response header (to
# x-amzn-Remapped-WWW-Authenticate), so the app's 401 reached the browser
# without it and Chrome showed "HTTP ERROR 401" instead of the login box.
# A viewer-response CloudFront function can't fix that: CloudFront doesn't run
# it on 401s that come from the origin. A response headers policy does apply to
# them, so it puts the challenge back. Browsers only act on WWW-Authenticate
# when the status is 401, so sending it on every response is harmless.
resource "aws_cloudfront_response_headers_policy" "auth_challenge" {
  name    = "${local.name}-auth-challenge"
  comment = "Restore the Basic Auth challenge that Lambda function URLs rename"

  custom_headers_config {
    items {
      header   = "WWW-Authenticate"
      value    = "Basic realm=\"Resume Tailor\", charset=\"UTF-8\""
      override = true
    }
  }
}
