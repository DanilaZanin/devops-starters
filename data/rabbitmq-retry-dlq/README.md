# RabbitMQ consumer that survives poison messages: TTL retry queue, dead-letter queue, publisher confirms (Python, pika)

**Level: verified.** The trap tests run in CI on every PR that touches this folder, and weekly.

An example application, not a library: a consumer for `orders` messages that retries failed messages after a delay, gives up after a fixed number of retries, and never retries a message that cannot succeed. Copy the pieces you need.

## Problem

A consumer that catches every exception and calls `basic_nack(requeue=True)` gets stuck on the first message that is not valid JSON. The broker hands the same message straight back, the consumer fails again, and with prefetch 1 every message behind it waits. CPU goes up, throughput goes to zero, nothing shows up as an error.

The usual repair, "on failure publish a copy to a retry queue, then ack", has a second hole. If that publish is not confirmed by the broker (no publisher confirms, no `mandatory` flag), it can fail silently, and the ack that follows deletes the last copy of the message.

## Quick start

```bash
make test    # starts RabbitMQ 4.3, then runs the trap tests through uv
make demo    # starts the consumer and publishes 4 sample messages
make reset   # removes containers and data
```

Expected `make test` result: `8 passed`. Expected `make demo` tail, once the retries have run out (about 15 seconds):

```
name           messages_ready  messages_unacknowledged
orders         0               0
orders.retry   0               0
orders.dead    2               0
```

The two dead-lettered messages are the poison one (invalid JSON) and `order-3`, which fails on every attempt. The management UI is at http://127.0.0.1:15672 (user and password from `.env`).

Requirements: docker with compose v2, [uv](https://docs.astral.sh/uv/), make. `make check-prereqs` verifies them.

| Verified on | RAM | First run (cold image cache) |
|---|---|---|
| 2026-09-29, macOS arm64, colima 4 CPU / 8 GB, RabbitMQ 4.3.6, `make test`: 8 passed (not yet run on an ubuntu-24.04 runner) | about 120 MiB (RabbitMQ container, sampled with `docker stats`) | about 29 s including the image pull; about 19 s with the image cached |

## Traps this avoids

1. **Poison message loops forever** (reproduced in tests). Invalid JSON goes straight to the DLQ with the parse error in the `x-last-error` header, without retries. The good message behind it is processed.
2. **Republish + ack without confirms loses messages** (reproduced in tests). Retry and DLQ publishes use a confirm-mode channel with `mandatory=True`. If the broker cannot route or accept the copy, the original is nacked back to the queue instead of acked.
3. **Retry count is bounded.** `MAX_RETRIES=3` means one first attempt plus exactly three retries (four handler calls), then the DLQ. The count travels in the `x-retry-count` header.
4. **Default `guest` user and open ports.** The broker is started with a user from `.env` (which replaces `guest`), and ports are published on 127.0.0.1 only.
5. **`depends_on: service_healthy` is not a guarantee.** `rabbitmq-diagnostics ping` can pass before the AMQP listener accepts connections. The healthcheck uses `check_port_connectivity`, and `connect()` retries anyway.

## What the test proves / does NOT prove

The tests run a broken consumer (`traps/broken_consumer.py`) and the real one (`app/consumer.py`) against a real RabbitMQ, and require the broken one to fail. If the broken variant ever passes, the suite fails.

Proves:
- with a poison message at the head of the queue, the broken consumer never dead-letters anything and the good message is not handled; the real consumer dead-letters the poison message and handles the good one;
- when the retry queue has disappeared, the broken consumer acks and loses the message; the real one keeps it;
- a failing message is handled exactly `MAX_RETRIES + 1` times, then lands in the DLQ with its error and retry count;
- a message that recovers on a retry is not dead-lettered;
- `guest/guest` is rejected.

Does NOT prove:
- Delivery is at-least-once. A crash between the retry publish and the ack produces a duplicate, so handlers must be idempotent. This is not tested.
- The message-loss trap is reproduced by deleting the retry queue while the consumer runs. Other causes (a broker resource alarm, a network drop between publish and confirm) are not tested.
- Broker restarts, disk persistence and clustering.
- Throughput. A confirm per message is slow; at volume you batch confirms.
- Quorum queues. RabbitMQ 4.0 and later give quorum queues a default delivery limit, which changes how the requeue loop ends. These tests use classic queues.

## Local demo vs production

This runs one node, over plain AMQP, with the password in a local `.env`. For production you also need:
- TLS on AMQP and on the management port, credentials from a secrets manager;
- quorum queues (or streams) and a cluster if you cannot lose the node;
- an alert on the DLQ depth, and a way to replay or discard dead letters;
- idempotent handlers (see above) and a backoff that grows: a single fixed `RETRY_DELAY_MS` hammers a failing dependency at a constant rate;
- changing `RETRY_DELAY_MS` on a live broker fails with `PRECONDITION_FAILED`, because queue arguments cannot be redeclared. Plan a migration or a new queue name; here `make reset` deletes the data.

## Copy it into your project

```
app/config.py      settings and queue names
app/messaging.py   connect() with retry, publish_confirmed()
app/topology.py    exchanges, queues, the TTL retry queue
app/consumer.py    handle_delivery(): the retry / dead-letter decision
app/handlers.py    your business logic goes here
```

Keep `pyproject.toml` (or the pinned `requirements.txt`), the `Dockerfile` and `.env.example`. Copy `tests/` and `traps/` too if you want the same guarantees for your handler. The whole folder also works on its own: `cp -r data/rabbitmq-retry-dlq /elsewhere && cd /elsewhere && make test`.

Pins: RabbitMQ 4.3.6 (management image), pika 1.4.4, Python 3.12.
