# The three modules wired together, planned against a mocked docker provider.
mock_provider "docker" {}

run "sandbox_wires_up_two_replicas_on_loopback" {
  command = plan

  assert {
    condition     = output.urls == ["http://127.0.0.1:8080", "http://127.0.0.1:8081"]
    error_message = "the example must publish two replicas on distinct loopback ports"
  }

  assert {
    condition     = output.web_container_names == ["sandbox-web-0", "sandbox-web-1"]
    error_message = "the example must create sandbox-web-0 and sandbox-web-1"
  }
}
