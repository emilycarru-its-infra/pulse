# pulse-product

Terraform module for the Azure half of one Pulse product, in a resource group that
already exists:

- **Storage account** with shared keys off, a table for every event, a table for the
  latest event per seat, and the Function App's deployment container.
- **Application Insights**, on a Log Analytics workspace you pass in or one it creates.
- **Function App** on Flex Consumption, Python 3.12, with a system-assigned identity that
  reaches storage with Storage Table Data Contributor and Storage Blob Data Owner (no keys
  or connection strings). HTTPS only, TLS 1.2, and client certificates `Required` except on the browser routes.
- **Static Web App** (Standard) for the page, with the Function App linked as its `/api`
  backend.
- Optionally a **custom domain**: a CNAME in an Azure DNS zone, validated by the Static Web
  App through that CNAME.

## How requests reach the API

```text
browser ── https://<custom domain>/api/status ──> Static Web App (sign-in, route rules) ──> Function App
agent   ── https://<function host>/api/ingest + TLS client certificate ─────────────────> Function App
```

The Static Web App links the Function App as its backend rather than proxying to it.
Linking turns on App Service authentication on the Function App with the Static Web App
as its only identity provider, so the read routes answer only through the Static Web App,
after its sign-in. The module then excludes `unauthenticated_paths` (`/api/ingest`) from
that authentication, merging into what the link wrote, so agents reach the code directly.

Client certificates are `Required` on every path except `browser_paths`. On the agents'
paths App Service ends TLS only for a client that presents a certificate and proves it holds
the key, then forwards that certificate in `X-ARR-ClientCert`; a request without one never
reaches the code, so the header cannot be supplied by hand. App Service does not check who
issued it: the product checks the chain and maps the device to a seat. The browser routes
are excluded, since the Static Web App's proxy presents no certificate. Leave HTTP/2 off on the Function
App (the default), since App Service client certificates are only dependable over HTTP/1.1.

Microsoft documents linked Function Apps on the Consumption, Premium and Dedicated plans
and does not yet list Flex Consumption. Plain `/api/*` routing has been reported to work
with Flex; check `/api/summary` through the Static Web App after the first deploy. There is no
unlinked mode: without the link the read routes would answer anyone on the Function
App's own host.

## Example

```hcl
provider "azurerm" {
  features {
    storage {
      data_plane_available = false
    }
  }
  storage_use_azuread = true
}

module "computers" {
  source = "github.com/emilycarru-its-infra/pulse//core/terraform/pulse-product?ref=<tag>"

  resource_group_name     = "rg-pulse"
  location                = "eastus2"
  static_web_app_location = "eastus2"
  storage_account_name    = "stpulsecomputers"
  function_app_name       = "func-pulse-computers"
  static_web_app_name     = "swa-pulse-computers"

  app_settings = {
    PULSE_DEVICE_CA_FILE = "device-cas.pem"
  }

  custom_domain = "computers.status.example.edu"
  dns_zone_name = "example.edu"
}
```

The provider settings matter: with shared keys off, azurerm must manage the account
through Azure Resource Manager only. The deploying identity needs Owner, or Contributor
plus User Access Administrator, on the resource group for the role assignments, and DNS
Zone Contributor on the zone when `custom_domain` is set.

[`examples/basic`](examples/basic) is the same call, used to validate the module:

```bash
cd examples/basic && terraform init -backend=false && terraform validate
```

## Inputs

| Name | Type | Default | |
|---|---|---|---|
| `resource_group_name` | string | required | Existing resource group |
| `location` | string | required | Region for storage, monitoring and the Function App; must offer Flex Consumption |
| `storage_account_name` | string | required | Globally unique, 3 to 24 lowercase letters and digits |
| `function_app_name` | string | required | Globally unique; agents post to `https://<name>.azurewebsites.net/api/ingest` |
| `static_web_app_name` | string | required | |
| `static_web_app_location` | string | `location` | Static Web Apps run in fewer regions |
| `storage_replication_type` | string | `LRS` | |
| `events_table_name` | string | `events` | Every event, append-only |
| `state_table_name` | string | `state` | Latest event per seat |
| `log_analytics_workspace_id` | string | null | Null creates `<function_app_name>-logs` |
| `log_retention_days` | number | `30` | For a workspace the module creates |
| `python_version` | string | `3.12` | |
| `instance_memory_in_mb` | number | `2048` | 512, 2048 or 4096 |
| `maximum_instance_count` | number | `40` | |
| `app_settings` | map(string) | `{}` | Merged over the module's own settings |
| `browser_paths` | list(string) | `["/api/status", "/api/summary", "/api/export"]` | Paths that need no client certificate; every other path does |
| `unauthenticated_paths` | list(string) | `["/api/ingest"]` | Paths App Service authentication lets through |
| `custom_domain` | string | null | Must sit inside `dns_zone_name` |
| `dns_zone_name` | string | null | Azure DNS zone for the CNAME |
| `dns_zone_resource_group_name` | string | `resource_group_name` | |
| `dns_ttl` | number | `3600` | |
| `tags` | map(string) | `{}` | |

The module sets `AzureWebJobsStorage__accountName`, `PULSE_STORAGE_ACCOUNT`,
`PULSE_EVENTS_TABLE` and `PULSE_STATE_TABLE`; anything in `app_settings` wins.

## Outputs

| Name | |
|---|---|
| `static_web_app_name`, `static_web_app_id`, `static_web_app_default_host_name` | |
| `static_web_app_api_key` | Deployment token for the page's content (sensitive) |
| `function_app_name`, `function_app_id`, `function_app_default_hostname` | The host agents post to |
| `function_principal_id` | The Function App's managed identity |
| `storage_account_name` | |
| `app_insights_connection_string` | Sensitive |

## Sign-in on the Static Web App

Sign-in and roles are the Static Web App's `staticwebapp.config.json`, deployed with the
page. The rules that matter to this module: require a role on everything, keep
`/api/ingest` unreachable through the Static Web App (agents use the Function App host),
and send the unauthenticated to the Entra sign-in. The tenant, application and role names
are the deploying site's:

```json
{
  "routes": [
    { "route": "/api/ingest", "statusCode": 404 },
    { "route": "/api/export/*", "allowedRoles": ["<export role>"] },
    { "route": "/*", "allowedRoles": ["<viewer role>"] }
  ],
  "responseOverrides": {
    "401": { "redirect": "/.auth/login/aad", "statusCode": 302 }
  },
  "auth": {
    "identityProviders": {
      "azureActiveDirectory": {
        "registration": {
          "openIdIssuer": "https://login.microsoftonline.com/<tenant id>/v2.0",
          "clientIdSettingName": "AAD_CLIENT_ID",
          "clientSecretSettingName": "AAD_CLIENT_SECRET"
        }
      }
    }
  }
}
```
