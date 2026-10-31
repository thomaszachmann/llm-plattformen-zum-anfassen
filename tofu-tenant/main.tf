module "tenant" {
  source   = "./modules/tenant"
  for_each = var.tenants

  name       = each.key
  team_group = each.value.team_group
  gpu_quota  = each.value.gpu_quota
}

output "namespaces" {
  value = sort([for t in module.tenant : t.namespace])
}
