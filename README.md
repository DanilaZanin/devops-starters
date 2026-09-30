# devops-starters

Copy-paste DevOps starters. Each module ships a test that reproduces the production trap it avoids: the broken variant fails, the shipped one passes.

```console
$ cd infra/ansible-docker-host && make test
...
OK: broken hardening failed the sshd -T check as expected
...
default: actions=7 successful=7 failed=0
```

Most SSH hardening roles edit `/etc/ssh/sshd_config`. On Ubuntu cloud images, `sshd_config.d/50-cloud-init.conf` is read first, and sshd keeps the first value it sees, so `PasswordAuthentication no` never takes effect. The test above proves the role in this repo does not have that bug, and fails if someone reintroduces it.

## Modules

| Module | Trap it avoids | Level |
|---|---|---|
| [infra/ansible-docker-host](infra/ansible-docker-host) | SSH hardening silently overridden by cloud-init; custom SSH port that locks you out through ufw | verified |
| [delivery/gitops-argocd](delivery/gitops-argocd) | ConfigMap change in a Helm chart does not restart pods | verified |
| [data/rabbitmq-retry-dlq](data/rabbitmq-retry-dlq) | Poison message crashes the consumer and requeues forever; retry without publisher confirms loses messages | verified |
| [data/redis-cache-aside](data/redis-cache-aside) | Cache stampede on a cold key; API returns 500 when Redis is down | verified |
| [delivery/vault-agent-injection](delivery/vault-agent-injection) | Pod stuck in Init with "permission denied" because the policy path misses `data/` on KV v2 | lab |
| [delivery/gitlab-ci-terraform](delivery/gitlab-ci-terraform) | Terraform image entrypoint breaks CI scripts; apply runs outside main; state dies with the job | lab |
| [infra/terraform-docker-modules](infra/terraform-docker-modules) | Replicas fail with "port is already allocated" | lab |
| [data/kafka-spark-pipeline](data/kafka-spark-pipeline) | One malformed event fails the sink and the streaming job replays it forever | lab |
| [data/lakehouse-trino-iceberg](data/lakehouse-trino-iceberg) | Re-running a load duplicates rows | lab |
| [observability/elk-filebeat](observability/elk-filebeat) | Filebeat ships logs from every container instead of the labelled ones | lab |

**verified**: the trap test runs on every pull request that touches the module, and weekly.
**lab**: static checks on every pull request that touches the module; the full run (compose stack or kind cluster) at least weekly and on demand.

Each module README states what its test proves and what it does not prove. A container is not a cloud VM, and a static pipeline check is not a GitLab run; where that matters, the README says so.

## Use one

Every module is self-contained. Copy the folder, nothing else:

```bash
cp -r data/redis-cache-aside ~/src/my-service/cache-demo
cd ~/src/my-service/cache-demo
make check-prereqs && make test
```

CI checks exactly this: each workflow copies its module to a temporary directory and runs `make test` there.

Every module has the same targets: `make up`, `make test`, `make down`, `make reset` (drops data), `make check-prereqs`.

Tested on macOS arm64 with colima (4 CPU, 8 GB) and on GitHub-hosted ubuntu-24.04 runners. Module READMEs list RAM and first-run time.

## Versions

Images, charts, providers and actions are pinned. Renovate proposes updates for the ones it can detect (Dockerfiles, compose files, GitHub Actions, Terraform providers, Python dependencies), and the module tests decide whether an update is safe. A few pins live in Makefiles and variables and are bumped by hand.

## License

MIT. See [LICENSE](LICENSE).
