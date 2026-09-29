variable "name" {
  description = "Name of the network; the docker network is called <name>-net."
  type        = string
}

variable "subnet" {
  description = "CIDR block for the network, e.g. 10.20.0.0/24."
  type        = string
  default     = "10.20.0.0/24"

  validation {
    condition     = can(cidrnetmask(var.subnet))
    error_message = "subnet must be a valid IPv4 CIDR block such as 10.20.0.0/24."
  }
}

variable "labels" {
  description = "Key/value labels attached to the network for discovery and cost-tagging style workflows."
  type        = map(string)
  default     = {}
}
