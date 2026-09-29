variable "name" {
  description = "Name of the network. Gets prefixed to avoid collisions with other stacks on the same host."
  type        = string
}

variable "subnet" {
  description = "CIDR block for the network, e.g. 10.20.0.0/24."
  type        = string
  default     = "10.20.0.0/24"
}

variable "labels" {
  description = "Key/value labels attached to the network for discovery and cost-tagging style workflows."
  type        = map(string)
  default     = {}
}
