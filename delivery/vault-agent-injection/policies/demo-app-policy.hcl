# KV v2 stores data under <mount>/data/<path>. The policy must name the API
# path (secret/data/demo-app), not the path you type in `vault kv get secret/demo-app`.
path "secret/data/demo-app" {
  capabilities = ["read"]
}
