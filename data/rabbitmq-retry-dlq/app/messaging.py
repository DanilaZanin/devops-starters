"""Connection and publishing helpers shared by the consumer and the demo producer."""
from __future__ import annotations

import logging
import time

import pika
import pika.exceptions

from .config import Settings

log = logging.getLogger("app.messaging")


class PublishFailed(Exception):
    """The broker did not confirm the message, or could not route it to a queue."""


def connect(settings: Settings, attempts: int = 10, delay_s: float = 2.0) -> pika.BlockingConnection:
    """Open a connection, retrying while the broker is still starting.

    `rabbitmq-diagnostics ping` (and sometimes even a healthy container) can
    report ready a moment before the AMQP listener accepts connections, so
    depends_on alone is not a guarantee.
    """
    params = pika.ConnectionParameters(
        host=settings.host,
        port=settings.port,
        virtual_host=settings.vhost,
        credentials=pika.PlainCredentials(settings.user, settings.password),
        heartbeat=30,
        blocked_connection_timeout=60,
    )
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return pika.BlockingConnection(params)
        except pika.exceptions.AMQPConnectionError as exc:
            last_error = exc
            log.warning("broker not ready (attempt %d/%d): %s", attempt, attempts, exc)
            time.sleep(delay_s)
    raise ConnectionError(f"could not connect to RabbitMQ after {attempts} attempts") from last_error


def open_publisher_channel(connection: pika.BlockingConnection):
    """A channel in confirm mode: basic_publish blocks until the broker acks or nacks."""
    channel = connection.channel()
    channel.confirm_delivery()
    return channel


def publish_confirmed(channel, exchange: str, routing_key: str, body: bytes, headers: dict | None = None) -> None:
    """Publish a persistent message and raise PublishFailed unless the broker took it.

    Two things are needed together:
    - confirm mode (see open_publisher_channel) so a broker nack surfaces as an error;
    - mandatory=True, because a message that matches no queue is *acked* by the
      broker and silently discarded unless it is returned to the publisher.
    """
    try:
        channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=body,
            properties=pika.BasicProperties(
                delivery_mode=pika.DeliveryMode.Persistent,
                content_type="application/json",
                headers=headers or {},
            ),
            mandatory=True,
        )
    except (pika.exceptions.UnroutableError, pika.exceptions.NackError) as exc:
        raise PublishFailed(f"{exchange}/{routing_key}: {exc!r}") from exc
