terraform {
  required_version = ">= 1.10"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 6.0" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
    archive = { source = "hashicorp/archive", version = "~> 2.5" }
  }
  # Partial configuration: bucket comes from `-backend-config` (see infra/apply.sh).
  backend "s3" {
    key          = "delivery.tfstate"
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { project = var.name_prefix, environment = "poc", managed_by = "terraform" }
  }
}

# CloudFront certificates, WAF web ACLs, CloudFront log delivery sources and the KVS data plane live in us-east-1.
provider "aws" {
  alias  = "use1"
  region = "us-east-1"
  default_tags {
    tags = { project = var.name_prefix, environment = "poc", managed_by = "terraform" }
  }
}
