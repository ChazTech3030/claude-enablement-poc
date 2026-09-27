# SES (plan 7.4) and Route 53. With no domain, a single verified sender address is used (demo fallback).

data "aws_route53_zone" "main" {
  count = local.has_domain ? 1 : 0
  name  = var.domain_name
}

resource "aws_route53_record" "delivery" {
  for_each = local.has_domain ? toset(["A", "AAAA"]) : toset([])
  zone_id  = data.aws_route53_zone.main[0].zone_id
  name     = local.custom_host
  type     = each.value
  alias {
    name                   = aws_cloudfront_distribution.delivery.domain_name
    zone_id                = aws_cloudfront_distribution.delivery.hosted_zone_id
    evaluate_target_health = false
  }
}

# ---- sending identity
resource "aws_sesv2_email_identity" "sender" {
  email_identity         = local.ses_identity
  configuration_set_name = aws_sesv2_configuration_set.auth.configuration_set_name
}

resource "aws_route53_record" "dkim" {
  count   = local.has_domain ? 3 : 0
  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = "${aws_sesv2_email_identity.sender.dkim_signing_attributes[0].tokens[count.index]}._domainkey.${local.ses_identity}"
  type    = "CNAME"
  ttl     = 600
  records = ["${aws_sesv2_email_identity.sender.dkim_signing_attributes[0].tokens[count.index]}.dkim.amazonses.com"]
}

resource "aws_sesv2_email_identity_mail_from_attributes" "sender" {
  count                  = local.has_domain ? 1 : 0
  email_identity         = aws_sesv2_email_identity.sender.email_identity
  mail_from_domain       = "bounce.${local.ses_identity}"
  behavior_on_mx_failure = "USE_DEFAULT_VALUE"
}

resource "aws_route53_record" "mail_from_mx" {
  count   = local.has_domain ? 1 : 0
  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = "bounce.${local.ses_identity}"
  type    = "MX"
  ttl     = 600
  records = ["10 feedback-smtp.${var.region}.amazonses.com"]
}

resource "aws_route53_record" "mail_from_spf" {
  count   = local.has_domain ? 1 : 0
  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = "bounce.${local.ses_identity}"
  type    = "TXT"
  ttl     = 600
  records = ["v=spf1 include:amazonses.com -all"]
}

resource "aws_route53_record" "dmarc" {
  count   = local.has_domain ? 1 : 0
  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = "_dmarc.${local.ses_identity}"
  type    = "TXT"
  ttl     = 600
  records = ["v=DMARC1; p=quarantine; rua=mailto:${var.ops_email}"]
}

# ---- sandbox recipients: each receives a one-click verification email from AWS
resource "aws_sesv2_email_identity" "sandbox_recipient" {
  for_each       = toset([for r in var.ses_sandbox_recipients : r if r != local.ses_identity])
  email_identity = each.value
}

# ---- bounce and complaint alerts
resource "aws_sesv2_configuration_set" "auth" {
  configuration_set_name = "${local.p}-auth"
  delivery_options { tls_policy = "REQUIRE" }
  reputation_options { reputation_metrics_enabled = true }
}

resource "aws_sns_topic" "ses_events" {
  name = "${local.p}-ses-events"
}

resource "aws_sns_topic_subscription" "ops" {
  topic_arn = aws_sns_topic.ses_events.arn
  protocol  = "email"
  endpoint  = var.ops_email
}

resource "aws_sesv2_configuration_set_event_destination" "sns" {
  configuration_set_name = aws_sesv2_configuration_set.auth.configuration_set_name
  event_destination_name = "bounces-complaints"
  event_destination {
    enabled              = true
    matching_event_types = ["BOUNCE", "COMPLAINT", "REJECT"]
    sns_destination { topic_arn = aws_sns_topic.ses_events.arn }
  }
}

data "aws_iam_policy_document" "sns_ses" {
  statement {
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.ses_events.arn]
    principals {
      type        = "Service"
      identifiers = ["ses.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account]
    }
  }
}

resource "aws_sns_topic_policy" "ses_events" {
  arn    = aws_sns_topic.ses_events.arn
  policy = data.aws_iam_policy_document.sns_ses.json
}
