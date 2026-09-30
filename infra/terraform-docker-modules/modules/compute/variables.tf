variable "name" {
  description = "Base name for the instance(s). A numeric suffix is appended when replicas > 1."
  type        = string
}

variable "image" {
  description = "Container image to run, e.g. nginxinc/nginx-unprivileged:1.30.2-alpine. Use an image that runs as non-root."
  type        = string
}

variable "replicas" {
  description = "Number of instances to create (mirrors an ASG-style desired capacity)."
  type        = number
  default     = 1

  validation {
    condition     = var.replicas >= 1 && floor(var.replicas) == var.replicas
    error_message = "replicas must be a whole number, at least 1."
  }
}

variable "network_name" {
  description = "Name of the network to attach the instance(s) to (output of the network module)."
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

variable "bind_ip" {
  description = "Host address the published ports listen on. Loopback by default; use 0.0.0.0 to expose them on every interface."
  type        = string
  default     = "127.0.0.1"
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

variable "healthcheck" {
  description = "Container health check. Leave null to use the image's own."
  type = object({
    test     = list(string)
    interval = optional(string, "10s")
    timeout  = optional(string, "3s")
    retries  = optional(number, 3)
  })
  default = null
}
