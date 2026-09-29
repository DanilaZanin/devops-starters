output "container_names" {
  description = "Names of the created containers."
  value       = docker_container.this[*].name
}

output "container_ips" {
  description = "IP address of each container on its first network."
  value       = [for c in docker_container.this : try(c.network_data[0].ip_address, null)]
}

output "published_ports" {
  description = "Host ports published by each replica: a list (one entry per replica) of { internal, external, protocol, ip }."
  value       = local.replica_ports
}
