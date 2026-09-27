#!/usr/bin/env bash
# Generate the CloudFront signed-cookie key pair offline and store the private key in Parameter Store (plan 7.5 step 3).
# The public key goes to keys/cloudfront_public.pem for Terraform; the private key never touches disk after upload.
# Usage: AWS_PROFILE=cdn-poc infra/make-signing-key.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
keys="$here/../keys"
param="${SIGNING_KEY_PARAM:-/fde-delivery/auth/cloudfront-private-key}"
region="${AWS_REGION:-eu-west-1}"
mkdir -p "$keys"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
openssl genrsa -out "$tmp" 2048 2>/dev/null
openssl rsa -in "$tmp" -pubout -out "$keys/cloudfront_public.pem" 2>/dev/null

# MSYS_NO_PATHCONV stops Git Bash on Windows rewriting the leading "/" of the parameter name into a path.
MSYS_NO_PATHCONV=1 aws ssm put-parameter --region "$region" --name "$param" --type SecureString \
  --value "$(cat "$tmp")" --overwrite >/dev/null
echo "private key -> SSM $param (SecureString); public key -> keys/cloudfront_public.pem"
