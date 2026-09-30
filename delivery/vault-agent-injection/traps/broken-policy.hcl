# THE TRAP. Looks right if you think in `vault kv get secret/demo-app` terms,
# but on a KV v2 mount the API path is secret/data/demo-app, so this grants
# nothing that the agent needs and the injected pod never starts.
# Only used by scripts/e2e.sh. Never apply this outside the test.
path "secret/demo-app" {
  capabilities = ["read"]
}
