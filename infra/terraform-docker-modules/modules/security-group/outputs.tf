output "name" {
  value = var.name
}

# Normalized so the compute module can feed this straight into a
# `ports { }` block regardless of how the caller wrote the rule.
output "rules" {
  value = [
    for r in var.ingress_rules : {
      description = r.description
      internal    = r.port
      external    = r.port
      protocol    = r.protocol
    }
  ]
}
