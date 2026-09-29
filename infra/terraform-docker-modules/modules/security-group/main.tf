# Docker has no native "security group" primitive like AWS/GCP/Azure do.
# This module keeps the same interface shape as a cloud security-group module
# (name in, normalized rules out) so calling code doesn't change when you
# swap the backend provider. The `terraform_data` resource just gives the
# validated rule set a real place in the state graph so `terraform plan`
# shows it like any other resource, instead of hiding it as a bare local.
resource "terraform_data" "this" {
  input = {
    name  = var.name
    rules = var.ingress_rules
  }
}
