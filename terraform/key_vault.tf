resource "azurerm_key_vault" "this" {
  name                       = "resume-updater-kv"
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  purge_protection_enabled   = false # personal project — allow full teardown
}

resource "azurerm_key_vault_secret" "anthropic_api_key" {
  name         = "anthropic-api-key"
  value        = var.anthropic_api_key
  key_vault_id = azurerm_key_vault.this.id
}

resource "azurerm_key_vault_secret" "site_password" {
  name         = "site-password"
  value        = var.site_password
  key_vault_id = azurerm_key_vault.this.id
}

resource "azurerm_role_assignment" "app_kv_secrets_user" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# Grant every principal that runs terraform (see variables.tf) permission
# to write secrets -- explicit list, not "whoever is currently running
# terraform", since more than one identity applies this config.
resource "azurerm_role_assignment" "deployer_kv_secrets_officer" {
  for_each             = toset(var.deployer_principal_ids)
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = each.value
}
