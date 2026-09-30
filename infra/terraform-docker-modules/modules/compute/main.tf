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

  # Offsetting by replica index only separates replicas of the SAME rule. Rules
  # whose ports are closer than `replicas` (8080 and 8081 with two replicas)
  # still overlap, so the computed set is checked as a whole: one entry per
  # (ip, protocol, external) may exist.
  host_port_keys = [for p in flatten(local.replica_ports) : "${p.ip}/${p.protocol}/${p.external}"]
  duplicate_host_ports = sort([
    for k in distinct(local.host_port_keys) : k
    if length([for x in local.host_port_keys : x if x == k]) > 1
  ])
  highest_host_port = max(concat([0], [for p in flatten(local.replica_ports) : p.external])...)
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

  lifecycle {
    precondition {
      condition     = length(local.duplicate_host_ports) == 0
      error_message = "replicas must publish distinct host ports, but these are claimed more than once: ${join(", ", local.duplicate_host_ports)}. Space the security group ports at least `replicas` apart."
    }
    precondition {
      condition     = local.highest_host_port <= 65535
      error_message = "the highest published host port would be ${local.highest_host_port}; ports above 65535 do not exist. Lower the port or the replica count."
    }
  }

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
