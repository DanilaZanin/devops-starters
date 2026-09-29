import dataclasses
import os
import uuid
from contextlib import suppress
from pathlib import Path

import pytest
import redis

from app.config import Settings


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
    """A unique key prefix per test, so a cold cache never depends on FLUSHALL."""
    base = Settings.from_env()
    return dataclasses.replace(base, key_prefix=f"t{uuid.uuid4().hex[:8]}:")


@pytest.fixture
def sync_redis(settings):
    """A plain synchronous client for assertions and cleanup."""
    client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password or None,
        decode_responses=True,
    )
    yield client
    with suppress(Exception):
        for key in client.scan_iter(match=f"{settings.key_prefix}*"):
            client.delete(key)
    client.close()
