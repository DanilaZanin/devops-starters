# Filebeat autodiscover collecting logs from every container (co.elastic.logs/enabled ignored): opt-in ELK stack with security and 7-day retention

**Level: lab.** Every PR gets the static checks (`make lint`). The full smoke run (`make test`) runs weekly and on demand, not on every PR.

Elasticsearch, Kibana and Filebeat 9.x for a Docker host. Filebeat ships the logs of containers that carry the label `co.elastic.logs/enabled: "true"`, and only those.

## Problem

Filebeat's Docker autodiscover with hints is documented as "label a container and its logs are collected". In practice it is easy to end up with one of two broken states. Either nothing is collected (on 8.15 the implicit default input template failed to resolve and the input was silently dropped), or, once you add a `hints.default_config` to work around that, everything is collected: Elasticsearch, Kibana, Filebeat itself and every other container on the host, whatever their labels. Attaching the stack to an existing host then floods the index with logs you never meant to ship.

The original version of this module also ran Elasticsearch with security off, kept two `filebeat.yml` files, and mentioned one label in a comment while the compose file used another.

## Quick start

```bash
make up       # starts Elasticsearch, Kibana, Filebeat, a Docker socket proxy and two demo containers
make test     # static checks, then a smoke run (wipes this module's data before and after)
make reset    # removes containers and all data
```

Then open http://127.0.0.1:5601, log in as `elastic` with `ELASTIC_PASSWORD` from `.env`, create a data view for `app-logs-*` and open Discover. You should see `demo log line N` messages from the `demo-app` container and no `quiet log line` messages from `quiet-app`, which has no label. `make test` ends with `SMOKE PASSED` and removes its containers and data again, so no test document stays in the index.

Requirements: docker with compose v2, python3, make. Budget roughly 4 GB of RAM for Docker (Elasticsearch heap is 512 MB; Kibana is the hungry one). On a Linux host, Elasticsearch needs `vm.max_map_count` of at least 262144; `make check-prereqs` tells you and prints the command (`sudo sysctl -w vm.max_map_count=262144`). On macOS the check is skipped; if Elasticsearch will not start there, look at the setting inside the Docker VM.

| Verified on | RAM | First run (cold image cache) |
|---|---|---|
| 2026-09-29, macOS arm64, colima 4 CPU / 8 GB, Elastic 9.5.4, `make test`: SMOKE PASSED, both directions of the trap, run twice (not yet run on an ubuntu-24.04 runner) | about 2.8 GiB in total: Kibana 1.7 GiB, Elasticsearch 1.05 GiB (512 MB heap), Filebeat 40 MiB, docker-proxy a few MiB (`docker stats`) | about 95 s for `make test` with the images pulled; the pull of about 1.5 GB is extra |

## Traps this avoids

1. **Opt-in collection that is not really opt-in** (reproduced in tests). `filebeat/filebeat.yml` sets `hints.default_config.enabled: false`, so only labeled containers are collected. `traps/filebeat.collect-all.yml` is the same file without that line.
2. **Security off.** Security is on. A `setup` service sets the `kibana_system` password and creates a `filebeat_writer` user that can only create indices and write documents into `app-logs-*`. Filebeat does not use the `elastic` superuser. All passwords come from `.env`, which is not committed.
3. **Logs kept forever.** An ILM policy deletes an index 7 days after creation. Filebeat writes one index per day (`app-logs-YYYY.MM.dd`), so about a week of logs is kept. The policy and the index template come from the `setup` service, so Filebeat needs no ILM privileges.
4. **Single-node cluster stuck yellow.** The index template sets replicas to 0.
5. **Data lost on restart.** Elasticsearch data and Filebeat's registry live on named volumes; without the registry Filebeat would re-ship everything after a restart.

6. **Raw Docker socket in a root container.** Mounting `/var/run/docker.sock:ro` into Filebeat does not make it read-only: the `:ro` flag covers the socket file, not the API behind it, so a compromised Filebeat could still create or kill containers. (Docker documents [the daemon attack surface](https://docs.docker.com/engine/security/).) Filebeat talks to a proxy instead: the pinned `tecnativa/docker-socket-proxy` (tag and digest) image with our own HAProxy config (`docker-proxy/haproxy.cfg`). The image's env switches allow whole prefixes (`CONTAINERS=1` also lets `GET /containers/{id}/attach/ws` through, which can feed stdin to a container), so the config allows only `GET /version`, `/info`, `/_ping`, `/containers/json`, `/containers/{id}/json` and `/events`, and answers 403 to everything else (reproduced in tests). `tests/check_compose.py` also fails if any other service mounts the socket.

Ports are published on 127.0.0.1 only.

## What the test proves / does NOT prove

The smoke test starts from a clean slate, waits for the stack, and then checks that:
- an anonymous request to Elasticsearch gets 401;
- the ILM policy exists and deletes after 7d;
- logs of the labeled `demo-app` arrive in `app-logs-*`;
- logs of the unlabeled `quiet-app` do not;
- with the broken config swapped in, the unlabeled logs do arrive (so the previous check can fail);
- the broken config still ships only this compose project (its autodiscover template matches container names `<COMPOSE_PROJECT_NAME>-*`): a container outside it that logs a marker line never reaches Elasticsearch, and Filebeat's log never mentions its id, so its files are not even opened. The project name comes from `COMPOSE_PROJECT_NAME`, so `COMPOSE_PROJECT_NAME=other make test` works too; a failing teardown makes the run fail (`tests/cleanup_selftest.sh`);
- the Filebeat container has no Docker socket mount, and the proxy answers 200 for exactly those six GET paths and 403 for `attach/ws`, `logs`, `archive`, `export`, `exec`, container create, kill and delete, image and volume listing;
- the count helper fails on an unreachable Elasticsearch and on an HTTP 401 (it used to print 0 there, which made the "unlabeled logs are absent" check pass without Elasticsearch);
- Kibana comes up.

Does NOT prove:
- That the broken config is harmless on a busy host outside the test: the real trap config still reads every container's log file and drops the foreign events afterwards.
- That ILM actually deletes anything: policy timing (`indices.lifecycle.poll_interval`, 7 real days) is not exercised.
- Log parsing. Messages are shipped as raw text; there are no ingest pipelines and no field mappings beyond dynamic ones.
- Multi-line logs, high volume, or backpressure.
- That the `hints` mechanism behaves the same on other Filebeat versions. If a future version ignores `hints.default_config.enabled`, the smoke test's second check will catch it. The old `container` input no longer exists in Filebeat 9.x (autodiscover rejects it with a config-check error and ships nothing); the config uses a `filestream` input with the `container` parser and a per-container `id`. The 8.15 note above was not re-tested.

## Local demo vs production

- HTTP and transport TLS are off. Passwords cross the docker network in clear text. Turn TLS on (and provide certificates) before this leaves a single machine.
- Single node, 512 MB heap, no snapshots. Production needs at least three nodes for the data tier, sized heap and snapshots to a repository.
- Filebeat runs as root because it reads other containers' log files. The Docker API goes through the read-only proxy, but read access is not harmless: `GET /containers/{id}/json` returns every container's environment variables (the one container endpoint left open). The proxy itself runs as root and holds the socket; keep it on the internal `docker-api` network, which only Filebeat joins. The config is copied into the image (`filebeat/Dockerfile`), not bind-mounted, so the stack also starts from a copy of the directory that the Docker VM cannot see (macOS `$TMPDIR` with colima); the same goes for `setup/setup.sh`. The smoke test builds the broken variant with `FILEBEAT_CONFIG=traps/filebeat.collect-all.yml`.
- A daily index with a 7 day delete is the simplest retention. With real volume, use data streams with rollover by size.
- Kibana's encryption key is a placeholder in `.env.example`. Generate your own.

## Copy it into your project

To attach it to an existing compose project: add the `filebeat` and `docker-proxy` services and the `elasticsearch`, `setup` and `kibana` ones they need (or point `filebeat` at the same Docker network) and put

```yaml
labels:
  co.elastic.logs/enabled: "true"
```

on each service whose logs you want. Keep `filebeat/filebeat.yml`, `setup/setup.sh`, `.env.example` and the `elasticsearch`, `setup`, `kibana`, `filebeat` and `docker-proxy` services together. The whole folder also works on its own: `cp -r observability/elk-filebeat /elsewhere && cd /elsewhere && make test`.

Pins: Elasticsearch, Kibana and Filebeat 9.5.4, docker-socket-proxy v0.5.0 as the base of `docker-proxy/Dockerfile` (digest `sha256:1f5038b5...3459`, checked against Docker Hub on 2026-09-30), BusyBox 1.37.0 for the demo containers.
