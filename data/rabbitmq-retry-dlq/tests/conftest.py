import dataclasses
import os
import uuid
from contextlib import suppress
from pathlib import Path

import pytest

from app.config import Settings
from app.messaging import connect


def _load_dotenv() -> None:
    """Read ../.env so `uv run pytest` works without exporting anything first."""
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


@pytest.fixture
def settings():
    """Fresh queue names per test, a short retry delay, and cleanup afterwards."""
    base = Settings.from_env()
    fresh = dataclasses.replace(
        base,
        prefix=f"t{uuid.uuid4().hex[:8]}.",
        retry_delay_ms=300,
        max_retries=3,
        requeue_pause_s=0.2,
        heartbeat_file=None,
    )
    yield fresh
    with suppress(Exception):
        connection = connect(fresh, attempts=1)
        channel = connection.channel()
        for queue in (fresh.main_queue, fresh.retry_queue, fresh.dead_queue):
            channel.queue_delete(queue)
        for exchange in (fresh.main_exchange, fresh.retry_exchange, fresh.dead_exchange):
            channel.exchange_delete(exchange)
        connection.close()


@pytest.fixture
def probe(settings):
    """A connection owned by the test thread, for publishing and inspecting queues."""
    connection = connect(settings)
    yield connection
    with suppress(Exception):
        connection.close()
