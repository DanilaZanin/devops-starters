resource "docker_network" "this" {
  name = "${var.name}-net"

  ipam_config {
    subnet = var.subnet
  }

  dynamic "labels" {
    for_each = var.labels
    content {
      label = labels.key
      value = labels.value
    }
  }
}
