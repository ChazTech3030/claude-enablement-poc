# One distribution serves everything (decision 2.11). Plan 7.4.

# ------------------------------------------------------------------ signing keys
resource "aws_cloudfront_public_key" "signing" {
  name        = "${local.p}-signing"
  encoded_key = file(var.cloudfront_public_key_pem_path)
  comment     = "Signed-cookie verification key; private half is in Parameter Store only"
  # CloudFront normalises the stored PEM, which otherwise reads as a change on every plan.
  # Rotation is deliberate: add a second key to the key group, then remove the old one.
  lifecycle { ignore_changes = [encoded_key] }
}

resource "aws_cloudfront_key_group" "signing" {
  name  = "${local.p}-learners"
  items = [aws_cloudfront_public_key.signing.id]
}

# ------------------------------------------------------------------ revocation KVS + gate function
# Entries are written by the pipeline (dk publish), never by Terraform.
resource "aws_cloudfront_key_value_store" "gate" {
  name    = "${local.p}-gate"
  comment = "revoked:{slug} entries (decision 2.5)"
}

resource "aws_cloudfront_function" "gate" {
  name                         = "${local.p}-gate"
  runtime                      = "cloudfront-js-2.0"
  comment                      = "Revocation, sign-in redirect and directory index rewrite for /c/*"
  publish                      = true
  code                         = templatefile("${path.module}/gate.js.tftpl", { kvs_id = aws_cloudfront_key_value_store.gate.id })
  key_value_store_associations = [aws_cloudfront_key_value_store.gate.arn]
}

# ------------------------------------------------------------------ origin access
resource "aws_cloudfront_origin_access_control" "s3" {
  name                              = "${local.p}-s3"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_origin_access_control" "lambda" {
  name                              = "${local.p}-lambda"
  origin_access_control_origin_type = "lambda"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Forward no cookies and no query strings. The viewer's x-amz-content-sha256 is consumed by OAC signing.
resource "aws_cloudfront_origin_request_policy" "auth_api" {
  name = "${local.p}-auth-api"
  cookies_config { cookie_behavior = "none" }
  query_strings_config { query_string_behavior = "none" }
  headers_config {
    header_behavior = "whitelist"
    headers { items = ["content-type"] } # x-amz-content-sha256 is used by OAC directly; CloudFront rejects it here
  }
}

data "aws_cloudfront_cache_policy" "optimized" { name = "Managed-CachingOptimized" }
data "aws_cloudfront_cache_policy" "disabled" { name = "Managed-CachingDisabled" }
data "aws_cloudfront_response_headers_policy" "security" { name = "Managed-SecurityHeadersPolicy" }

resource "aws_cloudfront_cache_policy" "auth_static" {
  name        = "${local.p}-auth-static"
  default_ttl = 60
  max_ttl     = 300
  min_ttl     = 0
  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config { cookie_behavior = "none" }
    headers_config { header_behavior = "none" }
    query_strings_config { query_string_behavior = "none" }
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
  }
}

# ------------------------------------------------------------------ certificate (custom domain only)
resource "aws_acm_certificate" "delivery" {
  count             = local.has_domain ? 1 : 0
  provider          = aws.use1
  domain_name       = local.custom_host
  validation_method = "DNS"
  lifecycle { create_before_destroy = true }
}

resource "aws_route53_record" "cert_validation" {
  for_each = local.has_domain ? {
    for o in aws_acm_certificate.delivery[0].domain_validation_options : o.domain_name => o
  } : {}
  zone_id         = data.aws_route53_zone.main[0].zone_id
  name            = each.value.resource_record_name
  type            = each.value.resource_record_type
  records         = [each.value.resource_record_value]
  ttl             = 300
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "delivery" {
  count                   = local.has_domain ? 1 : 0
  provider                = aws.use1
  certificate_arn         = aws_acm_certificate.delivery[0].arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}

# ------------------------------------------------------------------ distribution
locals {
  lambda_hosts = { for k, u in aws_lambda_function_url.auth : k => trimsuffix(trimprefix(u.function_url, "https://"), "/") }
}

resource "aws_cloudfront_distribution" "delivery" {
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "${local.p} delivery"
  price_class         = "PriceClass_100"
  default_root_object = "index.html"
  aliases             = local.has_domain ? [local.custom_host] : []
  web_acl_id          = var.enable_waf ? aws_wafv2_web_acl.auth[0].arn : null
  http_version        = "http2and3"

  origin {
    origin_id                = "content"
    domain_name              = aws_s3_bucket.content.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.s3.id
  }

  dynamic "origin" {
    for_each = local.lambda_hosts
    content {
      origin_id                = "auth-${origin.key}"
      domain_name              = origin.value
      origin_access_control_id = aws_cloudfront_origin_access_control.lambda.id
      custom_origin_config {
        http_port              = 80
        https_port             = 443
        origin_protocol_policy = "https-only"
        origin_ssl_protocols   = ["TLSv1.2"]
      }
    }
  }

  # /auth/api/request and /auth/api/verify -> Lambda function URLs
  dynamic "ordered_cache_behavior" {
    for_each = local.functions
    content {
      path_pattern               = ordered_cache_behavior.value.path
      target_origin_id           = "auth-${ordered_cache_behavior.key}"
      viewer_protocol_policy     = "https-only"
      allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods             = ["GET", "HEAD"]
      cache_policy_id            = data.aws_cloudfront_cache_policy.disabled.id
      origin_request_policy_id   = aws_cloudfront_origin_request_policy.auth_api.id
      response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security.id
      compress                   = true
    }
  }

  # Static login, gate, revoked and 404 pages
  ordered_cache_behavior {
    path_pattern               = "/auth/*"
    target_origin_id           = "content"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = aws_cloudfront_cache_policy.auth_static.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security.id
    compress                   = true
  }

  # Customer content: signed cookies (key group) + gate function
  ordered_cache_behavior {
    path_pattern               = "/c/*"
    target_origin_id           = "content"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security.id
    trusted_key_groups         = [aws_cloudfront_key_group.signing.id]
    compress                   = true
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.gate.arn
    }
  }

  default_cache_behavior {
    target_origin_id           = "content"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = aws_cloudfront_cache_policy.auth_static.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security.id
    compress                   = true
  }

  # 403 = not signed in / not authorised (S3 returns 404 for missing keys, decision 2.17).
  # Auth API handlers never return 403 because this applies distribution-wide.
  custom_error_response {
    error_code            = 403
    response_code         = 403
    response_page_path    = "/auth/gate.html"
    error_caching_min_ttl = 0
  }
  custom_error_response {
    error_code            = 404
    response_code         = 404
    response_page_path    = "/auth/not-found.html"
    error_caching_min_ttl = 10
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = !local.has_domain
    acm_certificate_arn            = local.has_domain ? aws_acm_certificate_validation.delivery[0].certificate_arn : null
    ssl_support_method             = local.has_domain ? "sni-only" : null
    minimum_protocol_version       = local.has_domain ? "TLSv1.2_2021" : null
  }
}

# ------------------------------------------------------------------ WAF: one rate rule on /auth/api/
resource "aws_wafv2_web_acl" "auth" {
  count    = var.enable_waf ? 1 : 0
  provider = aws.use1
  name     = "${local.p}-auth"
  scope    = "CLOUDFRONT"

  default_action {
    allow {}
  }

  rule {
    name     = "auth-api-rate"
    priority = 1
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit                 = var.auth_rate_limit
        evaluation_window_sec = 300
        aggregate_key_type    = "IP"
        scope_down_statement {
          byte_match_statement {
            search_string         = "/auth/api/"
            positional_constraint = "STARTS_WITH"
            field_to_match {
              uri_path {}
            }
            text_transformation {
              priority = 0
              type     = "NONE"
            }
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.p}-auth-api-rate"
      sampled_requests_enabled   = false
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.p}-auth"
    sampled_requests_enabled   = false
  }
}
