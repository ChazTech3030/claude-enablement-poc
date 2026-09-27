output "delivery_domain" {
  value = local.delivery_domain
}

output "cloudfront_domain" {
  value = aws_cloudfront_distribution.delivery.domain_name
}

output "distribution_id" {
  value = aws_cloudfront_distribution.delivery.id
}

output "content_bucket" {
  value = aws_s3_bucket.content.bucket
}

output "kvs_arn" {
  value = aws_cloudfront_key_value_store.gate.arn
}

output "allowlist_table" {
  value = aws_dynamodb_table.allowlist.name
}

output "deploy_role_arn" {
  value = aws_iam_role.deploy.arn
}

output "preview_role_arn" {
  value = aws_iam_role.preview.arn
}

output "region" {
  value = var.region
}
