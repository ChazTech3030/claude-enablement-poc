#!/usr/bin/env bash
# Apply one Terraform stack: bootstrap | delivery | github  (plan 7.1)
# Usage: AWS_PROFILE=cdn-poc infra/apply.sh <stack> [extra terraform args]
set -euo pipefail
stack="${1:?stack: bootstrap | delivery | github}"; shift || true
here="$(cd "$(dirname "$0")" && pwd)"
dir="$here/terraform/$stack"
region="${AWS_REGION:-eu-west-1}"

if [[ "$stack" == "bootstrap" ]]; then
  terraform -chdir="$dir" init -input=false
  terraform -chdir="$dir" apply -input=false "$@"
  exit 0
fi

bucket="$(terraform -chdir="$here/terraform/bootstrap" output -raw state_bucket)"
terraform -chdir="$dir" init -input=false -reconfigure \
  -backend-config="bucket=$bucket" -backend-config="region=$region"

if [[ "$stack" == "delivery" ]]; then
  python "$here/../auth/build.py"   # Lambda zips must exist before plan
fi
if [[ "$stack" == "github" ]]; then
  export GITHUB_TOKEN="${GITHUB_TOKEN:-$(gh auth token)}"
  set -- -var "state_bucket=$bucket" "$@"
fi

terraform -chdir="$dir" apply -input=false "$@"
