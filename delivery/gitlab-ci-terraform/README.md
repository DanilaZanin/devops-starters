# gitlab-ci-terraform-template

A reusable `.gitlab-ci.yml` template: lint → test → build → Terraform
plan/apply, split across staging (auto-applied) and production (manual gate),
wired up against a small demo Python app and a demo Terraform config so the
whole pipeline is actually runnable, not just a YAML sketch.

## Pipeline shape

```
lint -> test -> build -> terraform-plan:staging    -> terraform-apply:staging     (auto)
                       -> terraform-plan:production -> terraform-apply:production  (manual)
```

- **lint / test** — `ruff` + `pytest` against `app/`
- **build** — `docker build` via docker-in-docker (`docker:27-dind` service)
- **terraform-plan / terraform-apply** — one pair per environment; plan
  produces a `.tfplan` artifact, apply consumes exactly that artifact (not
  a fresh plan) so what gets applied is provably what was reviewed
- **production apply is `when: manual`** — staging ships on every push to
  main, production needs a human to click it in the GitLab UI

## Structure

```
.gitlab-ci.yml
app/
  app.py             # tiny demo module (add, is_palindrome)
  Dockerfile
  requirements.txt
tests/
  test_app.py
terraform/
  main.tf              # demo infra (docker provider, so plan/apply run without cloud creds)
```

`terraform/main.tf` uses the Docker provider instead of AWS/GCP so the
`terraform-plan` / `terraform-apply` jobs are actually runnable without any
cloud credentials — swap the provider block for your real one; the pipeline
logic (plan-as-artifact, environment-gated apply) doesn't change.

## Two real gotchas fixed while building this, not hidden

1. **`build` job couldn't reach the dind service.** The classic
   `docker:27` + `docker:27-dind` service pattern needs
   `DOCKER_HOST: tcp://docker:2375` and `DOCKER_TLS_CERTDIR: ""` set
   explicitly — without them the client tries to talk TLS on a plaintext
   port and fails with `Cannot connect to the Docker daemon`.

2. **`hashicorp/terraform` image swallows shell scripts.** That image sets
   `ENTRYPOINT` to the `terraform` binary itself, so a normal multi-line
   CI `script:` block (which GitLab wraps in `sh -c "..."`) gets run as
   `terraform sh -c "..."` instead — fails immediately with
   `Terraform has no command named "sh"`. Fixed with
   `image: {name: hashicorp/terraform:1.10, entrypoint: [""]}`.

## Verified — ran every stage for real, not just YAML-linted

Used [`gitlab-ci-local`](https://github.com/firecow/gitlab-ci-local), which
executes a real `.gitlab-ci.yml` against Docker exactly like GitLab Runner
would, without needing an actual GitLab server:

```
$ gitlab-ci-local lint test
 PASS  lint
 PASS  test          # 2 passed in 0.02s (real pytest run)

$ gitlab-ci-local build --privileged
 PASS  build          # real `docker build` inside the dind service,
                       # image tagged local-registry.../fallback.project:<sha>

$ gitlab-ci-local terraform-plan:staging --volume /var/run/docker.sock:/var/run/docker.sock
 PASS  terraform-plan:staging
       Plan: 2 to add, 0 to change, 0 to destroy
       Saved the plan to: staging.tfplan

$ gitlab-ci-local terraform-apply:staging --volume /var/run/docker.sock:/var/run/docker.sock
 PASS  terraform-apply:staging
       docker_container.app: Creation complete after 1s [id=5081896e...]

$ docker ps --filter name=gitlab-ci-demo
CONTAINER ID   IMAGE      STATUS         NAMES
5081896e22be   65645c7b   Up 6 seconds   gitlab-ci-demo-staging
```

The container terraform said it would create is actually running on the
host — the apply job genuinely executed `terraform apply` against the exact
plan artifact the previous job produced, same as a real GitLab pipeline
passing `staging.tfplan` between stages.

```
$ gitlab-ci-local --list | grep production
terraform-apply:production   terraform-apply  manual  true  production  [terraform-plan:production]
```

`when: manual, allow_failure: true` confirmed on the production apply job —
it will not run on its own in a real pipeline, matching the intent that
production needs a human in the loop.

(Note on `--volume .../docker.sock` for the terraform jobs: a real GitLab
Runner would either use a `dind` service like the build job, or a runner
with Docker executor access to a real Docker host. Mounting the local
socket was the simplest way to give the containerized `terraform-plan` /
`terraform-apply` jobs something real to talk to for this local
verification — documented here rather than left unexplained.)

Stack: GitLab CI syntax (validated + executed via `gitlab-ci-local` 4.73),
Terraform 1.10 (Docker provider), Python 3.12 (`ruff`, `pytest`), Docker
27 + dind, tested on Ubuntu 22.04.
