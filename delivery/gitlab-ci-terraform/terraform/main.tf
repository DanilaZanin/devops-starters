variable "environment" {
  description = "Deployment environment. Also the name of the GitLab-managed state."
  type        = string

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be \"staging\" or \"production\"."
  }
}

# The demo target is a container on the job's own Docker daemon, so the pipeline
# runs without cloud credentials. Replace this provider and resource with your
# real ones; the pipeline logic does not change.
resource "docker_image" "app" {
  name         = "nginxinc/nginx-unprivileged:1.30.2-alpine"
  keep_locally = true
}

resource "docker_container" "app" {
  name  = "gitlab-ci-demo-${var.environment}"
  image = docker_image.app.image_id
}
