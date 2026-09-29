"""Exchanges and queues. Declaring is idempotent as long as the arguments do not change."""
from __future__ import annotations

from .config import Settings


def declare_topology(channel, settings: Settings) -> None:
    for exchange in (settings.main_exchange, settings.retry_exchange, settings.dead_exchange):
        channel.exchange_declare(exchange, exchange_type="direct", durable=True)

    channel.queue_declare(settings.main_queue, durable=True)
    channel.queue_bind(settings.main_queue, settings.main_exchange, routing_key=settings.main_queue)

    # The retry queue has no consumers. A message waits here for retry_delay_ms,
    # then RabbitMQ dead-letters it back onto the main exchange. That is the whole
    # "delay" mechanism, no plugin needed.
    channel.queue_declare(
        settings.retry_queue,
        durable=True,
        arguments={
            "x-message-ttl": settings.retry_delay_ms,
            "x-dead-letter-exchange": settings.main_exchange,
            "x-dead-letter-routing-key": settings.main_queue,
        },
    )
    channel.queue_bind(settings.retry_queue, settings.retry_exchange, routing_key=settings.retry_queue)

    channel.queue_declare(settings.dead_queue, durable=True)
    channel.queue_bind(settings.dead_queue, settings.dead_exchange, routing_key=settings.dead_queue)
