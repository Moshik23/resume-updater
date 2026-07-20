# State is local (terraform.tfstate, gitignored) — this is a solo personal
# project, not a team one, so a remote backend isn't worth the bootstrap
# complexity. Migrate to an azurerm remote backend later if that changes.

terraform {
  required_version = ">= 1.9"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
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
