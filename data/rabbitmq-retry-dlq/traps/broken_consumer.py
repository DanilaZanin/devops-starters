"""The consumer as it is usually written first. Do not use this; it exists so the
tests can show what goes wrong. Same `run` signature as app.consumer.run.

Two production traps live here:

1. Poison message. json.loads() raises on bad input, the catch-all handler does
   basic_nack(requeue=True), and the broker hands the same message straight back.
   With prefetch 1 it sits at the head of the queue forever and everything behind
   it starves.

2. Republish + ack without publisher confirms. The retry copy is published on a
   channel that is not in confirm mode and without mandatory=True. If the broker
   cannot route or accept it, nobody is told, and the ack that follows deletes
   the only remaining copy of the message.
"""
from __future__ import annotations

import json
import threading
from contextlib import suppress

import pika

from app.config import Settings
from app.handlers import process_order
from app.messaging import connect
from app.topology import declare_topology


def _handle(channel, method, properties, body, settings: Settings, handler) -> None:
    attempt = int((properties.headers or {}).get("x-retry-count", 0))
    try:
        message = json.loads(body)  # trap 1: raises on a poison message
    except ValueError:
        channel.basic_nack(method.delivery_tag, requeue=True)  # trap 1: instant redelivery, forever
        return

    try:
        handler(message, attempt)
    except Exception:  # noqa: BLE001
        if attempt < settings.max_retries:
            # trap 2: no confirm mode, no mandatory flag, then ack
            channel.basic_publish(
                settings.retry_exchange,
                settings.retry_queue,
                body,
                properties=pika.BasicProperties(delivery_mode=2, headers={"x-retry-count": attempt + 1}),
            )
        else:
            channel.basic_publish(settings.dead_exchange, settings.dead_queue, body)
    channel.basic_ack(method.delivery_tag)


def run(settings: Settings, stop: threading.Event, handler=process_order) -> None:
    connection = connect(settings)
    try:
        channel = connection.channel()  # note: never calls confirm_delivery()
        declare_topology(channel, settings)
        channel.basic_qos(prefetch_count=1)
        for method, properties, body in channel.consume(settings.main_queue, inactivity_timeout=0.2):
            if method is None:
                if stop.is_set():
                    break
                continue
            _handle(channel, method, properties, body, settings, handler)
            if stop.is_set():
                break
        channel.cancel()
    finally:
        with suppress(Exception):
            connection.close()
