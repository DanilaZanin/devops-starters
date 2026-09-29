# rabbitmq-task-queue

A small task queue on top of RabbitMQ: publish a task, a worker consumes it,
failed tasks get retried with a delay a fixed number of times, and tasks
that never succeed land in a dead-letter queue instead of retrying forever
or getting silently dropped.

## Why build this instead of using Celery

Celery is the obvious answer for anything beyond a toy project, but it's a
lot of machinery (its own scheduler, worker pool model, serialization
layer). This is the ~150 lines of it I actually reach for most often: publish
a JSON task, consume it, retry-with-delay on failure, dead-letter after N
attempts. Good enough for a handful of background jobs, not trying to
replace Celery for anything serious.

## How the retry delay works without a plugin

RabbitMQ has no built-in "redeliver after N seconds," and the delayed-message
exchange is a community plugin, not core. Standard workaround, used here:

```
tasks_exchange --> tasks (queue workers consume from)

tasks_retry_exchange --> tasks_retry (queue with x-message-ttl=3000ms
                          and x-dead-letter-exchange=tasks_exchange)
```

A failed message gets republished into `tasks_retry` instead of `tasks`. It
sits there doing nothing for 3 seconds (the TTL), and when the TTL expires
RabbitMQ dead-letters it — which, despite the name, just means "route it
somewhere else per queue config" — straight back onto `tasks_exchange`, so
it's redelivered to a worker. No plugin, no external scheduler, just core
queue arguments.

`x-retry-count` travels in the message headers and gets incremented on each
requeue; once it hits `MAX_RETRIES` (3), the message goes to
`tasks_dead_exchange` / `tasks_dead` instead of being retried again.

## Structure

```
taskqueue/__init__.py   # topology setup, publish_task, retry/dead-letter routing
taskqueue/worker.py       # @task decorator + registry, message handling loop
demo_tasks.py               # two demo tasks (see below)
run_worker.py                 # entrypoint that registers demo_tasks and starts the worker
produce_demo.py               # publishes one of each demo task
docker-compose.yml
Dockerfile
```

## The two demo tasks

- `flaky_task` — fails `fail_times` attempts, then succeeds. Proves a task
  can recover through the retry path.
- `always_fails` — always raises. Proves a task that never succeeds ends up
  in the dead-letter queue after `MAX_RETRIES`, not retried forever.

## Usage

```bash
docker compose up -d --build
docker exec -e RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/ taskqueue-worker python produce_demo.py
docker logs -f taskqueue-worker
```

RabbitMQ's management UI is at `:15672` (guest/guest) if you want to watch
the queues fill and drain visually instead of reading logs.

## Verified — watched both paths actually happen

```
$ docker exec ... python produce_demo.py
published job-1 (flaky_task) and job-2 (always_fails)

$ docker logs -f taskqueue-worker
WARNING taskqueue.worker: task 'flaky_task' attempt 1 failed (...), scheduling retry 1/3
WARNING taskqueue.worker: task 'always_fails' attempt 1 failed (...), scheduling retry 1/3
WARNING taskqueue.worker: task 'flaky_task' attempt 2 failed (...), scheduling retry 2/3
WARNING taskqueue.worker: task 'always_fails' attempt 2 failed (...), scheduling retry 2/3
INFO    taskqueue.worker: task 'flaky_task' succeeded on attempt 3
WARNING taskqueue.worker: task 'always_fails' attempt 3 failed (...), scheduling retry 3/3
ERROR   taskqueue.worker: task 'always_fails' exhausted 3 retries (...), sending to dead-letter queue
```

And confirmed the dead-lettered message is actually sitting in the DLQ with
its failure reason attached, via the management API:

```
$ curl -u guest:guest http://localhost:15672/api/queues/%2F/tasks_dead
messages in DLQ: 1

$ curl -u guest:guest -X POST .../tasks_dead/get -d '{"count":5,...}'
{
  "payload": "{\"task\": \"always_fails\", \"payload\": {\"id\": \"job-2\"}}",
  "properties": {"headers": {"x-last-error": "task job-2 is designed to always fail"}}
}
```

## A real bug I hit and fixed

First run, the worker container crashed on startup with `Connection refused`
even though `docker-compose.yml` had `depends_on: condition: service_healthy`
on RabbitMQ. Turns out RabbitMQ's own healthcheck
(`rabbitmq-diagnostics ping`) only confirms the Erlang node is up — it can
report healthy slightly before the AMQP listener on 5672 is actually
accepting connections. Fixed by adding retry-with-backoff to `connect()`
itself (10 attempts, 2s apart) instead of trusting the healthcheck as a
guarantee. Worth knowing generally: `depends_on: service_healthy` is a
weaker guarantee than it looks for RabbitMQ specifically.

Stack: RabbitMQ 3.13 (management image), `pika` 1.3.2, Python 3.12, tested
on Ubuntu 22.04 with Docker Compose.
