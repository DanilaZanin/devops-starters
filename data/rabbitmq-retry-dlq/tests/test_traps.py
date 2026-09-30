"""Trap tests. Each trap is run against the broken variant (traps/broken_consumer.py)
and the fixed one (app/consumer.py). The broken variant MUST show the failure;
if it ever passes, the test fails, so the tests cannot go green by accident.

Needs a running broker: `make test` starts one.
"""
import json
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

import pika
import pika.exceptions
import pytest

from app import consumer as fixed
from app.messaging import PublishFailed, open_publisher_channel, publish_confirmed
from app.topology import declare_topology, queue_arguments, retry_arguments
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

    def __init__(self, module, settings, handler, expect_crash=False):
        self.module, self.settings, self.handler = module, settings, handler
        self.expect_crash = expect_crash
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
        if self.error and exc_type is None and not self.expect_crash:
            raise self.error


def publish_raw(channel, settings, *bodies: bytes) -> None:
    """Publish in order on ONE channel: order across channels is not guaranteed."""
    for body in bodies:
        channel.basic_publish(settings.main_exchange, settings.main_queue, body)


# ------------------------------------------------- trap 1: poison message

POISON = b"{this is not json"


@dataclass
class PoisonOutcome:
    handled: list
    poison_deliveries: int
    dlq: int
    main: int

    @property
    def healthy(self) -> bool:
        return self.handled == ["good-1"] and self.poison_deliveries == 1 and self.dlq == 1 and self.main == 0


def spy_on_decoding(monkeypatch, module, seen: list) -> None:
    """Record every body the consumer tries to decode, so a test can count deliveries."""
    if module is broken:
        real = json.loads
        monkeypatch.setattr(broken, "json", SimpleNamespace(loads=lambda body: (seen.append(body), real(body))[1]))
    else:
        real = fixed.decode_message
        monkeypatch.setattr(fixed, "decode_message", lambda body: (seen.append(body), real(body))[1])


def run_poison_scenario(module, settings, probe, monkeypatch) -> PoisonOutcome:
    """A poison message sits at the head of the queue with a good message behind it."""
    handled, seen = [], []
    spy_on_decoding(monkeypatch, module, seen)

    def handler(message, attempt):
        handled.append(message["order_id"])

    channel = probe.channel()
    declare_topology(channel, settings)
    publish_raw(channel, settings, POISON, json.dumps({"order_id": "good-1"}).encode())

    with RunningConsumer(module, settings, handler):
        wait_until(lambda: "good-1" in handled, timeout=4)
        time.sleep(0.3)  # let the consumer finish the ack it is in the middle of

    return PoisonOutcome(
        handled,
        seen.count(POISON),
        depth(probe, settings.dead_queue) or 0,
        depth(probe, settings.main_queue) or 0,
    )


def test_broken_consumer_loops_on_poison_message(settings, probe, monkeypatch):
    outcome = run_poison_scenario(broken, settings, probe, monkeypatch)
    assert outcome.poison_deliveries >= 3, f"the poison message must be redelivered again and again: {outcome}"
    assert outcome.handled == [], f"the good message must stay blocked behind it: {outcome}"
    assert outcome.dlq == 0, "the broken consumer never dead-letters anything"
    assert outcome.main == 2, "both messages are still waiting in the main queue"


def test_fixed_consumer_sends_poison_message_to_dlq(settings, probe, monkeypatch):
    outcome = run_poison_scenario(fixed, settings, probe, monkeypatch)
    assert outcome.healthy, outcome

    channel = probe.channel()
    _, properties, body = channel.basic_get(settings.dead_queue, auto_ack=True)
    assert body == POISON
    assert "invalid JSON" in properties.headers["x-last-error"]


# ------------------------- trap 1b: poison metadata (bad x-retry-count header)

def run_bad_header_scenario(module, settings, probe, header, restarts, expect_crash):
    """A well-formed order whose x-retry-count header is garbage, then a good order.
    `restarts` consumer runs in a row imitate `restart: unless-stopped`."""
    handled = []

    def handler(message, attempt):
        handled.append(message["order_id"])

    channel = probe.channel()
    declare_topology(channel, settings)
    channel.basic_publish(
        settings.main_exchange,
        settings.main_queue,
        json.dumps({"order_id": "bad-header"}).encode(),
        pika.BasicProperties(headers={"x-retry-count": header}),
    )
    channel.basic_publish(settings.main_exchange, settings.main_queue, json.dumps({"order_id": "good-1"}).encode())

    errors = []
    for _ in range(restarts):
        with RunningConsumer(module, settings, handler, expect_crash=expect_crash) as running:
            wait_until(lambda: "good-1" in handled or not running.thread.is_alive(), timeout=4)
            time.sleep(0.3)
        errors.append(running.error)
    return handled, errors, depth(probe, settings.dead_queue) or 0, depth(probe, settings.main_queue) or 0


def test_broken_consumer_crash_loops_on_bad_retry_header(settings, probe):
    handled, errors, dlq, main = run_bad_header_scenario(broken, settings, probe, "bad", restarts=3, expect_crash=True)
    assert all(isinstance(e, ValueError) for e in errors), f"every restart must crash: {errors}"
    assert handled == [], "the good message never gets processed"
    assert (dlq, main) == (0, 2), "both messages come back after every crash"


@pytest.mark.parametrize("header", ["bad", -1, Decimal("1.5")])
def test_fixed_consumer_dead_letters_bad_retry_header(settings, probe, header):
    handled, errors, dlq, main = run_bad_header_scenario(fixed, settings, probe, header, restarts=1, expect_crash=False)
    assert errors == [None], "the consumer must survive garbage metadata"
    assert handled == ["good-1"]
    assert (dlq, main) == (1, 0)
    _, properties, _ = probe.channel().basic_get(settings.dead_queue, auto_ack=True)
    assert "x-retry-count" in properties.headers["x-last-error"]


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


# ---------- trap 3: the broker-internal TTL -> main hop (dead-letter safety)

@dataclass
class RefusedHopOutcome:
    fillers: int  # messages the destination took before it nacked a publish (it refuses from then on)
    refused_after_ttl: bool  # it still nacked once the message's TTL had fired
    delivered_after_recovery: bool


def refuses(publisher, settings) -> bool:
    try:
        publish_confirmed(publisher, settings.main_exchange, settings.main_queue, b'{"order_id": "probe"}')
    except PublishFailed:
        return True  # nack from x-overflow=reject-publish
    return False


def run_refused_destination_scenario(settings, probe, retry_type, main_type="quorum", outage="full") -> RefusedHopOutcome:
    """A message's TTL fires in the retry queue while the main queue cannot take it. Did the
    message survive?

    outage="full":   the main queue is full (x-max-length=1, x-overflow=reject-publish). The
                     test fills it until the broker nacks a publish (quorum queues accept a
                     message or two over the limit) and checks again after the TTL. Only then
                     are the fillers consumed.
    outage="absent": there is no main queue (deleted in a deploy), so the dead-letter publish
                     cannot be routed. The probe publish comes back unroutable, before and
                     after the TTL. The queue is declared afterwards.

    Either way `refused_after_ttl` proves the destination was refusing when the TTL fired;
    the classic retry queue (at-most-once) counts a refused hop as delivered."""
    channel = probe.channel()
    for exchange in (settings.main_exchange, settings.retry_exchange):
        channel.exchange_declare(exchange, exchange_type="direct", durable=True)

    def declare_main():
        limits = {"x-max-length": 1, "x-overflow": "reject-publish"} if outage == "full" else {}
        channel.queue_declare(settings.main_queue, durable=True, arguments={**queue_arguments(main_type), **limits})
        channel.queue_bind(settings.main_queue, settings.main_exchange, routing_key=settings.main_queue)

    if outage == "full":
        declare_main()
    channel.queue_declare(settings.retry_queue, durable=True, arguments=retry_arguments(settings, retry_type))
    channel.queue_bind(settings.retry_queue, settings.retry_exchange, routing_key=settings.retry_queue)

    publisher = open_publisher_channel(probe)
    fillers = 0
    while not refuses(publisher, settings):  # a probe that got in becomes a filler
        fillers += 1
        assert fillers < 20, "the destination never started refusing"
    publish_confirmed(publisher, settings.retry_exchange, settings.retry_queue, b'{"order_id": "in-flight"}')
    time.sleep(settings.retry_delay_ms / 1000 + 1.5)  # the TTL fires while main refuses
    refused_after = refuses(publisher, settings)
    if outage == "absent":
        declare_main()

    arrived = False

    def drain_and_look() -> bool:
        """Consume the fillers; report whether the in-flight message has shown up."""
        nonlocal arrived
        while True:
            method, _, body = channel.basic_get(settings.main_queue, auto_ack=False)
            if method is None:
                return arrived
            if b"in-flight" in body:
                arrived = True
                channel.basic_nack(method.delivery_tag, requeue=True)
                return True
            channel.basic_ack(method.delivery_tag)

    return RefusedHopOutcome(fillers, refused_after, wait_until(drain_and_look, timeout=15, interval=0.5))


def test_classic_retry_queue_drops_message_when_destination_refuses(settings, probe):
    outcome = run_refused_destination_scenario(settings, probe, "classic", outage="absent")
    assert outcome.refused_after_ttl, outcome
    assert not outcome.delivered_after_recovery, "at-most-once must have dropped it"


def test_quorum_retry_queue_keeps_message_when_destination_refuses(settings, probe):
    outcome = run_refused_destination_scenario(settings, probe, "quorum")
    assert outcome.refused_after_ttl, outcome
    assert outcome.delivered_after_recovery, "at-least-once must retry until the destination takes it"


def test_quorum_retry_queue_keeps_message_when_destination_is_missing(settings, probe):
    outcome = run_refused_destination_scenario(settings, probe, "quorum", outage="absent")
    assert outcome.refused_after_ttl, outcome
    assert outcome.delivered_after_recovery, "at-least-once retries an unroutable hop too"


def test_quorum_retry_queue_delivers_to_a_classic_destination(settings, probe):
    """RabbitMQ requires a quorum SOURCE queue for at-least-once; the destination may be classic."""
    outcome = run_refused_destination_scenario(settings, probe, "quorum", main_type="classic")
    assert outcome.refused_after_ttl, outcome
    assert outcome.delivered_after_recovery


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
