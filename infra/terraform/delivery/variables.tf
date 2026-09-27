variable "region" {
  type    = string
  default = "eu-west-1"
}

variable "name_prefix" {
  type    = string
  default = "fde-delivery"
}

# ---- domain (optional: without it the demo runs on the *.cloudfront.net hostname) ----
variable "domain_name" {
  description = "Registered domain with a Route 53 hosted zone in this account, e.g. example.click. null = demo fallback."
  type        = string
  default     = null
}

variable "delivery_subdomain" {
  type    = string
  default = "learn"
}

variable "ses_subdomain" {
  type    = string
  default = "mail"
}

# ---- email ----
variable "internal_email_domains" {
  description = "Allowlist for the reserved slug `internal` (previews and dashboard)."
  type        = list(string)
  default     = ["version1.com"]
}

variable "ops_email" {
  description = "Receives SES bounce and complaint alerts."
  type        = string
}

variable "ses_sender_email" {
  description = "Sender address when no domain is configured (demo fallback). Must be an address you can receive at."
  type        = string
  default     = null
}

variable "ses_sandbox_recipients" {
  description = "While SES is in the sandbox, only verified addresses receive codes. Each gets a verification email."
  type        = list(string)
  default     = []
}

# ---- signing key (plan 7.4: private key generated offline, stored in Parameter Store) ----
variable "cloudfront_public_key_pem_path" {
  type    = string
  default = "../../../keys/cloudfront_public.pem"
}

variable "signing_key_param" {
  type    = string
  default = "/fde-delivery/auth/cloudfront-private-key"
}

# ---- CI ----
variable "github_repository" {
  description = "owner/name of the GitHub repository trusted through OIDC."
  type        = string
}

variable "github_owner_id" {
  description = "Numeric GitHub owner ID (gh api users/{owner} --jq .id)."
  type        = string
}

variable "github_repository_id" {
  description = "Numeric GitHub repository ID (gh api repos/{owner}/{repo} --jq .id)."
  type        = string
}

# ---- controls ----
variable "enable_waf" {
  type    = bool
  default = true
}

variable "auth_rate_limit" {
  description = "Requests per 5 minutes per IP to /auth/api/."
  type        = number
  default     = 100
}

variable "code_requests_per_window" {
  description = "Code requests allowed per email address per 15 minutes (plan 8.1: 3)."
  type        = number
  default     = 3
}

variable "enable_logging" {
  type    = bool
  default = true
}

variable "demo_show_code" {
  description = "DEMO ONLY (technical debt): return the sign-in code in the API response. Never enable beyond the demo."
  type        = bool
  default     = false
}

variable "lambda_reserved_concurrency" {
  description = "null = unset (new accounts often cannot reserve concurrency; plan 8.1 Packaging)."
  type        = number
  default     = null
}
