terraform {
  required_version = ">= 1.8"
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.70"
    }
  }
}

provider "hcloud" {} # Token aus Umgebungsvariable HCLOUD_TOKEN

variable "ssh_public_key" {
  type = string
}

variable "gateway_cidr" {
  type        = string
  description = "Quellnetz des llm-gateway (z. B. Egress-IP des Clusters)"
}

resource "hcloud_ssh_key" "admin" {
  name       = "llm-vm-admin"
  public_key = var.ssh_public_key
}

resource "hcloud_firewall" "llm_vm" {
  name = "llm-vm"
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = ["0.0.0.0/0", "::/0"]
  }
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "11434"
    source_ips = [var.gateway_cidr]
  }
}

resource "hcloud_server" "llm_vm" {
  name         = "llm-vm"
  image        = "ubuntu-24.04"
  server_type  = "ccx33" # 8 dedizierte vCPU, 32 GB RAM
  location     = "fsn1"
  ssh_keys     = [hcloud_ssh_key.admin.id]
  firewall_ids = [hcloud_firewall.llm_vm.id]
  labels       = { role = "llm-vm" }
  user_data    = <<-EOT
    #cloud-config
    package_update: true
    packages: [python3-apt]
  EOT
}

output "ansible_inventory" {
  value = "llm-vm ansible_host=${hcloud_server.llm_vm.ipv4_address} ansible_user=root"
}
