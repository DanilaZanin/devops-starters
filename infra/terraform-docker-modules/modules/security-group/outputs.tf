output "name" {
  description = "Name of the security group."
  value       = var.name
}

# Normalized so the compute module can feed this straight into its
# security_group_rules input regardless of how the caller wrote the rule.
output "rules" {
  description = "Normalized rules: a list of { description, internal, external, protocol }."
  value = [
    for r in var.ingress_rules : {
      description = r.description
      internal    = r.port
      external    = r.port
      protocol    = r.protocol
    }
  ]
}
