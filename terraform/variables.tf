variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "eastus"
}

variable "container_image_tag" {
  description = "Tag of the resume-updater-app image in ACR to deploy"
  type        = string
}

variable "anthropic_api_key" {
  description = "Anthropic API key, stored only in Key Vault, never in state as a resource attribute value logged elsewhere"
  type        = string
  sensitive   = true
}
