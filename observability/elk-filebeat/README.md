# compose-elk-logging

A drop-in centralized logging stack for any docker-compose project:
Elasticsearch + Kibana + Filebeat. Add one label to a service in your
existing compose file and its logs start flowing into Elasticsearch —
everything else on the host stays untouched.

## Structure

```
docker-compose.yml
filebeat/filebeat.yml    # docker autodiscover config, opt-in via label
```

`demo-app` in the compose file stands in for "a service from your own
project" — it's the only thing that makes this a runnable demo instead of
just a config snippet.

## How the opt-in works

```yaml
demo-app:
  labels:
    enable_logging: "true"
```

```yaml
# filebeat/filebeat.yml
filebeat.autodiscover:
  providers:
    - type: docker
      templates:
        - condition:
            equals:
              docker.container.labels.enable_logging: "true"
          config:
            - type: container
              paths:
                - "/var/lib/docker/containers/${data.container.id}/*.log"
```

Filebeat watches Docker's container-start events for the whole host (it has
to — that's how `docker autodiscover` works), but the `condition` block means
it only actually attaches a log input for containers carrying the label.
Nothing else on the host gets touched or shipped anywhere.

## Usage — attaching to your own project

Point your project's compose file at the same Docker network as this stack
(or just add these three services into your own `docker-compose.yml`), then
add `labels: { enable_logging: "true" }` to whichever of your services you
want centralized logs for. No code changes, no logging library to add — it
reads directly from Docker's own container log files.

```bash
docker compose up -d
# ... add the label to a service, restart it ...
curl http://localhost:9200/app-logs-*/_search
# or open Kibana at :5601 and build a Discover view over app-logs-*
```

## Verified — and two real bugs found and fixed along the way

```
$ docker compose up -d
$ curl http://elk-demo-app:8080/clean-test-1   # (from a container on the same network)
$ curl http://elk-demo-app:8080/clean-test-2
$ curl http://elk-demo-app:8080/clean-test-3

$ curl http://localhost:9200/app-logs-*/_search -d '{"size":0,"aggs":{"by_container":{"terms":{"field":"container.name"}}}}'
{
  "hits": {"total": {"value": 25}},
  "aggregations": {"by_container": {"buckets": [
    {"key": "elk-demo-app", "doc_count": 25}
  ]}}
}
```

25 log lines, all from `elk-demo-app`, none from Elasticsearch/Kibana/Filebeat
itself — confirmed the opt-in label is actually scoping collection, not just
collecting everything on the host. And the content is the real nginx log line:

```
message: 2026/07/31 ... [error] ... open() "/usr/share/nginx/html/clean-test-1"
          failed (2: No such file or directory) ... request: "GET /clean-test-1 HTTP/1.1"
container.name: elk-demo-app
```

### Bug 1 — `hints.enabled` silently drops every input

First version used Filebeat's `hints.enabled: true` + a `co.elastic.logs/enabled`
label, which is the officially documented pattern. It silently collected
nothing:

```
debug | autodiscover | Configuration template cannot be resolved:
  field 'data.kubernetes.container.id' not available in event or environment
```

The implicit default template the hints builder falls back to references a
*Kubernetes* metadata field even when the provider type is `docker` — a
version-specific (8.15.0) bug/quirk, not a config mistake on my end. Adding
`hints.default_config` with an explicit docker-style path fixed the template
error, but introduced bug 2.

### Bug 2 — `hints.default_config` applies to every container, not just labeled ones

With `hints.default_config` set, Filebeat happily started shipping logs from
*all four* containers — Elasticsearch, Kibana, Filebeat itself, and the demo
app — defeating the entire point of opt-in collection (confirmed via
`container.name` aggregation showing all four). `default_config` in the hints
system is explicitly the fallback for *unlabeled* containers, which is the
opposite of what a "drop-in, opt-in" stack needs.

Fixed by dropping the hints mechanism entirely and using `templates` +
`condition` instead — autodiscover's general-purpose conditional config
selection, unrelated to the buggy hints template resolution, and it does
exactly "only configure containers matching this condition."

Left both bugs in this README instead of just quietly shipping the working
version, because "the documented way didn't work, here's what did" is more
useful than a changelog-free final config.

Stack: Elasticsearch 8.15.0, Kibana 8.15.0, Filebeat 8.15.0, tested on
Ubuntu 22.04 / Docker Compose, single-node (`discovery.type=single-node`,
security disabled — a local/demo setup, not how you'd run this stack in
front of the internet).
