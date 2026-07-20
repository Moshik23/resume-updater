# Remote state in the same storage account used for job artifacts (a
# dedicated "tfstate" container, created out-of-band via `az storage
# container create` -- not managed by this config, to avoid the
# chicken-and-egg problem of a backend managing its own storage). This is
# required once more than one place applies changes (this machine's CLI
# and the CI/CD pipeline both do) -- a fresh checkout with no local state
# would otherwise try to recreate everything that already exists.
#
# Auth uses the storage account's access key (ARM_ACCESS_KEY env var, not
# committed here), fetched dynamically via `az storage account keys list`
# by whoever runs terraform -- this only requires the standard Contributor
# role's `listKeys` permission, not an extra data-plane RBAC grant.
terraform {
  required_version = ">= 1.9"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
  backend "azurerm" {
    resource_group_name  = "resume-updater-rg"
    storage_account_name = "resumeupdaterstorage"
    container_name       = "tfstate"
    key                  = "resume-updater.tfstate"
  }
}

provider "azurerm" {
  features {}
}

data "azurerm_client_config" "current" {}

resource "azurerm_resource_group" "this" {
  name     = "resume-updater-rg"
  location = var.location
}
