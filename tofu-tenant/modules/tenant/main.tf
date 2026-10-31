locals {
  ns = "tenant-${var.name}"
}

resource "kubernetes_namespace_v1" "this" {
  metadata {
    name = local.ns
    labels = {
      "sre-lab.io/role"                            = "tenant"
      "sre-lab.io/tenant"                          = var.name
      "pod-security.kubernetes.io/enforce"         = "restricted"
      "pod-security.kubernetes.io/enforce-version" = "latest"
      "pod-security.kubernetes.io/warn"            = "restricted"
      "pod-security.kubernetes.io/audit"           = "restricted"
    }
  }
}

resource "kubernetes_default_service_account_v1" "this" {
  metadata {
    namespace = kubernetes_namespace_v1.this.metadata[0].name
  }
  automount_service_account_token = false
}

resource "kubernetes_role_binding_v1" "admin" {
  metadata {
    name      = "tenant-admin"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
  }
  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = "tenant-admin" # Aggregierte ClusterRole aus Tag 6
  }
  subject {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Group"
    name      = var.team_group
  }
}

resource "kubernetes_resource_quota_v1" "this" {
  metadata {
    name      = "tenant-quota"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
  }
  spec {
    hard = {
      "requests.cpu"            = var.cpu_requests
      "requests.memory"         = var.memory_requests
      "limits.cpu"              = "4"
      "limits.memory"           = "8Gi"
      "pods"                    = "20"
      "persistentvolumeclaims"  = "5"
      "requests.storage"        = "20Gi"
      "services.loadbalancers"  = "0"
      "services.nodeports"      = "0"
      "requests.nvidia.com/gpu" = tostring(var.gpu_quota)
    }
  }
}

resource "kubernetes_limit_range_v1" "this" {
  metadata {
    name      = "tenant-defaults"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
  }
  spec {
    limit {
      type            = "Container"
      default_request = { cpu = "100m", memory = "128Mi" }
      default         = { cpu = "500m", memory = "512Mi" }
      max             = { cpu = "2", memory = "4Gi" }
    }
  }
}
