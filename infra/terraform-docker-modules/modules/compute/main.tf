resource "docker_image" "this" {
  name         = var.image
  keep_locally = true
}

resource "docker_container" "this" {
  count = var.count_

  name  = var.count_ > 1 ? "${var.name}-${count.index}" : var.name
  image = docker_image.this.image_id
  env   = [for k, v in var.env : "${k}=${v}"]
  command = var.command

  networks_advanced {
    name = var.network_name
  }

  # When count_ > 1 we offset the external port per replica (count.index) so
  # multiple instances of the same module can publish ports on one host
  # without colliding, similar to how an ALB fans out to distinct instance ports.
  dynamic "ports" {
    for_each = var.security_group_rules
    content {
      internal = ports.value.internal
      external = ports.value.external + count.index
      protocol = ports.value.protocol
    }
  }
}
