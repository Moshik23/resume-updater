variable "aws_region" {
  type    = string
  default = "ap-southeast-1"
}

variable "domain_name" {
  description = "Custom domain (DNS at Namecheap). Leave empty to use the *.cloudfront.net address only."
  type        = string
  default     = ""
}

variable "claude_model" {
  type    = string
  default = "claude-sonnet-5"
}

variable "ssm_prefix" {
  description = "SSM path holding <prefix>/anthropic-api-key and <prefix>/site-password (SecureString, created outside Terraform)"
  type        = string
  default     = "/resume-tailor"
}

variable "github_repo" {
  description = "owner/name of the repo allowed to deploy"
  type        = string
  default     = "Moshik23/resume-updater"
}

variable "github_sub_prefix_immutable" {
  description = "Immutable OIDC subject prefix for the repo (gh api repos/<repo>/actions/oidc/customization/sub -> sub_claim_prefix), e.g. repo:Owner@123/Repo@456. Empty if not used."
  type        = string
  default     = ""
}

variable "deploy_branch" {
  description = "Only pushes to this branch may deploy"
  type        = string
  default     = "master"
}
