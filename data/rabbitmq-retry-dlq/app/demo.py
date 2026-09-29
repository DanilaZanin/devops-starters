"""Publish one message of each kind: `python -m app.demo` (or `make demo`)."""
from __future__ import annotations

import json

from .config import Settings
from .messaging import connect, open_publisher_channel, publish_confirmed
from .topology import declare_topology

SAMPLES = [
    ("ok", json.dumps({"order_id": "order-1"}).encode()),
    ("flaky (fails twice, then succeeds)", json.dumps({"order_id": "order-2", "simulate_failures": 2}).encode()),
    ("never succeeds (ends in the DLQ after the last retry)", json.dumps({"order_id": "order-3", "simulate_failures": 99}).encode()),
    ("poison (not JSON, goes to the DLQ at once)", b"{this is not json"),
]


def main() -> None:
    settings = Settings.from_env()
    connection = connect(settings)
    try:
        declare_topology(connection.channel(), settings)
        channel = open_publisher_channel(connection)
        for label, body in SAMPLES:
            publish_confirmed(channel, settings.main_exchange, settings.main_queue, body)
            print(f"published: {label}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
