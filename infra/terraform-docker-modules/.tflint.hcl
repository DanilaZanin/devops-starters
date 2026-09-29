plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

# The example root module has no variables.tf on purpose.
rule "terraform_standard_module_structure" {
  enabled = false
}
