output "container_app_fqdn" {
  value = azurerm_container_app.this.ingress[0].fqdn
}

output "acr_login_server" {
  value = azurerm_container_registry.this.login_server
}

output "key_vault_uri" {
  value = azurerm_key_vault.this.vault_uri
}
