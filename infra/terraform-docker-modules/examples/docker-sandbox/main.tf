module "network" {
  source = "../../modules/network"

  name   = "sandbox"
  subnet = "10.30.0.0/24"
  labels = {
    project = "terraform-docker-modules"
  }
}

module "web_sg" {
  source = "../../modules/security-group"

  name = "sandbox-web-sg"
  ingress_rules = [
    {
      description = "HTTP"
      port        = 8080
    }
  ]
}

module "web" {
  source = "../../modules/compute"

  name                 = "sandbox-web"
  image                = "nginxinc/nginx-unprivileged:1.30.2-alpine"
  replicas             = 2
  network_name         = module.network.network_name
  security_group_rules = module.web_sg.rules

  healthcheck = {
    test = ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/"]
  }
}
