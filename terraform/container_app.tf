resource "azurerm_log_analytics_workspace" "this" {
  name                = "resume-updater-logs"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_container_app_environment" "this" {
  name                       = "resume-updater-env"
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
}

# User-assigned (not system-assigned) so the identity exists, and can be
# granted AcrPull / Key Vault Secrets User / Storage Blob Data Contributor,
# *before* the Container App is created — a system-assigned identity only
# exists once the app resource is created, which is too late: the app's
# first revision needs those permissions to pull its image and read its
# secret at creation time, not after.
resource "azurerm_user_assigned_identity" "app" {
  name                = "resume-updater-app-identity"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
}

resource "azurerm_container_app" "this" {
  name                         = "resume-updater-app"
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = azurerm_resource_group.this.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  template {
    min_replicas = 0 # scale-to-zero — near-$0 idle cost
    max_replicas = 1 # personal-scale traffic

    container {
      name   = "resume-updater-app"
      image  = "${azurerm_container_registry.this.login_server}/resume-updater-app:${var.container_image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name        = "ANTHROPIC_API_KEY"
        secret_name = "anthropic-api-key"
      }
      env {
        name        = "SITE_PASSWORD"
        secret_name = "site-password"
      }
      env {
        name  = "AZURE_STORAGE_ACCOUNT_NAME"
        value = azurerm_storage_account.this.name
      }
      env {
        # Disambiguates which identity DefaultAzureCredential should use
        # inside the container (the Blob SDK call is our own code, not
        # Container Apps' platform-level secret/registry resolution).
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.app.client_id
      }
    }
  }

  secret {
    name                = "anthropic-api-key"
    key_vault_secret_id = azurerm_key_vault_secret.anthropic_api_key.versionless_id
    identity            = azurerm_user_assigned_identity.app.id
  }

  secret {
    name                = "site-password"
    key_vault_secret_id = azurerm_key_vault_secret.site_password.versionless_id
    identity            = azurerm_user_assigned_identity.app.id
  }

  registry {
    server   = azurerm_container_registry.this.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  depends_on = [
    azurerm_role_assignment.app_acr_pull,
    azurerm_role_assignment.app_kv_secrets_user,
  ]

  ingress {
    external_enabled = true
    target_port      = 8000
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}
