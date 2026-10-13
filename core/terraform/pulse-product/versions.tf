terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    # One gap azurerm cannot close: after the Static Web App is linked, keep /api/ingest out of
    # App Service authentication without overwriting the provider the link added.
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.0"
    }
  }
}
