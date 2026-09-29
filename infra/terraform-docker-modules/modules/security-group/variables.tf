variable "name" {
  description = "Name of the security group, used only for output/logging in this local backend."
  type        = string
}

variable "ingress_rules" {
  description = <<-EOT
    List of allowed inbound ports. Mirrors the shape of an AWS/GCP security group rule
    so this module can be swapped for a real cloud security-group module without touching
    the code that calls it (see README "Porting to a real cloud").
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
}
