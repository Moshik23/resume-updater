resource "azurerm_storage_account" "this" {
  name                     = "resumeupdaterstorage"
  resource_group_name      = azurerm_resource_group.this.name
  location                 = azurerm_resource_group.this.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
}

resource "azurerm_storage_container" "jobs" {
  name                  = "jobs"
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}

# Persistent, per-named-profile data (default resume + application tracker).
# Deliberately not covered by the "jobs/" lifecycle rule below -- unlike
# ephemeral job artifacts, this is meant to stick around across sessions.
resource "azurerm_storage_container" "profiles" {
  name                  = "profiles"
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}

# Auto-delete job artifacts (resume content is personal data) after ~2 days.
resource "azurerm_storage_management_policy" "cleanup" {
  storage_account_id = azurerm_storage_account.this.id

  rule {
    name    = "expire-job-artifacts"
    enabled = true

    filters {
      blob_types   = ["blockBlob"]
      prefix_match = ["jobs/"]
    }

    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = 2
      }
    }
  }
}

resource "azurerm_role_assignment" "app_blob_contributor" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}
