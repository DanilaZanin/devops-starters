import json
import os
import random
import time
import uuid
from datetime import datetime, timezone

from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")
TOPIC = os.environ.get("TOPIC", "orders")
RATE = float(os.environ.get("EVENTS_PER_SEC", "5"))

PRODUCTS = [
    ("wireless-mouse", 19.99),
    ("mechanical-keyboard", 89.50),
    ("usb-c-hub", 34.00),
    ("laptop-stand", 45.90),
    ("webcam-1080p", 59.99),
    ("noise-cancelling-headset", 129.00),
]


def make_event():
    product, base_price = random.choice(PRODUCTS)
    qty = random.randint(1, 4)
    # a bit of price jitter so revenue isn't a flat multiple, like real sales data
    price = round(base_price * random.uniform(0.95, 1.05), 2)
    return {
        "order_id": str(uuid.uuid4()),
        "product": product,
        "price": price,
        "quantity": qty,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def connect_with_retry():
    for attempt in range(30):
        try:
            return KafkaProducer(
                bootstrap_servers=BOOTSTRAP,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
        except NoBrokersAvailable:
            print(f"kafka not ready yet, retrying ({attempt + 1}/30)...", flush=True)
            time.sleep(2)
    raise RuntimeError("could not connect to kafka after 30 retries")


def main():
    producer = connect_with_retry()
    print(f"producing to {TOPIC} @ ~{RATE}/s", flush=True)
    sent = 0
    while True:
        event = make_event()
        producer.send(TOPIC, event)
        sent += 1
        if sent % 50 == 0:
            producer.flush()
            print(f"sent {sent} events so far", flush=True)
        time.sleep(1.0 / RATE)


if __name__ == "__main__":
    main()
