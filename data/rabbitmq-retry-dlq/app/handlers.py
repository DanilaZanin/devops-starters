"""Business logic. Replace `process_order` with your own handler.

A handler is `handler(message: dict, attempt: int) -> None`:
- return normally: the message is acked;
- raise InvalidMessage: the message can never succeed, it goes to the DLQ at once;
- raise anything else: the failure is treated as transient and retried.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger("app.handlers")


class InvalidMessage(Exception):
    """Retrying would not help (bad JSON, missing fields)."""


def decode_message(body: bytes) -> dict:
    try:
        message = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidMessage(f"invalid JSON: {exc}") from exc
    if not isinstance(message, dict):
        raise InvalidMessage(f"expected a JSON object, got {type(message).__name__}")
    return message


def process_order(message: dict, attempt: int) -> None:
    order_id = message.get("order_id")
    if not isinstance(order_id, str) or not order_id:
        raise InvalidMessage("order_id is required")

    # Demo switch: fail the first N attempts, then succeed.
    failures = int(message.get("simulate_failures", 0))
    if attempt < failures:
        raise RuntimeError(f"simulated transient failure {attempt + 1}/{failures}")

    log.info("order %s processed on attempt %d", order_id, attempt + 1)
