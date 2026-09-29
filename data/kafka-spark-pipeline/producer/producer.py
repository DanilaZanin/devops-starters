import json
import os
import random
import signal
import sys
import time
import uuid
from datetime import datetime, timezone

from confluent_kafka import Producer

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")
TOPIC = os.environ.get("TOPIC", "orders")
RATE = float(os.environ.get("EVENTS_PER_SEC", "5"))
ALIVE_FILE = "/tmp/alive"  # touched every loop; the container healthcheck reads its mtime

PRODUCTS = [
    ("wireless-mouse", 19.99),
    ("mechanical-keyboard", 89.50),
    ("usb-c-hub", 34.00),
    ("laptop-stand", 45.90),
    ("webcam-1080p", 59.99),
    ("noise-cancelling-headset", 129.00),
]

running = True
delivered = 0
failed = 0


def stop(signum, frame):
    global running
    running = False


def on_delivery(err, msg):
    """Called from poll()/flush() once the broker has answered for a message."""
    global delivered, failed
    if err is not None:
        failed += 1
        print(f"delivery failed: {err}", file=sys.stderr, flush=True)
    else:
        delivered += 1
        if delivered % 50 == 0:
            print(f"delivered {delivered} events", flush=True)


def make_event():
    product, base_price = random.choice(PRODUCTS)
    return {
        "order_id": str(uuid.uuid4()),
        "product": product,
        # a bit of price jitter so revenue isn't a flat multiple
        "price": round(base_price * random.uniform(0.95, 1.05), 2),
        "quantity": random.randint(1, 4),
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    producer = Producer({
        "bootstrap.servers": BOOTSTRAP,
        "client.id": "orders-producer",
        # acks=all: the leader answers only after every in-sync replica has the write.
        # Idempotence adds retries without duplicates or reordering (and forces acks=all).
        "acks": "all",
        "enable.idempotence": True,
        "linger.ms": 20,
        "delivery.timeout.ms": 30000,
    })

    print(f"producing to {TOPIC} @ ~{RATE}/s", flush=True)
    while running:
        event = make_event()
        try:
            producer.produce(TOPIC, key=event["order_id"], value=json.dumps(event), on_delivery=on_delivery)
        except BufferError:
            producer.poll(1)  # local queue full: let delivery callbacks drain it first
            continue
        producer.poll(0)
        with open(ALIVE_FILE, "a"):
            os.utime(ALIVE_FILE)
        time.sleep(1.0 / RATE)

    # Graceful shutdown: without flush(), events still sitting in librdkafka's
    # local queue are dropped when the process exits.
    print("stopping, flushing in-flight events", flush=True)
    still_queued = producer.flush(20)
    print(f"delivered={delivered} failed={failed} not_delivered={still_queued}", flush=True)
    return 1 if (failed or still_queued) else 0


if __name__ == "__main__":
    sys.exit(main())
