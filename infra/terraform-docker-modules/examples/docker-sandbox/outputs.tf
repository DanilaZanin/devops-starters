output "web_container_names" {
  value = module.web.container_names
}

output "web_container_ips" {
  value = module.web.container_ips
}

output "urls" {
  value = ["http://localhost:8080", "http://localhost:8081"]
}
