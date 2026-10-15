# One Pulse product: storage for its events and state, a Function App for the API, and a
# Static Web App for the page. Browsers reach the API through the Static Web App, which
# links the Function App as its /api backend and enforces sign-in. Agents post to the
# Function App's own host and authenticate with a TLS client certificate, which App
# Service forwards to the code in X-ARR-ClientCert.

locals {
  custom_domain     = var.custom_domain == null ? null : lower(trimsuffix(var.custom_domain, "."))
  dns_zone_rg       = coalesce(var.dns_zone_resource_group_name, var.resource_group_name)
  workspace_id      = var.log_analytics_workspace_id != null ? var.log_analytics_workspace_id : azurerm_log_analytics_workspace.this[0].id
  deployment_bucket = "${azurerm_storage_account.this.primary_blob_endpoint}${azurerm_storage_container.deployments.name}"

  app_settings = merge({
    # azurerm writes AzureWebJobsStorage as a connection string with an empty account key,
    # which the host tries before the identity settings and fails on. An empty value makes
    # it fall through to AzureWebJobsStorage__accountName and the managed identity.
    AzureWebJobsStorage              = ""
    AzureWebJobsStorage__accountName = azurerm_storage_account.this.name
    PULSE_STORAGE_ACCOUNT            = azurerm_storage_account.this.name
    PULSE_EVENTS_TABLE               = var.events_table_name
    PULSE_STATE_TABLE                = var.state_table_name
  }, var.app_settings)
}

# Storage: no shared keys anywhere; the Function App reaches it with its managed identity.

resource "azurerm_storage_account" "this" {
  name                            = var.storage_account_name
  resource_group_name             = var.resource_group_name
  location                        = var.location
  account_tier                    = "Standard"
  account_replication_type        = var.storage_replication_type
  min_tls_version                 = "TLS1_2"
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  allow_nested_items_to_be_public = false
  tags                            = var.tags
}

# The tables go through ARM. azurerm_storage_table still writes table ACLs over the data
# plane with the account key, which an account with shared keys off refuses.
resource "azapi_resource" "events" {
  type      = "Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01"
  name      = var.events_table_name
  parent_id = "${azurerm_storage_account.this.id}/tableServices/default"
}

resource "azapi_resource" "state" {
  type      = "Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01"
  name      = var.state_table_name
  parent_id = "${azurerm_storage_account.this.id}/tableServices/default"
}

resource "azurerm_storage_container" "deployments" {
  name                  = "deployments"
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}

# Monitoring.

resource "azurerm_log_analytics_workspace" "this" {
  count               = var.log_analytics_workspace_id == null ? 1 : 0
  name                = "${var.function_app_name}-logs"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days
  tags                = var.tags
}

resource "azurerm_application_insights" "this" {
  name                = var.function_app_name
  resource_group_name = var.resource_group_name
  location            = var.location
  workspace_id        = local.workspace_id
  application_type    = "web"
  tags                = var.tags
}

# The API.

resource "azurerm_service_plan" "this" {
  name                = "${var.function_app_name}-plan"
  resource_group_name = var.resource_group_name
  location            = var.location
  os_type             = "Linux"
  sku_name            = "FC1"
  tags                = var.tags
}

resource "azurerm_function_app_flex_consumption" "this" {
  name                = var.function_app_name
  resource_group_name = var.resource_group_name
  location            = var.location
  service_plan_id     = azurerm_service_plan.this.id

  runtime_name           = "python"
  runtime_version        = var.python_version
  instance_memory_in_mb  = var.instance_memory_in_mb
  maximum_instance_count = var.maximum_instance_count
  http_concurrency       = var.http_concurrency

  storage_container_type      = "blobContainer"
  storage_container_endpoint  = local.deployment_bucket
  storage_authentication_type = "SystemAssignedIdentity"

  https_only = true
  # Required everywhere except the browser routes: on the agents' paths App Service ends
  # TLS only for a client that presents a certificate and proves it holds the key, and
  # X-ARR-ClientCert then carries that certificate. A request with no handshake
  # certificate never reaches the code, so a header someone types in proves nothing. The
  # browser routes, reached through the Static Web App's proxy, are excluded. App Service
  # does not check who issued the certificate; the code does.
  client_certificate_enabled         = true
  client_certificate_mode            = "Required"
  client_certificate_exclusion_paths = join(";", var.browser_paths)

  webdeploy_publish_basic_authentication_enabled = false

  identity {
    type = "SystemAssigned"
  }

  site_config {
    minimum_tls_version                    = "1.2"
    application_insights_connection_string = azurerm_application_insights.this.connection_string
  }

  app_settings = local.app_settings
  tags         = var.tags

  lifecycle {
    # Linking the Static Web App writes the authentication settings (see azapi_update_resource below).
    ignore_changes = [auth_settings_v2]
  }
}

resource "azurerm_role_assignment" "tables" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Table Data Contributor"
  principal_id         = azurerm_function_app_flex_consumption.this.identity[0].principal_id
}

resource "azurerm_role_assignment" "blobs" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = azurerm_function_app_flex_consumption.this.identity[0].principal_id
}

# The page.

resource "azurerm_static_web_app" "this" {
  name                = var.static_web_app_name
  resource_group_name = var.resource_group_name
  location            = coalesce(var.static_web_app_location, var.location)
  sku_tier            = "Standard"
  sku_size            = "Standard"
  # The Static Web App replaces its settings whole on every write, so its sign-in settings
  # (the Entra client id and secret staticwebapp.config.json names) are set here only.
  app_settings = var.static_web_app_app_settings
  tags         = var.tags
}

# Linking makes the Function App the Static Web App's /api backend and turns on App Service
# authentication with the Static Web App as its only identity provider, so the read routes
# answer only through the Static Web App and its sign-in.
resource "azurerm_static_web_app_function_app_registration" "this" {
  static_web_app_id = azurerm_static_web_app.this.id
  function_app_id   = azurerm_function_app_flex_consumption.this.id
}

# ...except the agents' paths, which must reach the code directly. This merges into the
# settings the link wrote rather than replacing them, which azurerm's auth_settings_v2 would.
resource "azapi_update_resource" "auth_exclusions" {
  type        = "Microsoft.Web/sites/config@2024-04-01"
  resource_id = "${azurerm_function_app_flex_consumption.this.id}/config/authsettingsV2"

  body = {
    properties = {
      globalValidation = {
        requireAuthentication       = true
        unauthenticatedClientAction = "Return401"
        excludedPaths               = var.unauthenticated_paths
      }
    }
  }

  depends_on = [azurerm_static_web_app_function_app_registration.this]
}

# Custom domain: a CNAME in an Azure DNS zone, then the Static Web App validates it by that CNAME.

data "azurerm_dns_zone" "this" {
  count               = local.custom_domain == null ? 0 : 1
  name                = var.dns_zone_name
  resource_group_name = local.dns_zone_rg
}

resource "azurerm_dns_cname_record" "this" {
  count               = local.custom_domain == null ? 0 : 1
  name                = trimsuffix(local.custom_domain, ".${data.azurerm_dns_zone.this[0].name}")
  zone_name           = data.azurerm_dns_zone.this[0].name
  resource_group_name = local.dns_zone_rg
  ttl                 = var.dns_ttl
  record              = azurerm_static_web_app.this.default_host_name
  tags                = var.tags

  lifecycle {
    precondition {
      condition     = var.dns_zone_name != null && endswith(local.custom_domain, ".${lower(coalesce(var.dns_zone_name, "-"))}")
      error_message = "custom_domain must be a name inside dns_zone_name (a zone apex cannot be a CNAME)."
    }
  }
}

resource "azurerm_static_web_app_custom_domain" "this" {
  count             = local.custom_domain == null ? 0 : 1
  static_web_app_id = azurerm_static_web_app.this.id
  domain_name       = local.custom_domain
  validation_type   = "cname-delegation"

  depends_on = [azurerm_dns_cname_record.this]
}

# The first apply created these tables through azurerm and then failed on their ACLs. Forget
# them without a data-plane delete; the azapi tables above take over the same tables.
removed {
  from = azurerm_storage_table.events
  lifecycle {
    destroy = false
  }
}

removed {
  from = azurerm_storage_table.state
  lifecycle {
    destroy = false
  }
}
