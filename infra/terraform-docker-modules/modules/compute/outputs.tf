output "container_names" {
  value = docker_container.this[*].name
}

output "container_ips" {
  value = [for c in docker_container.this : c.network_data[0].ip_address]
}
