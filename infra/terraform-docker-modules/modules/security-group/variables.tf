variable "name" {
  description = "Name of the security group, used only for output/logging in this local backend."
  type        = string
}

variable "ingress_rules" {
  description = <<-EOT
    List of allowed inbound ports. Mirrors the shape of an AWS/GCP security group rule
    so this module can be swapped for a real cloud security-group module without touching
    the code that calls it (see README "Porting to a real cloud"). Docker cannot filter
    published ports by source address, so cidr only accepts the default 0.0.0.0/0 here.
  EOT
  type = list(object({
    description = string
    port        = number
    protocol    = optional(string, "tcp")
    cidr        = optional(string, "0.0.0.0/0")
  }))
  default = []

  validation {
    condition     = alltrue([for r in var.ingress_rules : r.port > 0 && r.port <= 65535])
    error_message = "Each ingress_rules[].port must be between 1 and 65535."
  }

  validation {
    condition     = alltrue([for r in var.ingress_rules : contains(["tcp", "udp"], r.protocol)])
    error_message = "Each ingress_rules[].protocol must be either \"tcp\" or \"udp\"."
  }

  validation {
    condition     = alltrue([for r in var.ingress_rules : r.cidr == "0.0.0.0/0"])
    error_message = "Each ingress_rules[].cidr must be 0.0.0.0/0: Docker cannot restrict published ports by source address, so any other value would be silently ignored."
  }
}
