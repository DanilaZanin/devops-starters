# Plan-only tests against a mocked docker provider: no daemon is needed.
# The assertions are on values Terraform knows at plan time.
mock_provider "docker" {}

variables {
  name         = "web"
  image        = "nginxinc/nginx-unprivileged:1.30.2-alpine"
  network_name = "demo-net"
  security_group_rules = [
    {
      description = "HTTP"
      internal    = 8080
      external    = 8080
      protocol    = "tcp"
    }
  ]
}

# THE TRAP (see traps/port-offset.sh): replicas of one module must not publish
# the same host port. Without the per-replica offset the second container fails
# at apply with "port is already allocated". This run fails on such a module.
run "replicas_publish_distinct_host_ports" {
  command = plan

  variables {
    replicas = 3
  }

  assert {
    condition     = flatten([for ports in output.published_ports : [for p in ports : p.external]]) == [8080, 8081, 8082]
    error_message = "replicas must publish distinct host ports (8080, 8081, 8082 expected)"
  }

  assert {
    condition     = [for c in docker_container.this : c.name] == ["web-0", "web-1", "web-2"]
    error_message = "replica names must carry the replica index"
  }
}

run "single_replica_keeps_the_plain_name_and_port" {
  command = plan

  assert {
    condition     = [for c in docker_container.this : c.name] == ["web"]
    error_message = "a single replica must be named exactly var.name"
  }

  assert {
    condition     = flatten([for ports in output.published_ports : [for p in ports : p.external]]) == [8080]
    error_message = "a single replica must publish the requested port unchanged"
  }
}

run "ports_bind_to_loopback_by_default" {
  command = plan

  assert {
    condition     = alltrue(flatten([for ports in output.published_ports : [for p in ports : p.ip == "127.0.0.1"]]))
    error_message = "published ports must default to 127.0.0.1"
  }
}

run "zero_replicas_is_rejected" {
  command = plan

  variables {
    replicas = 0
  }

  expect_failures = [var.replicas]
}

# Offsetting by replica index is not enough across several rules: with rules on
# 8080 and 8081 and two replicas, replica 0 publishes [8080, 8081] and replica 1
# publishes [8081, 8082], and 8081 is claimed twice.
run "adjacent_rules_that_collide_across_replicas_are_rejected" {
  command = plan

  variables {
    replicas = 2
    security_group_rules = [
      { description = "app", internal = 8080, external = 8080, protocol = "tcp" },
      { description = "admin", internal = 9090, external = 8081, protocol = "tcp" },
    ]
  }

  expect_failures = [docker_container.this]
}

run "rules_spaced_by_at_least_the_replica_count_are_accepted" {
  command = plan

  variables {
    replicas = 2
    security_group_rules = [
      { description = "app", internal = 8080, external = 8080, protocol = "tcp" },
      { description = "admin", internal = 9090, external = 8082, protocol = "tcp" },
    ]
  }

  assert {
    condition     = flatten([for ports in output.published_ports : [for p in ports : p.external]]) == [8080, 8082, 8081, 8083]
    error_message = "two replicas and two spaced rules must publish four distinct host ports"
  }
}

run "the_same_port_on_tcp_and_udp_is_not_a_collision" {
  command = plan

  variables {
    replicas = 2
    security_group_rules = [
      { description = "dns tcp", internal = 53, external = 5353, protocol = "tcp" },
      { description = "dns udp", internal = 53, external = 5353, protocol = "udp" },
    ]
  }

  assert {
    condition     = length(flatten(output.published_ports)) == 4
    error_message = "tcp and udp on the same number are separate host ports"
  }
}

run "ports_beyond_65535_are_rejected" {
  command = plan

  variables {
    replicas = 3
    security_group_rules = [
      { description = "edge", internal = 80, external = 65534, protocol = "tcp" },
    ]
  }

  expect_failures = [docker_container.this]
}
