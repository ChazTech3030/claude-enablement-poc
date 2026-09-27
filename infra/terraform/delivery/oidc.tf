# CI identity: GitHub Actions OIDC (rev 3). Two roles, so a PR preview can never write live customer prefixes.
# This is CI-to-AWS federation only; learner sign-in federation remains out of scope (plan section 0).

# GitHub's subject claim embeds the owner and repository IDs: repo:{owner}@{owner_id}/{repo}@{repo_id}:...
# Exact match on IDs means a deleted-and-recreated or look-alike repository cannot assume these roles.
locals {
  gh_owner = split("/", var.github_repository)[0]
  gh_repo  = split("/", var.github_repository)[1]
  gh_sub   = "repo:${local.gh_owner}@${var.github_owner_id}/${local.gh_repo}@${var.github_repository_id}"
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "trust_deploy" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only jobs running in the `production` environment, which the github stack restricts to main.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.gh_sub}:environment:production"]
    }
  }
}

data "aws_iam_policy_document" "trust_preview" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.gh_sub}:pull_request", "${local.gh_sub}:environment:preview"] # env jobs get the environment subject
    }
  }
}

resource "aws_iam_role" "deploy" {
  name                 = "${local.p}-gha-deploy"
  assume_role_policy   = data.aws_iam_policy_document.trust_deploy.json
  max_session_duration = 3600
}

resource "aws_iam_role" "preview" {
  name                 = "${local.p}-gha-preview"
  assume_role_policy   = data.aws_iam_policy_document.trust_preview.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "List"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.content.arn]
  }
  statement {
    sid     = "Write"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [
      "${aws_s3_bucket.content.arn}/c/*",
      "${aws_s3_bucket.content.arn}/state/*",
      "${aws_s3_bucket.content.arn}/build-cache/*",
    ]
  }
  statement {
    sid       = "Invalidate"
    actions   = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"]
    resources = [aws_cloudfront_distribution.delivery.arn]
  }
  statement {
    sid       = "Allowlist"
    actions   = ["dynamodb:Query", "dynamodb:PutItem", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.allowlist.arn]
  }
  statement {
    sid       = "Revocation"
    actions   = ["cloudfront-keyvaluestore:DescribeKeyValueStore", "cloudfront-keyvaluestore:ListKeys", "cloudfront-keyvaluestore:UpdateKeys", "cloudfront-keyvaluestore:GetKey", "cloudfront-keyvaluestore:PutKey", "cloudfront-keyvaluestore:DeleteKey"]
    resources = [aws_cloudfront_key_value_store.gate.arn]
  }
}

# Previews: write only under c/internal/previews/; read-only on build-cache so a PR cannot poison main's cache.
data "aws_iam_policy_document" "preview" {
  statement {
    sid       = "List"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.content.arn]
  }
  statement {
    sid       = "WritePreviews"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.content.arn}/c/internal/previews/*"]
  }
  statement {
    sid       = "ReadState"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.content.arn}/state/*", "${aws_s3_bucket.content.arn}/build-cache/*"]
  }
  statement {
    sid       = "Invalidate" # cannot be scoped to a path in IAM; harmless beyond cache churn
    actions   = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"]
    resources = [aws_cloudfront_distribution.delivery.arn]
  }
}

resource "aws_iam_role_policy" "deploy" {
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}

resource "aws_iam_role_policy" "preview" {
  role   = aws_iam_role.preview.id
  policy = data.aws_iam_policy_document.preview.json
}
