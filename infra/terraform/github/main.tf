# Repository settings as code (rev 3, plan 7.2). Applied after `delivery`; reads its outputs.
terraform {
  required_version = ">= 1.10"
  required_providers {
    github = { source = "integrations/github", version = "~> 6.0" }
  }
  backend "s3" {
    key          = "github.tfstate"
    use_lockfile = true
  }
}

variable "owner" {
  type    = string
  default = "ChazTech3030"
}

variable "repository" {
  type    = string
  default = "claude-enablement-poc"
}

variable "required_approvals" {
  description = "0 while there is a single account (authors cannot approve their own PRs). Set to 1 when a reviewer joins."
  type        = number
  default     = 0
}

variable "state_bucket" {
  type = string
}

variable "region" {
  type    = string
  default = "eu-west-1"
}

# Authenticates with GITHUB_TOKEN from the workstation environment (e.g. `gh auth token`).
provider "github" {
  owner = var.owner
}

data "terraform_remote_state" "delivery" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "delivery.tfstate"
    region = var.region
  }
}

locals {
  d = data.terraform_remote_state.delivery.outputs
}

resource "github_repository" "poc" {
  name                   = var.repository
  description            = "Claude enablement content delivery platform - proof of concept (synthetic content only)"
  visibility             = "public" # free-plan branch protection needs public repos (rev 3)
  has_issues             = true
  has_projects           = false
  has_wiki               = false
  allow_auto_merge       = true
  allow_merge_commit     = false
  allow_rebase_merge     = false
  allow_squash_merge     = true
  delete_branch_on_merge = true
}

resource "github_branch_protection" "main" {
  repository_id           = github_repository.poc.node_id
  pattern                 = "main"
  enforce_admins          = false # owner can bypass for the demo (technical debt)
  required_linear_history = true
  allows_force_pushes     = false
  allows_deletions        = false

  required_status_checks {
    strict   = true
    contexts = ["validate"]
  }

  required_pull_request_reviews {
    required_approving_review_count = var.required_approvals
    dismiss_stale_reviews           = true
    require_code_owner_reviews      = var.required_approvals > 0
  }
}

resource "github_repository_environment" "production" {
  repository  = github_repository.poc.name
  environment = "production"
  deployment_branch_policy {
    protected_branches     = true
    custom_branch_policies = false
  }
}

resource "github_repository_environment" "preview" {
  repository  = github_repository.poc.name
  environment = "preview"
}

locals {
  labels = {
    "change"            = "d93f0b"
    "review-overdue"    = "e99695"
    "outcome-updated"   = "0e8a16"
    "outcome-no-change" = "c5def5"
    "no-changelog"      = "fef2c0"
  }
  variables = {
    AWS_REGION         = local.d.region
    DK_BUCKET          = local.d.content_bucket
    DK_DISTRIBUTION_ID = local.d.distribution_id
    DK_KVS_ARN         = local.d.kvs_arn
    DK_ALLOWLIST_TABLE = local.d.allowlist_table
    DK_DELIVERY_DOMAIN = local.d.delivery_domain
    AWS_DEPLOY_ROLE    = local.d.deploy_role_arn
    AWS_PREVIEW_ROLE   = local.d.preview_role_arn
  }
}

resource "github_issue_label" "labels" {
  for_each   = local.labels
  repository = github_repository.poc.name
  name       = each.key
  color      = each.value
}

# Not secrets: resource names and role ARNs (plan rule 9).
resource "github_actions_variable" "vars" {
  for_each      = local.variables
  repository    = github_repository.poc.name
  variable_name = each.key
  value         = each.value
}

output "repository_url" {
  value = github_repository.poc.html_url
}
