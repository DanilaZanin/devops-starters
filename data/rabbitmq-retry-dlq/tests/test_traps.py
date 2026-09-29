"""Trap tests. Each trap is run against the broken variant (traps/broken_consumer.py)
and the fixed one (app/consumer.py). The broken variant MUST show the failure;
if it ever passes, the test fails, so the tests cannot go green by accident.

Needs a running broker: `make test` starts one.
"""
import json
import threading
import time
from dataclasses import dataclass

import pika
import pika.exceptions
import pytest

from app import consumer as fixed
from app.messaging import PublishFailed, open_publisher_channel, publish_confirmed
from app.topology import declare_topology
from traps import broken_consumer as broken

# ---------------------------------------------------------------- helpers

def wait_until(predicate, timeout: float, interval: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def depth(probe, queue: str):
    """Messages ready in `queue`, or None if the queue does not exist."""
    channel = probe.channel()
    try:
        return channel.queue_declare(queue, passive=True).method.message_count
    except pika.exceptions.ChannelClosedByBroker:
        return None


class RunningConsumer:
    """Runs a consumer module's `run()` in a thread and stops it on exit."""

    def __init__(self, module, settings, handler):
        self.module, self.settings, self.handler = module, settings, handler
        self.stop = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self._target, daemon=True)

    def _target(self):
        try:
            self.module.run(self.settings, self.stop, self.handler)
        except BaseException as exc:  # noqa: BLE001 - reported from __exit__
            self.error = exc

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop.set()
        self.thread.join(timeout=10)
        assert not self.thread.is_alive(), "consumer did not stop"
        if self.error and exc_type is None:
            raise self.error


def publish_raw(channel, settings, *bodies: bytes) -> None:
    """Publish in order on ONE channel: order across channels is not guaranteed."""
    for body in bodies:
        channel.basic_publish(settings.main_exchange, settings.main_queue, body)


# ------------------------------------------------- trap 1: poison message

@dataclass
class PoisonOutcome:
    handled: list
    dlq: int
    main: int

    @property
    def healthy(self) -> bool:
        return self.handled == ["good-1"] and self.dlq == 1 and self.main == 0


def run_poison_scenario(module, settings, probe) -> PoisonOutcome:
    """A poison message sits at the head of the queue with a good message behind it."""
    handled = []

    def handler(message, attempt):
        handled.append(message["order_id"])

    channel = probe.channel()
    declare_topology(channel, settings)
    publish_raw(channel, settings, b"{this is not json", json.dumps({"order_id": "good-1"}).encode())

    with RunningConsumer(module, settings, handler):
        wait_until(lambda: "good-1" in handled, timeout=4)
        time.sleep(0.3)  # let the consumer finish the ack it is in the middle of

    return PoisonOutcome(handled, depth(probe, settings.dead_queue) or 0, depth(probe, settings.main_queue) or 0)


def test_broken_consumer_loops_on_poison_message(settings, probe):
    outcome = run_poison_scenario(broken, settings, probe)
    assert not outcome.healthy
    assert outcome.dlq == 0, "the broken consumer never dead-letters anything"


def test_fixed_consumer_sends_poison_message_to_dlq(settings, probe):
    outcome = run_poison_scenario(fixed, settings, probe)
    assert outcome.healthy, outcome

    channel = probe.channel()
    _, properties, body = channel.basic_get(settings.dead_queue, auto_ack=True)
    assert body == b"{this is not json"
    assert "invalid JSON" in properties.headers["x-last-error"]


# ------------------------------ trap 2: republish + ack without confirms

@dataclass
class RetryLossOutcome:
    calls: int
    main: int
    dead: int

    @property
    def message_preserved(self) -> bool:
        return self.main + self.dead >= 1


def run_lost_retry_scenario(module, settings, probe) -> RetryLossOutcome:
    """The retry queue disappears (deleted by hand, renamed in a deploy, wiped by a
    policy) while the consumer is running. The next retry publish cannot be routed."""
    calls = []

    def handler(message, attempt):
        calls.append(attempt)
        raise RuntimeError("boom")

    with RunningConsumer(module, settings, handler):
        assert wait_until(lambda: depth(probe, settings.retry_queue) is not None, timeout=5)
        probe.channel().queue_delete(settings.retry_queue)
        publish_raw(probe.channel(), settings, json.dumps({"order_id": "order-1"}).encode())
        assert wait_until(lambda: len(calls) >= 1, timeout=5)
        time.sleep(1.0)  # give the consumer time to republish (and ack, if it is the broken one)

    # after the consumer is gone, an unacked message is back in the queue
    wait_until(lambda: (depth(probe, settings.main_queue) or 0) >= 1, timeout=3)
    return RetryLossOutcome(len(calls), depth(probe, settings.main_queue) or 0, depth(probe, settings.dead_queue) or 0)


def test_broken_consumer_loses_message_when_retry_publish_fails(settings, probe):
    outcome = run_lost_retry_scenario(broken, settings, probe)
    assert outcome.calls == 1
    assert not outcome.message_preserved, "the broken consumer acked a message it never re-queued"


def test_fixed_consumer_keeps_message_when_retry_publish_fails(settings, probe):
    outcome = run_lost_retry_scenario(fixed, settings, probe)
    assert outcome.message_preserved, outcome


def test_publish_confirmed_rejects_unroutable_message(settings, probe):
    declare_topology(probe.channel(), settings)
    channel = open_publisher_channel(probe)
    with pytest.raises(PublishFailed):
        publish_confirmed(channel, settings.main_exchange, "no-such-routing-key", b"{}")


# ---------------------------------------------------- retry policy (fixed)

def test_message_is_retried_exactly_max_retries_times_then_dead_lettered(settings, probe):
    calls = []

    def handler(message, attempt):
        calls.append(attempt)
        raise RuntimeError("boom")

    channel = probe.channel()
    declare_topology(channel, settings)
    body = json.dumps({"order_id": "order-1"}).encode()
    publish_raw(channel, settings, body)

    with RunningConsumer(fixed, settings, handler):
        assert wait_until(lambda: depth(probe, settings.dead_queue) == 1, timeout=15)

    # 1 first attempt + max_retries retries, each seeing the retry counter it was sent with
    assert calls == list(range(settings.max_retries + 1))
    _, properties, dead_body = probe.channel().basic_get(settings.dead_queue, auto_ack=True)
    assert dead_body == body
    assert properties.headers["x-retry-count"] == settings.max_retries
    assert "boom" in properties.headers["x-last-error"]
    assert depth(probe, settings.retry_queue) == 0
    assert depth(probe, settings.main_queue) == 0


def test_message_that_recovers_is_not_dead_lettered(settings, probe):
    calls = []

    def handler(message, attempt):
        calls.append(attempt)
        if attempt < 2:
            raise RuntimeError("transient")

    channel = probe.channel()
    declare_topology(channel, settings)
    publish_raw(channel, settings, json.dumps({"order_id": "order-1"}).encode())

    with RunningConsumer(fixed, settings, handler):
        assert wait_until(lambda: len(calls) >= 3, timeout=10)
        time.sleep(0.3)

    assert calls == [0, 1, 2]
    assert depth(probe, settings.dead_queue) == 0


# ---------------------------------------------------------------- access

def test_guest_user_is_disabled(settings, probe):
    # `probe` proves the configured user works; guest must not.
    params = pika.ConnectionParameters(
        host=settings.host,
        port=settings.port,
        credentials=pika.PlainCredentials("guest", "guest"),
        connection_attempts=1,
    )
    with pytest.raises(pika.exceptions.AMQPConnectionError):
        pika.BlockingConnection(params)
