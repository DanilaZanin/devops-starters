"""The consumer: retry through a TTL queue, dead-letter what cannot succeed."""
from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from contextlib import suppress

from .config import Settings
from .handlers import InvalidMessage, decode_message, process_order
from .messaging import PublishFailed, connect, open_publisher_channel, publish_confirmed
from .topology import declare_topology

log = logging.getLogger("app.consumer")

Handler = Callable[[dict, int], None]


def attempt_of(properties) -> int:
    """How many retries this message has already been through (0 on first delivery)."""
    return int((properties.headers or {}).get("x-retry-count", 0))


def handle_delivery(channel, publisher, method, properties, body: bytes, settings: Settings, handler: Handler) -> None:
    attempt = attempt_of(properties)
    target = None  # (exchange, routing_key, headers) when the message has to move on

    try:
        handler(decode_message(body), attempt)
    except InvalidMessage as exc:
        # Poison message: no number of retries can fix it, so do not retry.
        log.error("invalid message, sending to DLQ: %s", exc)
        target = (settings.dead_exchange, settings.dead_queue, {"x-last-error": str(exc), "x-retry-count": attempt})
    except Exception as exc:  # noqa: BLE001 - a handler can raise anything
        if attempt < settings.max_retries:
            log.warning("attempt %d failed (%s), retry %d/%d", attempt + 1, exc, attempt + 1, settings.max_retries)
            target = (
                settings.retry_exchange,
                settings.retry_queue,
                {"x-last-error": str(exc), "x-retry-count": attempt + 1},
            )
        else:
            log.error("out of retries (%d), sending to DLQ: %s", settings.max_retries, exc)
            target = (settings.dead_exchange, settings.dead_queue, {"x-last-error": str(exc), "x-retry-count": attempt})

    if target is None:
        channel.basic_ack(method.delivery_tag)
        return

    exchange, routing_key, headers = target
    try:
        publish_confirmed(publisher, exchange, routing_key, body, headers)
    except PublishFailed as exc:
        # The copy did not reach a queue. Acking now would lose the message, so give
        # the original back to the broker and try again after a short pause.
        log.error("could not move message to %s, putting it back: %s", routing_key, exc)
        channel.basic_nack(method.delivery_tag, requeue=True)
        time.sleep(settings.requeue_pause_s)
        return
    channel.basic_ack(method.delivery_tag)


def _beat(settings: Settings, last: float) -> float:
    now = time.monotonic()
    if settings.heartbeat_file and now - last >= 5:
        with suppress(OSError), open(settings.heartbeat_file, "a"):
            os.utime(settings.heartbeat_file)
        return now
    return last


def run(settings: Settings, stop: threading.Event, handler: Handler = process_order) -> None:
    """Consume until `stop` is set. One message in flight at a time (prefetch 1)."""
    connection = connect(settings)
    try:
        channel = connection.channel()
        publisher = open_publisher_channel(connection)
        declare_topology(channel, settings)
        channel.basic_qos(prefetch_count=1)
        log.info("consuming from %r", settings.main_queue)

        last_beat = 0.0
        # inactivity_timeout makes the generator yield (None, None, None) while idle,
        # which is what lets us notice `stop` and refresh the heartbeat.
        for method, properties, body in channel.consume(settings.main_queue, inactivity_timeout=0.2):
            last_beat = _beat(settings, last_beat)
            if method is None:
                if stop.is_set():
                    break
                continue
            handle_delivery(channel, publisher, method, properties, body, settings, handler)
            if stop.is_set():
                break
        channel.cancel()
    finally:
        with suppress(Exception):
            connection.close()
