output "web_container_names" {
  description = "Names of the web containers."
  value       = module.web.container_names
}

output "web_container_ips" {
  description = "IPs of the web containers on the sandbox network."
  value       = module.web.container_ips
}

output "urls" {
  description = "Host URLs of the replicas."
  value       = [for ports in module.web.published_ports : "http://${ports[0].ip}:${ports[0].external}"]
}
