"""Entrypoint: `python -m app.main`."""
from __future__ import annotations

import logging
import signal
import threading
import time

import pika.exceptions

from .config import Settings
from .consumer import run

log = logging.getLogger("app.main")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    while not stop.is_set():
        try:
            run(settings, stop)
        except (pika.exceptions.AMQPError, ConnectionError) as exc:
            # Unacked messages are redelivered by the broker, so a reconnect is safe.
            log.error("connection lost: %s; reconnecting in 5s", exc)
            time.sleep(5)
    log.info("stopped")


if __name__ == "__main__":
    main()
