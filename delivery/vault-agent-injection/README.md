# Vault Agent Injector on Kubernetes: pod stuck in Init with "permission denied" on a KV v2 secret

Level: **lab** (end-to-end script; weekly CI plus on changes to this module).

Injects HashiCorp Vault secrets into a pod with the Vault Agent Injector. The
application never talks to Vault: it reads a file written by the sidecar. The
module includes an end-to-end test that runs on a throwaway kind cluster.

## Problem

You annotate a Deployment for Vault Agent injection, the pod stays in
`Init:0/1`, and the `vault-agent-init` container logs `permission denied`
(HTTP 403) even though the Kubernetes auth role and the secret both exist.
A common cause is the policy path. On a KV version 2 mount the API path is
`secret/data/<name>`, while `vault kv get secret/<name>` hides the `data/`
segment. A policy written for `secret/<name>` grants nothing the agent needs.
The Vault KV v2 documentation describes the `data/` and `metadata/` API paths.

## Quick start

```bash
make check-prereqs   # docker, kind, kubectl, helm
make test            # cluster, Vault, injector, broken policy fails, fixed policy works
```

`make test` copies `.env.example` to `.env` if needed, creates a kind cluster with
a private kubeconfig (`.kube/`), runs `scripts/e2e.sh`, and deletes the cluster.
Expected lines:

```
OK: trap reproduced. Login worked, the read of secret/data/demo-app was denied, the app is not running.
OK: the app read the secret from /vault/secrets and reported its SHA-256.
OK: no secret value in the Deployment.
```

`make up` runs the same script and keeps the cluster; running `scripts/e2e.sh` again on
that cluster works (the Vault release is reused and the app pod is recreated before every
inspection, so logs from an earlier run never count); `make down` removes it;
`make reset` also deletes `.kube/` and `.env`.

| | Status |
|---|---|
| macOS arm64 + colima (4 CPU / 8 GB) | verified 2026-09-30: `make test` green from a copied directory (1 min 40 s), and `scripts/e2e.sh` re-run on a kept cluster. hashicorp/vault chart 0.34.1 (Vault 2.0.4, vault-k8s 1.7.6), kind 0.33.0, node image v1.37.0 pinned by digest, helm 4.3.0 |
| ubuntu-24.04 GitHub runner | CI only, not measured here; see `.github/workflows/vault-agent-injection.yml` |
| First-run time | about 67 s for `make test` with the kind node image and the Vault images already pulled once; a cold machine adds the image pulls (not measured) |
| RAM | peak about 1.7 GB used in the colima VM (kind node, Vault dev pod, injector, app; other containers were running too, so an upper bound) |

The module stays at `lab` until the
script has been stable across several weekly runs.

## Traps this avoids

1. **Policy written for the KV v1-style path** (reproduced in tests). The policy
   in `policies/demo-app-policy.hcl` uses `secret/data/demo-app`;
   `traps/broken-policy.hcl` uses `secret/demo-app` and leaves the pod without secrets.
2. **Secrets in the pod spec.** The Deployment has annotations and a template,
   no values. The test checks that the secret does not appear in the Deployment.
3. **Root token in the repo.** The dev root token comes from `.env` (git-ignored;
   only `.env.example` is committed) and is passed to Helm on the command line.
4. **Unpinned chart.** The `hashicorp/vault` chart version is pinned in
   `.env.example`; images come from that chart version.
5. **Apps that need a Vault SDK.** The test app only reads `/vault/secrets/db-creds`.

## What the test proves / does NOT prove

Proves, on a real cluster:

- With the broken policy, a freshly created pod's `vault-agent-init` logs in successfully
  (so the role and service account are fine) and is then denied on
  `GET /v1/secret/data/demo-app`; the app container never becomes ready. A denied login
  is not accepted as the trap. With the fixed policy and another fresh pod, the app starts
  and the init container renders `/vault/secrets/db-creds`.
- The app returns the SHA-256 of a random `db_password` written to Vault at test
  time, computed independently by the script, and does not return the raw value.

Does NOT prove:

- Anything about production Vault. Dev mode is unsealed, in-memory, single-node,
  with a root token. No HA, storage backend, auto-unseal, TLS, audit log or
  token policies for operators.
- Secret rotation. The sidecar renewal path is not exercised.
- That the pinned chart and images stay current. 0.34.1 was the newest chart on
  2026-09-29; see `VAULT_CHART_VERSION` in `.env.example` and check it against the Helm repo.
- That Vault has no warnings: it prints one about the role having no audience configured.
- Other auth methods, namespaces (Vault Enterprise), or the CSI provider and
  External Secrets alternatives.

## Local demo vs production

- Run Vault outside the cluster or in HA mode with a real storage backend
  (integrated Raft), TLS and auto-unseal through a cloud KMS or HSM.
- Replace the root token with scoped operator policies and audit logging.
- Bind roles to exact service account names and namespaces (the demo does) and
  keep policies to one path each.
- Decide how secret rotation reaches the app: the file changes, the app must
  re-read it (this demo reads it on every request).
- Consider `agent-init-first` and resource limits for the agent containers.

## Copy it into your project

Copy `manifests/`, `policies/`, and the parts of `scripts/e2e.sh` you want as a
smoke test. The module has no references outside its directory. Change the role
name, namespace and secret path together: the policy, the Vault role, the service
account and the annotations must agree.

## Layout

```
manifests/vault-values.yaml   Helm values for hashicorp/vault (dev mode + injector)
manifests/serviceaccount.yaml namespace and service account
manifests/app.yaml            demo app (reads /vault/secrets, returns hashes) with the annotations
policies/demo-app-policy.hcl  read on secret/data/demo-app only
traps/broken-policy.hcl       the trap: secret/demo-app (wrong for KV v2)
scripts/e2e.sh                the end-to-end test
```
