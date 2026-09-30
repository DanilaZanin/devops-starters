mock_provider "docker" {}

run "network_is_named_with_the_net_suffix" {
  command = plan

  variables {
    name   = "demo"
    subnet = "10.40.0.0/24"
  }

  assert {
    condition     = docker_network.this.name == "demo-net"
    error_message = "the docker network must be called <name>-net"
  }
}

run "invalid_subnet_is_rejected_at_plan_time" {
  command = plan

  variables {
    name   = "demo"
    subnet = "not-a-cidr"
  }

  expect_failures = [var.subnet]
}
