module "network" {
  source = "../../modules/network"

  name   = "sandbox"
  subnet = "10.30.0.0/24"
  labels = {
    project = "terraform-modules-starter"
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

  name                  = "sandbox-web"
  image                 = "nginxinc/nginx-unprivileged:1.27-alpine"
  count_                = 2
  network_id            = module.network.network_id
  network_name          = module.network.network_name
  security_group_rules  = module.web_sg.rules
}
