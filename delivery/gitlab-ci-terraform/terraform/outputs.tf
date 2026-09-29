output "container_name" {
  description = "Name of the demo container for this environment."
  value       = docker_container.app.name
}
