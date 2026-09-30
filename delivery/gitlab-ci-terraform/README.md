# GitLab CI Terraform pipeline: plan in merge requests, apply on main, remote state

Level: **lab** (static policy checks and trap tests run in CI, plus a weekly smoke run of the demo image; the pipeline itself is not executed).

A `.gitlab-ci.yml` template: lint, test, build and push an image to the project
registry, `terraform plan` in merge requests and on the default branch, and
`terraform apply` on the default branch only (staging automatic, production behind a
manual gate). The demo Terraform and app are small so the whole flow has something
real to run.

## Problem

Terraform pipelines fail or misbehave in a few repeatable ways. A job using the
`hashicorp/terraform` image dies at once with an error like `Terraform has no
command named "sh"`: that image's ENTRYPOINT is the `terraform` binary, so GitLab's
shell-wrapped script becomes arguments to terraform. Separately, on ephemeral
runners a pipeline without remote state starts from empty state every time, so
`apply` tries to recreate what already exists. And a pipeline whose `apply` job runs
in merge requests can change real infrastructure from an unmerged branch.

This template resets the entrypoint, keeps state in GitLab-managed Terraform state
(one state per environment), and restricts applies to the default branch with a
`resource_group` per environment.

## Quick start

```bash
make check-prereqs   # python3, terraform
make test            # ruff, app tests, trap tests, terraform fmt/validate
```

`make test` creates `.venv` from `requirements-dev.txt`, runs `ruff` and
`terraform fmt -check`, then `pytest` (the app tests and `tests/test_traps.py`),
and ends with `terraform validate` (`init -backend=false`, which downloads the
docker provider). The trap tests fail if any broken variant passes.

`make up` builds the demo image, serves it on `127.0.0.1:8080` and fails unless
`/health` answers; the weekly CI job runs it and always runs `make down`;
`make down` stops it; `make reset` removes `.venv`, caches and `terraform/.terraform`;
`make lock` regenerates the provider lock file (needs network).

| | Status |
|---|---|
| macOS arm64 + colima (4 CPU / 8 GB) | verified 2026-09-29: `make test` green, also from a copied directory; `make up` served `/health`. Terraform 1.16.4, kreuzwerker/docker 4.6.0, pytest 9.1.1, ruff 0.16.9, Python 3.14; `hadolint` and `trivy config` (0.74.0, run via its image, HIGH/CRITICAL) report nothing |
| ubuntu-24.04 GitHub runner | CI only, not measured here; see `.github/workflows/gitlab-ci-terraform.yml` |
| First-run time | about 21 s for the first `make test` (venv install and provider download); about 12 s from a copied directory with the provider cached |
| RAM | `make test` starts no containers; the demo container idles at a few tens of MB (not measured precisely) |


## Traps this avoids

1. **Terraform image ENTRYPOINT swallows the job script** (reproduced in tests).
   `.terraform` sets `entrypoint: [""]`; the same applies to the trivy job.
2. **State on the runner.** `terraform/backend.tf` uses `backend "http" {}` and
   `.gitlab-ci.yml` points it at GitLab-managed state through `TF_HTTP_*`
   variables, with locking. Reproduced in tests as a policy check (backend
   declared, state address set), not by running Terraform against GitLab.
3. **Apply from a merge request.** Apply jobs have rules for the default branch only.
   Plans run in both. Production apply is `when: manual` with `allow_failure: false`.
   The policy check evaluates the `rules:` of every plan and apply job for four pipeline
   types (merge request, default branch, feature branch with and without an MR) with
   GitLab's first-matching-rule semantics, so `if: $CI_DEFAULT_BRANCH` (always true), a
   `!=` comparison, or an automatic rule listed before the manual one are all caught.
4. **Concurrent applies.** `resource_group` per environment.
5. **Provider drift.** `.terraform.lock.hcl` is committed (not git-ignored) and CI runs
   `terraform init -lockfile=readonly`.

Also: the image is built with a non-root user and a real `CMD`, and pushed to
`$CI_REGISTRY_IMAGE` from the default branch; lint stages run `terraform fmt`,
`validate` and `trivy config`.

## What the test proves / does NOT prove

Proves:

- The shipped `.gitlab-ci.yml` (with `extends` resolved the way GitLab merges it and
  `rules:if` evaluated per pipeline type) satisfies the policy in
  `checks/pipeline_policy.py`, and each mutation in
  `tests/test_traps.py` (drop the entrypoint reset, allow apply in merge requests through
  a second rule, a bare `$CI_DEFAULT_BRANCH` or a `!=`, make the production apply automatic
  or shadow its manual rule with an automatic one, let it fail with `allow_failure: true` on the
  job or the rule, an unevaluable `=~` rule (fails closed), drop the resource group, drop the push, drop the readonly
  lock, drop the remote backend, git-ignore or delete the lock file, run the image as
  root, remove the CMD) is reported with the expected code.
- `terraform fmt -check` and `terraform validate` pass; the app tests pass.

These are static policy checks on the YAML, not a run of GitLab. The evaluator supports
`$VAR`, string literals, `==`, `!=`, `&&`, `||` and parentheses; it does not know `=~`,
`rules:changes` or `rules:exists`.

Does NOT prove:

- That GitLab accepts or runs the pipeline. Nothing here executes a GitLab job or
  lints the file with GitLab's own CI lint. Paste it into the project's CI Lint page
  or use `gitlab-ci-local` (a third-party tool, not part of this module) before
  relying on it.
- That state locking, the job token and the state API work. That needs a GitLab project.
- That the trivy job passes inside GitLab. The same `trivy config` calls were run locally through the trivy image and were clean. The pinned job images (`hashicorp/terraform:1.16.4`, `docker:29.8.1`, `docker:29.8.1-dind`, `aquasec/trivy:0.74.0`, `python:3.14.7-slim`) were checked to exist with `docker manifest inspect`, but no job was run.
- That `apply` succeeds. The demo target is a container on the job's own docker-in-docker
  daemon, so it vanishes when the job ends while the state remembers it.

## Local demo vs production

- Replace the docker provider and `docker_container` with your real provider. Then
  run `make lock` (or `terraform providers lock ...`) and commit the new lock file.
- Docker-in-docker needs a runner with privileged mode. Prefer a runner with a
  dedicated Docker host or Kaniko/BuildKit for image builds.
- Protect production: protected branches, a protected `production` environment with
  required approvals, and restricted access to the state (Settings, CI/CD, job token
  allowlist).
- Plan files can contain secrets; artifacts expire after one day, restrict who can
  download them.
- Add real credentials as masked, protected CI/CD variables, never in the repo.
- Pin images by digest and let Renovate bump them: `hashicorp/terraform`,
  `docker`, `aquasec/trivy`, `python`.

## Copy it into your project

Copy `.gitlab-ci.yml`, `terraform/`, `app/`, `requirements-dev.txt`, `pytest.ini`,
`ruff.toml`, `tests/` and `checks/`. All of these are required: the pipeline's
`lint:python` and `test:python` jobs install `requirements-dev.txt` and run `ruff` and
`pytest` over `app/`, `tests/` and `checks/`. The `Makefile` is optional (local runs only).
To ship a smaller set, delete the `.python_base`, `lint:python` and `test:python` jobs
from `.gitlab-ci.yml` first, then `requirements-dev.txt`, `pytest.ini`, `ruff.toml`,
`tests/` and `checks/` can go too; the policy tests go with them. Adjust the policy in
`checks/pipeline_policy.py` when you rename jobs (it expects `plan:<env>`, `apply:<env>`,
`build`). No reference points outside this directory.

## Layout

```
.gitlab-ci.yml                pipeline
app/                          demo service (stdlib HTTP server) and its Dockerfile
terraform/                    backend.tf (http state), versions.tf, main.tf, lock file
checks/pipeline_policy.py     the policy the pipeline must satisfy
tests/test_traps.py           broken pipelines must fail the policy
tests/test_app.py             app tests
```
