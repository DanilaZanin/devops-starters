# Helm ConfigMap change does not restart pods: GitOps starter for ArgoCD

Level: **verified** (trap test runs in CI on every PR).

A Helm chart (`demo-app`) with staging and production values, and an ArgoCD
app-of-apps that deploys both from one git repo. The chart carries the fix for
the most common silent Helm failure: config changes that never reach running pods.

## Problem

You change a value that feeds a ConfigMap, `helm upgrade` (or an ArgoCD sync)
finishes green, `kubectl get configmap` shows the new value, and the application
keeps running with the old one. Environment variables and mounted files that
were read at start-up only change when the pod restarts, and Kubernetes does not
restart a Deployment because a ConfigMap it references changed. Helm's chart
tips describe the standard fix, a `checksum/config` annotation on the pod
template (<https://helm.sh/docs/howto/charts_tips_and_tricks/#automatically-roll-deployments>).
The checksum changes with the rendered ConfigMap, which changes the pod template,
which makes the Deployment roll.

## Quick start

```bash
make check-prereqs   # docker, kind, kubectl, helm, kubeconform
make test            # lint, then the trap on a throwaway kind cluster
```

`make test` runs `helm lint` and `kubeconform` (strict, with ArgoCD CRD schemas),
creates a kind cluster with a private kubeconfig (`.kube/`, your current context
is not touched), runs the trap, and deletes the cluster. Expected lines from the
trap:

```
OK: trap reproduced. ConfigMap is v2, the pod is unchanged and still has v1.
OK: fixed chart recreated the pod with APP_ENV=v2.
```

`make up` keeps a kind cluster with the staging release installed;
`make down` removes it; `make reset` also deletes the private kubeconfig.

| | Status |
|---|---|
| macOS arm64 + colima (4 CPU / 8 GB) | verified 2026-09-29: `make test` green (also from a copied directory) and `make up` reached a Running pod. kind 0.33.0, node image `kindest/node` v1.37.0 (pinned by digest), helm 4.3.0, kubectl 1.37.1, kubeconform 0.8.0 |
| ubuntu-24.04 GitHub runner | CI only, not measured here; see `.github/workflows/gitops-argocd.yml` |
| First-run time | about 80 s for `make test` with the kind node image already local (cluster create about 25 s, two trap runs the rest); add the pull of the 1.3 GB node image on a truly cold machine (not measured) |
| RAM | peak about 2.5 GB used in the colima VM while the kind cluster ran (other containers were running too, so this is an upper bound) |

If Docker Hub rate-limits your pulls (HTTP 429), pull `nginxinc/nginx-unprivileged` once; `make` then copies the image from your local docker into the kind node instead of pulling it there.

## Traps this avoids

1. **ConfigMap change does not restart pods** (reproduced in tests). Fix: the
   `checksum/config` annotation in `templates/deployment.yaml`.
2. **Selector labels that change between releases.** A Deployment's
   `spec.selector` is immutable; putting chart version or `managed-by` in it makes
   the next `helm upgrade` fail. Selectors use `name` and `instance` only.
3. **`default` AppProject and production that follows `main`.** Two AppProjects
   restrict repos, namespaces and kinds. Production is pinned to a git tag and
   synced by hand; staging follows `main` with automated sync.
4. **ArgoCD fighting the HPA.** With autoscaling on, the template omits
   `replicas`, and the production Application has `ignoreDifferences` on
   `/spec/replicas` so ArgoCD does not revert the autoscaler.
5. **Pods that run as root on a writable filesystem.** Non-root user,
   `readOnlyRootFilesystem` (with an `emptyDir` on `/tmp`), all capabilities
   dropped, `RuntimeDefault` seccomp, no service account token. Also a
   PodDisruptionBudget (production) and `ingressClassName` on the Ingress.

## What the test proves / does NOT prove

Proves:

- On a real Kubernetes API (kind), the chart without `checksum/config` leaves the
  pod running with the old `APP_ENV` after `helm upgrade` even though the
  ConfigMap changed, and the shipped chart replaces the pod with one that has the
  new value. The broken chart is generated from the shipped one by deleting that
  single annotation line, so the two cannot drift apart.
- A failure unrelated to the ConfigMap cannot pass as the trap: `traps/guard-test.sh`
  runs the trap script with a `helm` stub that exits 42 and requires a non-zero exit
  with no case scored as "stale" (part of `make test`, needs no cluster).
- Rendered manifests validate against the Kubernetes and ArgoCD schemas
  (`kubeconform -strict`), and every Application uses the same `repoURL`.

Does NOT prove:

- That ArgoCD syncs the Applications. `make test` never installs ArgoCD. The
  manifests are schema-checked only. Sync behaviour, `ignoreDifferences` and the
  AppProject restrictions are unexercised.
- That the fix covers every config source. The checksum covers the ConfigMap this
  chart renders. A Secret, or a ConfigMap created outside the chart, needs its own
  checksum or a controller such as Reloader.
- Behaviour on managed clusters (admission policies, PSA, ingress controllers).
  The Ingress is only rendered and validated, never served.
- That `nginxinc/nginx-unprivileged:1.30.2-alpine` is current. It is an exact tag, not a
  digest, and it will age; re-check it before you copy the chart.

## Use it with ArgoCD

1. Put this directory at the root of your own git repo (or adjust every `path`
   in `apps/` and `bootstrap/`).
2. `scripts/set-repo-url.sh https://github.com/you/your-repo.git` replaces the
   placeholder in all manifests (it refuses to run if they disagree).
3. Commit, push, and tag the commit production should run: `git tag v0.2.0 && git push --tags`.
   `apps/production.yaml` pins that tag in `targetRevision`.
4. Install ArgoCD (see the ArgoCD getting-started guide; pin a release rather than `stable`; v3.5.3 was the latest GitHub release on 2026-09-29, not tested here).
5. `kubectl apply -f bootstrap/projects.yaml && kubectl apply -f bootstrap/root.yaml`
6. `kubectl -n argocd get applications`. Production shows `OutOfSync` until you
   press Sync; that is the intended gate.

To promote: tag a commit that ran in staging, change `targetRevision` in
`apps/production.yaml` through review, sync.

## Local demo vs production

- Image tag, resource requests and replica counts are demo values.
- ArgoCD itself (HA, SSO, RBAC, repo credentials for private repos, notifications)
  is out of scope.
- Real TLS, an ingress controller, network policies and secrets management are
  out of scope. `ingress.enabled` defaults to `false`.
- Renovate or similar should bump `targetRevision`, the image tag and the
  `KUBERNETES_VERSION` used for validation.

## Copy it into your project

The directory is self-contained: `charts/`, `environments/`, `apps/`,
`bootstrap/`, `scripts/`, `traps/`, `Makefile`. Copy the chart and the manifests
you need; keep `traps/configmap-rollout.sh` and `traps/guard-test.sh` if you want the regression test for
your own chart (it expects `charts/demo-app` and the `demo-app.fullname` naming).

## Layout

```
charts/demo-app/        chart: Deployment (checksum/config), Service, ConfigMap, HPA, PDB, Ingress
environments/           values for staging and production
apps/                   Applications created by the root app
bootstrap/              AppProjects and the root Application, applied once by hand
scripts/set-repo-url.sh one command to set the repo URL everywhere
traps/                  configmap-rollout.sh: broken vs fixed chart on kind
```
