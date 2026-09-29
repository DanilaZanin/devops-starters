# vault-k8s-secrets-demo

A reference setup for injecting HashiCorp Vault secrets into a Kubernetes pod
via the Vault Agent Injector — no application code ever talks to Vault's API,
it just reads a file the sidecar wrote for it.

## Why this pattern

The alternative (app fetches secrets itself with a Vault SDK + its own token
lifecycle) means every service reimplements auth, renewal, and retry logic.
The injector pattern moves all of that into a sidecar that's configured once
per role — the app just reads `/vault/secrets/<name>` like any other file.

## Structure

```
manifests/
  vault-values.yaml     # helm values for the official hashicorp/vault chart (dev mode + injector)
  serviceaccount.yaml    # namespace + the service account the pod authenticates as
  app-deployment.yaml     # the pod, with vault.hashicorp.com/* injection annotations
policies/
  demo-app-policy.hcl      # read-only access to secret/data/demo-app, nothing else
```

## How it fits together

1. `auth/kubernetes` — Vault trusts the cluster's own service account tokens
   to prove pod identity (configured against the in-cluster API server, no
   extra credentials to manage).
2. `auth/kubernetes/role/demo-app` — binds the `demo-app` service account in
   the `demo-app` namespace to the `demo-app` policy.
3. `policies/demo-app-policy.hcl` — read-only on exactly one path
   (`secret/data/demo-app`). Least privilege: this role can't read any other
   app's secrets.
4. `app-deployment.yaml` annotations tell the injector webhook to add an
   `init` container (fetches the secret once, writes it, exits) and a
   sidecar (keeps it renewed) to any pod matching the `demo-app` service
   account — the Deployment spec itself has zero Vault-specific code.

## Usage

```bash
helm repo add hashicorp https://helm.releases.hashicorp.com
kubectl create namespace vault
helm install vault hashicorp/vault -n vault -f manifests/vault-values.yaml

kubectl -n vault exec vault-0 -- env VAULT_TOKEN=root vault kv put secret/demo-app \
  db_password="..." api_key="..."
kubectl -n vault exec vault-0 -- env VAULT_TOKEN=root vault auth enable kubernetes
kubectl -n vault exec vault-0 -- sh -c 'VAULT_TOKEN=root vault write auth/kubernetes/config \
  kubernetes_host="https://$KUBERNETES_SERVICE_HOST:$KUBERNETES_SERVICE_PORT"'
kubectl -n vault exec vault-0 -- env VAULT_TOKEN=root vault policy write demo-app - < policies/demo-app-policy.hcl
kubectl -n vault exec vault-0 -- env VAULT_TOKEN=root vault write auth/kubernetes/role/demo-app \
  bound_service_account_names=demo-app bound_service_account_namespaces=demo-app \
  policies=demo-app ttl=1h

kubectl apply -f manifests/serviceaccount.yaml
kubectl apply -f manifests/app-deployment.yaml
```

Dev mode (`server.dev.enabled: true` in the values file) is unsealed
automatically and stores everything in memory — right for this demo, wrong
for anything you'd actually keep secrets in. Production would mean HA mode,
a real storage backend (Raft/Consul), and auto-unseal via a cloud KMS.

## Verified — actually deployed on a real cluster

Spun up a local `kind` cluster, installed Vault dev mode + the injector via
the official chart, and ran the full flow above for real:

```
$ kubectl -n demo-app get pods
demo-app-55855464cd-xmkjg   2/2     Running   0   5s     # 2/2 = app container + vault-agent sidecar

$ kubectl -n demo-app exec demo-app-55855464cd-xmkjg -c demo-app -- cat /vault/secrets/db-creds
DB_PASSWORD=s3cr3t-db-pass
API_KEY=demo-api-key-12345
```

The `demo-app` container itself is a stock `nginx-unprivileged` image with no
Vault SDK, no token, no network call to Vault in its own code — the secret
just showed up as a file because of the pod's service account + the
annotations. That's the entire point of the injector pattern.

Stack: Kubernetes 1.31 (kind), Vault (official hashicorp/vault Helm chart,
dev mode), Vault Agent Injector, tested on Ubuntu 22.04.
