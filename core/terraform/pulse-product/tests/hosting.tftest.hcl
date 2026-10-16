mock_provider "azurerm" {}
mock_provider "azapi" {}

variables {
  resource_group_name  = "example-pulse"
  location             = "canadacentral"
  storage_account_name = "examplepulse123"
  function_app_name    = "example-pulse-api"
  static_web_app_name  = "example-pulse"
}

run "existing_flex_default" {
  command = plan
  assert {
    condition     = length(azurerm_function_app_flex_consumption.this) == 1 && length(azurerm_linux_function_app.dedicated) == 0
    error_message = "Existing callers must retain Flex hosting by default."
  }
  assert {
    condition     = azurerm_service_plan.this[0].sku_name == "FC1"
    error_message = "The existing Flex plan must remain FC1."
  }
}

run "fixed_capacity_preserves_security_and_timers" {
  command = plan
  variables {
    hosting_mode  = "dedicated"
    dedicated_sku = "B2"
  }
  assert {
    condition     = length(azurerm_function_app_flex_consumption.this) == 0 && length(azurerm_linux_function_app.dedicated) == 1
    error_message = "Dedicated hosting must select only the Linux Function App."
  }
  assert {
    condition     = azurerm_service_plan.dedicated[0].sku_name == "B2" && azurerm_service_plan.dedicated[0].worker_count == 1 && azurerm_linux_function_app.dedicated[0].site_config[0].always_on
    error_message = "Fixed hosting must use one B2 worker with Always On for HTTP and timers."
  }
  assert {
    condition     = azurerm_linux_function_app.dedicated[0].client_certificate_enabled && azurerm_linux_function_app.dedicated[0].client_certificate_mode == "Required" && azurerm_linux_function_app.dedicated[0].client_certificate_exclusion_paths == join(";", var.browser_paths)
    error_message = "Device TLS certificate requirements and browser exclusions must be preserved."
  }
  assert {
    condition     = azurerm_linux_function_app.dedicated[0].storage_uses_managed_identity && !azurerm_storage_account.this.shared_access_key_enabled && !azurerm_linux_function_app.dedicated[0].webdeploy_publish_basic_authentication_enabled
    error_message = "Dedicated hosting must retain identity-based storage and disabled publish credentials."
  }
  assert {
    condition     = azapi_update_resource.auth_exclusions.body.properties.globalValidation.requireAuthentication && azapi_update_resource.auth_exclusions.body.properties.globalValidation.excludedPaths == var.unauthenticated_paths
    error_message = "Linked browser authentication must remain required outside agent paths."
  }
}

run "reject_unsupported_hosting_mode" {
  command = plan
  variables {
    hosting_mode = "unknown"
  }
  expect_failures = [var.hosting_mode]
}
