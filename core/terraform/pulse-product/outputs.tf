output "static_web_app_name" {
  value = azurerm_static_web_app.this.name
}

output "static_web_app_id" {
  value = azurerm_static_web_app.this.id
}

output "static_web_app_default_host_name" {
  value = azurerm_static_web_app.this.default_host_name
}

output "static_web_app_api_key" {
  description = "Deployment token for publishing the page's content."
  value       = azurerm_static_web_app.this.api_key
  sensitive   = true
}

output "function_app_name" {
  value = local.function_app.name
}

output "function_app_id" {
  value = local.function_app.id
}

output "function_app_default_hostname" {
  description = "The host agents post to: https://<this>/api/ingest."
  value       = local.function_app.default_hostname
}

output "function_principal_id" {
  description = "The Function App's managed identity, for further role assignments."
  value       = local.function_app.principal_id
}

output "storage_account_name" {
  value = azurerm_storage_account.this.name
}

output "app_insights_connection_string" {
  value     = azurerm_application_insights.this.connection_string
  sensitive = true
}
