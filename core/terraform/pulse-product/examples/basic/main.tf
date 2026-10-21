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

# A product whose state is pushed by a service rather than agents: PrintersPulse in live mode.
# The push carries an Entra app-only token holding Pulse.Ingest instead of a client
# certificate, so its path skips both the certificate and the Static Web App sign-in, and the
# code checks the token.
module "printers" {
  source = "../.."

  resource_group_name  = azurerm_resource_group.pulse.name
  location             = azurerm_resource_group.pulse.location
  storage_account_name = "stpulseprintersexample"
  function_app_name    = "func-pulse-printers-example"
  static_web_app_name  = "swa-pulse-printers-example"

  browser_paths         = ["/api/status", "/api/summary", "/api/GetRoles", "/api/ingest/health"]
  unauthenticated_paths = ["/api/ingest/health"]

  app_settings = {
    PULSE_SOURCE           = "live"
    PULSE_STALE_SECONDS    = "600"
    PULSE_TENANT_ID        = "00000000-0000-0000-0000-000000000000"
    PULSE_INGEST_AUDIENCES = "api://printers-example"
  }
}

output "printers_ingest_url" {
  value = "https://${module.printers.function_app_default_hostname}/api/ingest/health"
}
