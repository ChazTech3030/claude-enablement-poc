# CloudFront standard logging v2 (decision 2.6, plan 7.4).
#
# WHY THESE FIELDS ARE EXCLUDED (operations s8): personal data is excluded at source, so it never exists
# to be protected, retained or deleted. We do NOT log:
#   c-ip, x-forwarded-for, c-port   - the learner's network address
#   cs(Cookie)                      - contains the signed-cookie credentials
#   cs-uri-query                    - may carry identifiers or tokens
#   cs(User-Agent), cs(Referer)     - fingerprinting data we have no use for
# The allowlist below is exhaustive: anything not listed is not logged. Logs expire after 7 days.

resource "aws_s3_bucket" "logs" {
  bucket        = "${local.p}-logs-${local.account}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket                  = aws_s3_bucket.logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    id     = "seven-days"
    status = "Enabled"
    filter {}
    expiration { days = 7 }
  }
}

data "aws_iam_policy_document" "logs" {
  statement {
    sid       = "LogDelivery"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.logs.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account]
    }
  }
}

resource "aws_s3_bucket_policy" "logs" {
  bucket = aws_s3_bucket.logs.id
  policy = data.aws_iam_policy_document.logs.json
}

resource "aws_cloudwatch_log_delivery_source" "cloudfront" {
  count        = var.enable_logging ? 1 : 0
  provider     = aws.use1
  name         = "${local.p}-cloudfront"
  log_type     = "ACCESS_LOGS"
  resource_arn = aws_cloudfront_distribution.delivery.arn
}

resource "aws_cloudwatch_log_delivery_destination" "logs" {
  count         = var.enable_logging ? 1 : 0
  provider      = aws.use1
  name          = "${local.p}-logs-s3"
  output_format = "json"
  delivery_destination_configuration {
    destination_resource_arn = "${aws_s3_bucket.logs.arn}/cloudfront"
  }
}

resource "aws_cloudwatch_log_delivery" "cloudfront" {
  count                    = var.enable_logging ? 1 : 0
  provider                 = aws.use1
  delivery_source_name     = aws_cloudwatch_log_delivery_source.cloudfront[0].name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.logs[0].arn
  record_fields = [
    "date", "time", "x-edge-location", "sc-bytes", "cs-method", "cs-uri-stem",
    "sc-status", "cs-protocol", "time-taken", "x-edge-result-type", "sc-content-type",
  ]
  s3_delivery_configuration {
    suffix_path = "{yyyy}/{MM}/{dd}/{HH}"
  }
  depends_on = [aws_s3_bucket_policy.logs]
}
