# Auth Lambdas behind CloudFront OAC (decision 2.3). Zips are built by auth/build.py.
locals {
  dist = "${path.module}/../../../auth/dist"
  functions = {
    request = { zip = "${local.dist}/auth_request.zip", path = "/auth/api/request" }
    verify  = { zip = "${local.dist}/auth_verify.zip", path = "/auth/api/verify" }
  }
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "auth" {
  name               = "${local.p}-auth-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "auth" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.auth["request"].arn}:*", "${aws_cloudwatch_log_group.auth["verify"].arn}:*"]
  }
  statement {
    actions = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]
    resources = [
      aws_dynamodb_table.allowlist.arn, aws_dynamodb_table.codes.arn,
      aws_dynamodb_table.ratelimit.arn, aws_dynamodb_table.signins.arn,
    ]
  }
  statement {
    actions = ["ssm:GetParameter"]
    # delivery-domain by constructed ARN: referencing the resource would make the function depend on the distribution
    resources = [aws_ssm_parameter.pepper.arn, local.delivery_domain_param_arn, local.signing_key_param_arn]
  }
  statement {
    actions   = ["ses:SendEmail"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "ses:FromAddress"
      values   = [local.ses_from]
    }
  }
}

resource "aws_iam_role_policy" "auth" {
  role   = aws_iam_role.auth.id
  policy = data.aws_iam_policy_document.auth.json
}

resource "aws_cloudwatch_log_group" "auth" {
  for_each          = local.functions
  name              = "/aws/lambda/${local.p}-auth-${each.key}"
  retention_in_days = 7
}

resource "aws_lambda_function" "auth" {
  for_each         = local.functions
  function_name    = "${local.p}-auth-${each.key}"
  role             = aws_iam_role.auth.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "handler.handler"
  filename         = each.value.zip
  source_code_hash = filebase64sha256(each.value.zip)
  memory_size      = 256
  timeout          = 10

  reserved_concurrent_executions = var.lambda_reserved_concurrency == null ? -1 : var.lambda_reserved_concurrency

  environment {
    variables = {
      TABLE_ALLOWLIST       = aws_dynamodb_table.allowlist.name
      TABLE_CODES           = aws_dynamodb_table.codes.name
      TABLE_RATELIMIT       = aws_dynamodb_table.ratelimit.name
      TABLE_SIGNINS         = aws_dynamodb_table.signins.name
      PEPPER_PARAM          = aws_ssm_parameter.pepper.name
      SIGNING_KEY_PARAM     = var.signing_key_param
      KEY_PAIR_ID           = aws_cloudfront_public_key.signing.id
      DELIVERY_DOMAIN_PARAM = local.delivery_domain_param
      SES_FROM              = local.ses_from
      SES_CONFIG_SET        = aws_sesv2_configuration_set.auth.configuration_set_name
      DEMO_SHOW_CODE        = var.demo_show_code ? "true" : "false"
    }
  }

  depends_on = [aws_cloudwatch_log_group.auth, aws_iam_role_policy.auth]
}

resource "aws_lambda_function_url" "auth" {
  for_each           = local.functions
  function_name      = aws_lambda_function.auth[each.key].function_name
  authorization_type = "AWS_IAM"
}

# CloudFront OAC invokes the URL. Recent Lambda changes require both permissions for function URLs.
resource "aws_lambda_permission" "cloudfront_url" {
  for_each      = local.functions
  statement_id  = "AllowCloudFrontInvokeFunctionUrl"
  action        = "lambda:InvokeFunctionUrl"
  function_name = aws_lambda_function.auth[each.key].function_name
  principal     = "cloudfront.amazonaws.com"
  source_arn    = aws_cloudfront_distribution.delivery.arn
}

resource "aws_lambda_permission" "cloudfront_invoke" {
  for_each      = local.functions
  statement_id  = "AllowCloudFrontInvokeFunction"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.auth[each.key].function_name
  principal     = "cloudfront.amazonaws.com"
  source_arn    = aws_cloudfront_distribution.delivery.arn
}
