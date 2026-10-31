variable "kube_context" {
  type    = string
  default = "kind-sre-lab"
}

variable "tenants" {
  description = "Mandanten: Name => Einstellungen"
  type = map(object({
    team_group = string
    gpu_quota  = optional(number, 0)
  }))
}
