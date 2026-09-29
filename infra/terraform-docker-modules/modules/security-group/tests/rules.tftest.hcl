run "rules_are_normalized_for_the_compute_module" {
  command = plan

  variables {
    name = "web"
    ingress_rules = [
      {
        description = "HTTP"
        port        = 8080
      }
    ]
  }

  assert {
    condition     = output.rules[0].internal == 8080 && output.rules[0].external == 8080 && output.rules[0].protocol == "tcp"
    error_message = "a rule with only a port must normalize to internal = external = port over tcp"
  }
}

run "port_zero_is_rejected" {
  command = plan

  variables {
    name = "web"
    ingress_rules = [
      {
        description = "bad"
        port        = 0
      }
    ]
  }

  expect_failures = [var.ingress_rules]
}

run "port_above_65535_is_rejected" {
  command = plan

  variables {
    name = "web"
    ingress_rules = [
      {
        description = "bad"
        port        = 70000
      }
    ]
  }

  expect_failures = [var.ingress_rules]
}

run "unknown_protocol_is_rejected" {
  command = plan

  variables {
    name = "web"
    ingress_rules = [
      {
        description = "bad"
        port        = 8080
        protocol    = "icmp"
      }
    ]
  }

  expect_failures = [var.ingress_rules]
}

# Docker cannot filter by source address; accepting a narrower cidr would let a
# caller believe traffic is restricted when it is not.
run "narrow_cidr_is_rejected_instead_of_ignored" {
  command = plan

  variables {
    name = "web"
    ingress_rules = [
      {
        description = "office only"
        port        = 8080
        cidr        = "10.0.0.0/8"
      }
    ]
  }

  expect_failures = [var.ingress_rules]
}
