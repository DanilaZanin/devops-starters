"""Exchanges and queues. Declaring is idempotent as long as the arguments do not change."""
from __future__ import annotations

from .config import Settings


def queue_arguments(queue_type: str) -> dict:
    return {"x-queue-type": "quorum"} if queue_type == "quorum" else {}


def retry_arguments(settings: Settings, queue_type: str = "quorum") -> dict:
    """Arguments of the TTL retry queue.

    The TTL -> main hop happens inside the broker, where the consumer's publisher
    confirms do not reach. In a classic queue that hop is at-most-once: if the
    destination cannot take the message at that moment (no queue bound, leader down),
    the message is dropped. A quorum queue with x-dead-letter-strategy=at-least-once
    keeps it and retries the hop. That strategy is set on the quorum SOURCE queue (this
    one) together with x-overflow=reject-publish; the destination may be a classic queue.
    The retry interval is the broker's dead_letter_worker_publisher_confirm_timeout
    (180 s by default, see docker-compose.yml).
    """
    quorum = queue_type == "quorum"
    return {
        **queue_arguments(queue_type),
        **({"x-dead-letter-strategy": "at-least-once", "x-overflow": "reject-publish"} if quorum else {}),
        "x-message-ttl": settings.retry_delay_ms,
        "x-dead-letter-exchange": settings.main_exchange,
        "x-dead-letter-routing-key": settings.main_queue,
    }


def declare_topology(channel, settings: Settings, queue_type: str = "quorum") -> None:
    """`queue_type="classic"` exists only so the tests can show what the default protects."""
    type_args = queue_arguments(queue_type)

    for exchange in (settings.main_exchange, settings.retry_exchange, settings.dead_exchange):
        channel.exchange_declare(exchange, exchange_type="direct", durable=True)

    channel.queue_declare(settings.main_queue, durable=True, arguments=type_args)
    channel.queue_bind(settings.main_queue, settings.main_exchange, routing_key=settings.main_queue)

    # The retry queue has no consumers. A message waits here for retry_delay_ms,
    # then RabbitMQ dead-letters it back onto the main exchange. That is the whole
    # "delay" mechanism, no plugin needed.
    channel.queue_declare(settings.retry_queue, durable=True, arguments=retry_arguments(settings, queue_type))
    channel.queue_bind(settings.retry_queue, settings.retry_exchange, routing_key=settings.retry_queue)

    channel.queue_declare(settings.dead_queue, durable=True, arguments=type_args)
    channel.queue_bind(settings.dead_queue, settings.dead_exchange, routing_key=settings.dead_queue)
