variable "name" {
  description = "Kurzname des Mandanten, ergibt Namespace tenant-<name>"
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.name))
    error_message = "name: 2-21 Zeichen, a-z, 0-9, Bindestrich."
  }
}

variable "team_group" {
  description = "IdP-Gruppe, die tenant-admin im Namespace erhält"
  type        = string
}

variable "gpu_quota" {
  description = "Maximal angeforderte GPUs (requests.nvidia.com/gpu)"
  type        = number
  default     = 0
  validation {
    condition     = var.gpu_quota >= 0 && floor(var.gpu_quota) == var.gpu_quota
    error_message = "gpu_quota muss eine ganze Zahl >= 0 sein."
  }
}

variable "cpu_requests" {
  description = "Summe CPU-Requests im Namespace"
  type        = string
  default     = "2"
}

variable "memory_requests" {
  description = "Summe Memory-Requests im Namespace"
  type        = string
  default     = "4Gi"
}
