output "network_id" {
  description = "ID of the docker network."
  value       = docker_network.this.id
}

output "network_name" {
  description = "Name of the docker network (pass this to the compute module)."
  value       = docker_network.this.name
}
