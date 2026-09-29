# gitops-helm-argocd-starter

A GitOps starter kit: one Helm chart (`demo-app`), two environment overlays
(staging/production), and an ArgoCD "app of apps" that syncs both from a
single root Application. Register `apps/root.yaml` once in ArgoCD and it
discovers and manages everything else in `apps/` on its own.

## Structure

```
charts/demo-app/           # the Helm chart itself
  Chart.yaml
  values.yaml               # base defaults
  templates/                # Deployment, Service, ConfigMap, HPA, Ingress
environments/
  staging/values.yaml        # overrides: 1 replica, APP_ENV=staging
  production/values.yaml     # overrides: 3 replicas, HPA 3-6, APP_ENV=production
apps/
  root.yaml                  # register only this one in ArgoCD
  staging.yaml                # Application -> charts/demo-app + staging values
  production.yaml             # Application -> charts/demo-app + production values
```

## How the app-of-apps pattern works here

`apps/root.yaml` is an ArgoCD `Application` whose source is the `apps/`
directory itself (with `root.yaml` excluded so it doesn't try to sync
itself). ArgoCD applies every other manifest it finds there as plain
Kubernetes objects — which happens to mean "create these two more
`Application` objects." Those get picked up by ArgoCD's own controller and
synced normally. Add a `apps/new-environment.yaml` and it shows up with zero
extra ArgoCD configuration.

`staging.yaml` / `production.yaml` both point at the same chart
(`charts/demo-app`) but load a different `values.yaml` on top via
`spec.source.helm.valueFiles`, so the two environments never drift out of
sync on templates — only on the numbers that should actually differ
(replica count, resource limits, autoscaling).

## Usage

1. Push this repo to your own git remote and edit the `repoURL` in the three
   files under `apps/` to point at it (`sed -i 's#YOUR_USERNAME#you#' apps/*.yaml`).
2. Install ArgoCD (`kubectl create ns argocd && kubectl apply -n argocd --server-side -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml`).
3. `kubectl apply -f apps/root.yaml`
4. Watch it: `kubectl -n argocd get applications`

## Verified — actually deployed, not just `helm template`

I didn't have a spare cloud Kubernetes cluster, so I stood up a local one
with `kind`, installed real ArgoCD into it, self-hosted a throwaway Gitea
instance on the same Docker network to act as the git remote (ArgoCD needs
real git smart-HTTP, not just static files), pushed this repo to it, and
registered `root.yaml` for real:

```
$ kubectl -n argocd get applications
NAME                  SYNC STATUS   HEALTH STATUS
demo-app-production   Synced        Progressing
demo-app-staging      Synced        Healthy
root                  Synced        Healthy

$ kubectl -n demo-app-staging get pods
demo-app-staging-demo-app-596d88fd6c-hxlbc   1/1   Running   0   40s   # 1 replica, matches staging values

$ kubectl -n demo-app-production get pods
demo-app-production-demo-app-b7497766f-lc8gh   1/1   Running   0   40s
demo-app-production-demo-app-b7497766f-lrsf8   1/1   Running   0   25s
demo-app-production-demo-app-b7497766f-sv6qj   1/1   Running   0   25s   # 3 replicas, matches production values

$ kubectl -n demo-app-production get hpa
NAME                                REFERENCE                                 MINPODS   MAXPODS   REPLICAS
demo-app-production-demo-app        Deployment/demo-app-production-demo-app   3         6         3
```

Then tested the actual point of GitOps — self-heal on manual drift:

```
$ kubectl -n demo-app-staging scale deployment demo-app-staging-demo-app --replicas=5
$ kubectl -n demo-app-staging get pods --no-headers | wc -l
5
# ~40s later, ArgoCD's controller notices the live state doesn't match git and reverts it:
$ kubectl -n demo-app-staging get pods --no-headers | wc -l
1
```

Nobody had to `kubectl apply` anything to fix that — git was the source of
truth and ArgoCD enforced it, which is the entire point of the pattern.

One real snag along the way, left in because it's a common gotcha: my first
attempt served the git repo as static files over nginx ("dumb" HTTP). ArgoCD
uses git's smart HTTP protocol (`git-upload-pack`) and failed with
`failed to list refs: unexpected EOF` — static file serving doesn't implement
that endpoint. Switched to a real git server (Gitea) and it worked immediately.

Stack: Kubernetes 1.31 (kind), ArgoCD (stable), Helm 3.16, tested on Ubuntu 22.04.
