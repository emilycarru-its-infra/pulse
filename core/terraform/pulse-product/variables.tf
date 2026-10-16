variable "resource_group_name" {
  description = "Existing resource group the product lives in."
  type        = string
}

variable "location" {
  description = "Region for the storage, monitoring and Function App. It must offer the selected hosting plan."
  type        = string
}

variable "static_web_app_location" {
  description = "Region for the Static Web App, which is offered in fewer regions (such as westus2, centralus, eastus2, westeurope, eastasia). Defaults to location."
  type        = string
  default     = null
}

variable "storage_account_name" {
  description = "Globally unique storage account name: 3 to 24 lowercase letters and digits."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.storage_account_name))
    error_message = "storage_account_name must be 3 to 24 lowercase letters and digits."
  }
}

variable "function_app_name" {
  description = "Globally unique Function App name; its default host is <name>.azurewebsites.net, which the agents post to."
  type        = string
}

variable "static_web_app_name" {
  description = "Static Web App name."
  type        = string
}

variable "storage_replication_type" {
  description = "Storage account replication."
  type        = string
  default     = "LRS"
}

variable "events_table_name" {
  description = "Table that keeps every event, append-only."
  type        = string
  default     = "events"
}

variable "state_table_name" {
  description = "Table that keeps the latest event per seat."
  type        = string
  default     = "state"
}

variable "log_analytics_workspace_id" {
  description = "Existing Log Analytics workspace for Application Insights. Null creates one named <function_app_name>-logs."
  type        = string
  default     = null
}

variable "log_retention_days" {
  description = "Retention of a workspace this module creates."
  type        = number
  default     = 30
}

variable "python_version" {
  description = "Python version of the Function App."
  type        = string
  default     = "3.12"
}

variable "instance_memory_in_mb" {
  description = "Flex Consumption instance memory: 512, 2048 or 4096."
  type        = number
  default     = 2048
}

variable "http_concurrency" {
  description = "Optional concurrent HTTP requests per instance. Null keeps the platform default (one for Python). Tune storage-bound workloads using measured latency and execution units."
  type        = number
  default     = null

  validation {
    condition     = var.http_concurrency == null ? true : var.http_concurrency >= 1 && var.http_concurrency <= 1000 && floor(var.http_concurrency) == var.http_concurrency
    error_message = "http_concurrency must be null or an integer from 1 to 1000."
  }
}

variable "maximum_instance_count" {
  description = "Flex Consumption scale-out ceiling."
  type        = number
  default     = 40
}

variable "static_web_app_app_settings" {
  description = "Static Web App settings, such as the client id and secret its custom Entra sign-in reads. Set them here only: the Static Web App replaces its settings whole on every write."
  type        = map(string)
  default     = {}
  sensitive   = true
}

variable "app_settings" {
  description = "Function App settings merged over the ones this module sets (storage and table names). Product settings such as PULSE_DEVICE_CA_PEM go here."
  type        = map(string)
  default     = {}
}

variable "browser_paths" {
  description = "Function App paths the browser reaches through the Static Web App. Every other path, the agents' included, needs a TLS client certificate."
  type        = list(string)
  default     = ["/api/status", "/api/summary", "/api/export", "/api/GetRoles"]
}

variable "unauthenticated_paths" {
  description = "Function App paths that App Service authentication lets through without the Static Web App, for clients that authenticate themselves (agents with a device certificate)."
  type        = list(string)
  default     = ["/api/ingest"]
}

variable "custom_domain" {
  description = "Host name for the Static Web App, such as computers.status.example.edu, or null for none. It must sit inside dns_zone_name."
  type        = string
  default     = null
}

variable "dns_zone_name" {
  description = "Azure DNS zone that holds custom_domain's CNAME record."
  type        = string
  default     = null
}

variable "dns_zone_resource_group_name" {
  description = "Resource group of dns_zone_name. Defaults to resource_group_name."
  type        = string
  default     = null
}

variable "dns_ttl" {
  description = "TTL of the CNAME record, in seconds."
  type        = number
  default     = 3600
}

variable "tags" {
  description = "Tags for every resource."
  type        = map(string)
  default     = {}
}

variable "hosting_mode" {
  description = "API hosting: flex (existing default) or dedicated. Changing modes requires replacing the Function App; stage and review the cutover before applying."
  type        = string
  default     = "flex"
  validation {
    condition     = contains(["flex", "dedicated"], var.hosting_mode)
    error_message = "hosting_mode must be flex or dedicated."
  }
}

variable "dedicated_sku" {
  description = "Fixed Linux App Service SKU when hosting_mode is dedicated. One worker with Always On; no automatic scale-out."
  type        = string
  default     = "B2"
  validation {
    condition     = contains(["B1", "B2", "B3"], var.dedicated_sku)
    error_message = "dedicated_sku must be B1, B2 or B3."
  }
}
