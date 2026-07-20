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

variable "site_password" {
  description = "Shared HTTP Basic Auth password gating the whole app -- keeps a stranger who finds the URL from running up Anthropic API costs. Stored only in Key Vault."
  type        = string
  sensitive   = true
}

variable "deployer_principal_ids" {
  description = "Object IDs of every principal that runs terraform against this config (interactive users and CI/CD service connections) -- each needs Key Vault Secrets Officer to write the anthropic-api-key secret. Explicit and stable, not derived from data.azurerm_client_config.current, since that resolves to whoever is currently running terraform and breaks the moment a second identity (e.g. the CI/CD pipeline) also needs to apply. Not secret -- object IDs are identifiers, not credentials."
  type        = list(string)
  default = [
    "588c5199-00d3-41f4-8bd4-03337488d021", # mseetloo@gmail.com (interactive)
    "61d17e32-9d78-4f2d-adad-53d2552e1128", # resume-updater-arm-connection service principal (CI/CD)
  ]
}
