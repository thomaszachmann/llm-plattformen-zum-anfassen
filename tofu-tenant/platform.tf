# Plattform-Release: metrics-server (Basis für HPA, Tag 7)
resource "helm_release" "metrics_server" {
  name       = "metrics-server"
  namespace  = "kube-system"
  repository = "https://kubernetes-sigs.github.io/metrics-server/"
  chart      = "metrics-server"
  version    = "3.14.0"

  set = [
    {
      name  = "args[0]"
      value = "--kubelet-insecure-tls" # nur kind: Kubelet-Zertifikate selbstsigniert
    },
  ]
}
