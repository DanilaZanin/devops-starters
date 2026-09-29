"""
A small task queue on top of RabbitMQ: publish a task, a worker consumes it,
and if the handler raises, the message gets retried with a delay a fixed
number of times before landing in a dead-letter queue for inspection.

RabbitMQ has no built-in "retry after N seconds" primitive, so this uses the
standard trick: a retry queue with a message TTL and a dead-letter-exchange
pointing back at the main queue. When a message's TTL expires in the retry
queue, RabbitMQ dead-letters it right back into circulation — no delayed-
message plugin required, just core exchange/queue features.
"""
import json
import logging
import time

import pika

logger = logging.getLogger("taskqueue")

MAIN_EXCHANGE = "tasks_exchange"
MAIN_QUEUE = "tasks"
RETRY_EXCHANGE = "tasks_retry_exchange"
RETRY_QUEUE = "tasks_retry"
DEAD_EXCHANGE = "tasks_dead_exchange"
DEAD_QUEUE = "tasks_dead"

RETRY_DELAY_MS = 3000
MAX_RETRIES = 3


def connect(url: str, retries: int = 10, retry_delay_s: float = 2.0) -> pika.BlockingConnection:
    # rabbitmq's own healthcheck (rabbitmq-diagnostics ping) can report
    # healthy before the AMQP listener is actually accepting connections,
    # so a container that depends_on: condition: service_healthy can still
    # race it on a cold start. Retry instead of trusting the healthcheck blindly.
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return pika.BlockingConnection(pika.URLParameters(url))
        except pika.exceptions.AMQPConnectionError as exc:
            last_error = exc
            logger.warning("rabbitmq not ready yet (attempt %d/%d): %s", attempt, retries, exc)
            time.sleep(retry_delay_s)
    raise last_error


def setup_topology(channel: pika.adapters.blocking_connection.BlockingChannel) -> None:
    """Idempotent: declares the exchanges/queues if they don't already exist.
    Safe to call from both the producer and the worker on startup."""
    channel.exchange_declare(MAIN_EXCHANGE, exchange_type="direct", durable=True)
    channel.exchange_declare(RETRY_EXCHANGE, exchange_type="direct", durable=True)
    channel.exchange_declare(DEAD_EXCHANGE, exchange_type="direct", durable=True)

    channel.queue_declare(MAIN_QUEUE, durable=True)
    channel.queue_bind(MAIN_QUEUE, MAIN_EXCHANGE, routing_key=MAIN_QUEUE)

    # messages sit here for RETRY_DELAY_MS, then RabbitMQ dead-letters them
    # back onto the main exchange -- that's the entire "delay" mechanism
    channel.queue_declare(
        RETRY_QUEUE,
        durable=True,
        arguments={
            "x-message-ttl": RETRY_DELAY_MS,
            "x-dead-letter-exchange": MAIN_EXCHANGE,
            "x-dead-letter-routing-key": MAIN_QUEUE,
        },
    )
    channel.queue_bind(RETRY_QUEUE, RETRY_EXCHANGE, routing_key=RETRY_QUEUE)

    channel.queue_declare(DEAD_QUEUE, durable=True)
    channel.queue_bind(DEAD_QUEUE, DEAD_EXCHANGE, routing_key=DEAD_QUEUE)


def publish_task(channel, task_name: str, payload: dict, retry_count: int = 0) -> None:
    body = json.dumps({"task": task_name, "payload": payload}).encode()
    channel.basic_publish(
        exchange=MAIN_EXCHANGE,
        routing_key=MAIN_QUEUE,
        body=body,
        properties=pika.BasicProperties(
            delivery_mode=2,  # persistent
            headers={"x-retry-count": retry_count},
        ),
    )


def _requeue_for_retry(channel, body: bytes, retry_count: int) -> None:
    channel.basic_publish(
        exchange=RETRY_EXCHANGE,
        routing_key=RETRY_QUEUE,
        body=body,
        properties=pika.BasicProperties(
            delivery_mode=2,
            headers={"x-retry-count": retry_count},
        ),
    )


def _send_to_dead_letter(channel, body: bytes, error: str) -> None:
    channel.basic_publish(
        exchange=DEAD_EXCHANGE,
        routing_key=DEAD_QUEUE,
        body=body,
        properties=pika.BasicProperties(
            delivery_mode=2,
            headers={"x-last-error": error},
        ),
    )
