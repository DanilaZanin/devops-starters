import json
import logging

from . import (
    MAIN_QUEUE,
    MAX_RETRIES,
    _requeue_for_retry,
    _send_to_dead_letter,
    connect,
    setup_topology,
)

logger = logging.getLogger("taskqueue.worker")

# Task name -> callable(payload: dict) -> None. Raise to signal failure.
_registry: dict = {}


def task(name: str):
    def decorator(func):
        _registry[name] = func
        return func

    return decorator


def _handle_delivery(channel, method, properties, body):
    retry_count = 0
    if properties.headers:
        retry_count = properties.headers.get("x-retry-count", 0)

    message = json.loads(body)
    task_name = message["task"]
    payload = message["payload"]

    handler = _registry.get(task_name)
    if handler is None:
        logger.error("no handler registered for task %r, dropping to dead-letter", task_name)
        _send_to_dead_letter(channel, body, error=f"unknown task: {task_name}")
        channel.basic_ack(method.delivery_tag)
        return

    try:
        handler(payload, retry_count=retry_count)
    except Exception as exc:  # noqa: BLE001 - a task handler can raise anything
        if retry_count < MAX_RETRIES:
            logger.warning(
                "task %r attempt %d failed (%s), scheduling retry %d/%d",
                task_name, retry_count + 1, exc, retry_count + 1, MAX_RETRIES,
            )
            _requeue_for_retry(channel, body, retry_count + 1)
        else:
            logger.error(
                "task %r exhausted %d retries (%s), sending to dead-letter queue",
                task_name, MAX_RETRIES, exc,
            )
            _send_to_dead_letter(channel, body, error=str(exc))
        channel.basic_ack(method.delivery_tag)
    else:
        logger.info("task %r succeeded on attempt %d", task_name, retry_count + 1)
        channel.basic_ack(method.delivery_tag)


def run(url: str) -> None:
    conn = connect(url)
    channel = conn.channel()
    setup_topology(channel)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(MAIN_QUEUE, on_message_callback=_handle_delivery)
    logger.info("worker started, waiting for tasks on %r", MAIN_QUEUE)
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
        conn.close()
