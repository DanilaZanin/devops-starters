locals {
  # One entry per replica: the ports that replica publishes on the host.
  # The external port is offset by the replica index so replicas of one module
  # never fight for the same host port ("port is already allocated" at apply).
  replica_ports = [
    for i in range(var.replicas) : [
      for r in var.security_group_rules : {
        internal = r.internal
        external = r.external + i
        protocol = r.protocol
        ip       = var.bind_ip
      }
    ]
  ]
}

resource "docker_image" "this" {
  name         = var.image
  keep_locally = true
}

resource "docker_container" "this" {
  count = var.replicas

  name    = var.replicas > 1 ? "${var.name}-${count.index}" : var.name
  image   = docker_image.this.image_id
  env     = [for k, v in var.env : "${k}=${v}"]
  command = var.command

  networks_advanced {
    name = var.network_name
  }

  dynamic "ports" {
    for_each = local.replica_ports[count.index]
    content {
      internal = ports.value.internal
      external = ports.value.external
      protocol = ports.value.protocol
      ip       = ports.value.ip
    }
  }

  dynamic "healthcheck" {
    for_each = var.healthcheck == null ? [] : [var.healthcheck]
    content {
      test     = healthcheck.value.test
      interval = healthcheck.value.interval
      timeout  = healthcheck.value.timeout
      retries  = healthcheck.value.retries
    }
  }
}
