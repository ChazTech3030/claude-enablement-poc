data "aws_caller_identity" "me" {}

locals {
  p               = var.name_prefix
  account         = data.aws_caller_identity.me.account_id
  has_domain      = var.domain_name != null
  custom_host     = local.has_domain ? "${var.delivery_subdomain}.${var.domain_name}" : null
  delivery_domain = local.has_domain ? local.custom_host : aws_cloudfront_distribution.delivery.domain_name
  ses_identity    = local.has_domain ? "${var.ses_subdomain}.${var.domain_name}" : var.ses_sender_email
  ses_from        = local.has_domain ? "no-reply@${var.ses_subdomain}.${var.domain_name}" : var.ses_sender_email
  param_root      = "/${var.name_prefix}"
}

# ------------------------------------------------------------------ content bucket (plan 7.4)
resource "aws_s3_bucket" "content" {
  bucket        = "${local.p}-content-${local.account}"
  force_destroy = true # AT-17 rebuilds the delivery stack; content is reproducible from git
}

resource "aws_s3_bucket_public_access_block" "content" {
  bucket                  = aws_s3_bucket.content.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "content" {
  bucket = aws_s3_bucket.content.id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_lifecycle_configuration" "content" {
  bucket = aws_s3_bucket.content.id
  rule {
    id     = "build-cache"
    status = "Enabled"
    filter { prefix = "build-cache/" }
    expiration { days = 30 }
  }
  rule {
    id     = "previews-backstop"
    status = "Enabled"
    filter { prefix = "c/internal/previews/" }
    expiration { days = 14 }
  }
}

# The OAC may read c/, auth/ and the landing page, and may list the bucket so missing keys are 404 not 403
# (decision 2.17). state/ and build-cache/ are never readable through CloudFront.
data "aws_iam_policy_document" "content" {
  statement {
    sid       = "CloudFrontRead"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.content.arn}/c/*", "${aws_s3_bucket.content.arn}/auth/*", "${aws_s3_bucket.content.arn}/index.html"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.delivery.arn]
    }
  }
  statement {
    sid       = "CloudFrontList"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.content.arn]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.delivery.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "content" {
  bucket     = aws_s3_bucket.content.id
  policy     = data.aws_iam_policy_document.content.json
  depends_on = [aws_s3_bucket_public_access_block.content]
}

# Static auth pages and landing page, managed by Terraform (not the content pipeline).
locals {
  web_root  = "${path.module}/../../../auth/web"
  web_files = fileset(local.web_root, "**")
  mime = {
    html = "text/html; charset=utf-8"
    css  = "text/css; charset=utf-8"
    js   = "application/javascript; charset=utf-8"
  }
}

resource "aws_s3_object" "web" {
  for_each      = local.web_files
  bucket        = aws_s3_bucket.content.id
  key           = each.value
  source        = "${local.web_root}/${each.value}"
  etag          = filemd5("${local.web_root}/${each.value}")
  content_type  = lookup(local.mime, reverse(split(".", each.value))[0], "application/octet-stream")
  cache_control = "public, max-age=60"
}

# ------------------------------------------------------------------ DynamoDB (plan 7.4)
resource "aws_dynamodb_table" "allowlist" {
  name         = "${local.p}-allowlist"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "slug"
  range_key    = "domain"
  attribute {
    name = "slug"
    type = "S"
  }
  attribute {
    name = "domain"
    type = "S"
  }
}

resource "aws_dynamodb_table" "codes" {
  name         = "${local.p}-codes"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  attribute {
    name = "pk"
    type = "S"
  }
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}

resource "aws_dynamodb_table" "ratelimit" {
  name         = "${local.p}-ratelimit"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "email_hmac"
  range_key    = "window_start"
  attribute {
    name = "email_hmac"
    type = "S"
  }
  attribute {
    name = "window_start"
    type = "N"
  }
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}

resource "aws_dynamodb_table" "signins" {
  name         = "${local.p}-signins"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "slug"
  range_key    = "date"
  attribute {
    name = "slug"
    type = "S"
  }
  attribute {
    name = "date"
    type = "S"
  }
}

# The reserved slug `internal` is published here, never by the pipeline (plan 6).
resource "aws_dynamodb_table_item" "internal_allowlist" {
  for_each   = toset(var.internal_email_domains)
  table_name = aws_dynamodb_table.allowlist.name
  hash_key   = "slug"
  range_key  = "domain"
  item       = jsonencode({ slug = { S = "internal" }, domain = { S = each.value } })
}

# ------------------------------------------------------------------ Parameter Store (plan 7.4)
# FLAG: the pepper value is in Terraform state. Accepted for the PoC (technical debt register).
resource "random_password" "pepper" {
  length  = 43
  special = false
}

resource "aws_ssm_parameter" "pepper" {
  name  = "${local.param_root}/auth/hmac-pepper"
  type  = "SecureString"
  value = random_password.pepper.result
}

locals {
  delivery_domain_param     = "${local.param_root}/auth/delivery-domain"
  delivery_domain_param_arn = "arn:aws:ssm:${var.region}:${local.account}:parameter${local.delivery_domain_param}"
}

resource "aws_ssm_parameter" "delivery_domain" {
  name  = local.delivery_domain_param
  type  = "String"
  value = local.delivery_domain
}

# The signing key parameter is created outside Terraform (scripts/make-signing-key.sh); only its ARN is used here.
locals {
  signing_key_param_arn = "arn:aws:ssm:${var.region}:${local.account}:parameter${var.signing_key_param}"
}
