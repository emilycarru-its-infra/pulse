# A minimal call, used to validate the module. Every name here is a placeholder.

terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.0"
    }
  }
}

provider "azurerm" {
  features {
    storage {
      # Shared keys are off on the account, so manage it through Azure Resource Manager only.
      data_plane_available = false
    }
  }
  storage_use_azuread = true
}

provider "azapi" {}

resource "azurerm_resource_group" "pulse" {
  name     = "rg-pulse-example"
  location = "eastus2"
}

module "computers" {
  source = "../.."

  resource_group_name  = azurerm_resource_group.pulse.name
  location             = azurerm_resource_group.pulse.location
  storage_account_name = "stpulsecomputersexample"
  function_app_name    = "func-pulse-computers-example"
  static_web_app_name  = "swa-pulse-computers-example"

  app_settings = {
    PULSE_DEVICE_CA_FILE = "device-cas.pem"
  }

  custom_domain = "computers.status.example.edu"
  dns_zone_name = "example.edu"
}

output "agent_ingest_url" {
  value = "https://${module.computers.function_app_default_hostname}/api/ingest"
}
