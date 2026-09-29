variable "name" {
  description = "Base name for the instance(s). A numeric suffix is appended when count > 1."
  type        = string
}

variable "image" {
  description = "Container image to run, e.g. nginx:1.27-alpine."
  type        = string
}

variable "count_" {
  description = "Number of instances to create (mirrors an ASG-style `desired_capacity`)."
  type        = number
  default     = 1
}

variable "network_id" {
  description = "ID of the network to attach the instance(s) to (output of the network module)."
  type        = string
}

variable "network_name" {
  description = "Name of the network to attach the instance(s) to."
  type        = string
}

variable "security_group_rules" {
  description = "Normalized rules from the security-group module output."
  type = list(object({
    description = string
    internal    = number
    external    = number
    protocol    = string
  }))
  default = []
}

variable "env" {
  description = "Environment variables to inject into the instance, e.g. app config."
  type        = map(string)
  default     = {}
}

variable "command" {
  description = "Override the container's default command. Leave null to use the image's own entrypoint."
  type        = list(string)
  default     = null
}
