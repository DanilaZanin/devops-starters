# State lives in GitLab-managed Terraform state, not on the runner. The
# connection settings come from TF_HTTP_* environment variables set in
# .gitlab-ci.yml (address, lock/unlock URLs, job token), so this block stays empty.
# Without a remote backend every job starts from empty state on a fresh runner.
terraform {
  backend "http" {}
}
