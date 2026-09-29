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
