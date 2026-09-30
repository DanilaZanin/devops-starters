"""Settings. Everything comes from the environment (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0
    key_prefix: str = "shop:"
    ttl_seconds: int = 30
    # A loader may hold the per-key lock for at most this long. If the process
    # holding it dies, the lock expires by itself and someone else takes over.
    # A loader that runs longer loses the lock and its result is not cached.
    lock_ttl_ms: int = 5000
    # How long requests that lost the lock wait for the winner. Keep it above
    # lock_ttl_ms, so a dead holder's lock expires while the waiters still poll
    # and one of them takes over. After that, waiters load the value themselves
    # (merged into one call per key per process).
    lock_wait_s: float = 6.0
    poll_interval_s: float = 0.02
    # Bounds every Redis call, so a hung Redis costs a request at most this long.
    socket_timeout_s: float = 0.25
    source_latency_s: float = 0.5

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            redis_host=os.environ.get("REDIS_HOST", cls.redis_host),
            redis_port=int(os.environ.get("REDIS_PORT", cls.redis_port)),
            redis_password=os.environ.get("REDIS_PASSWORD", cls.redis_password),
            ttl_seconds=int(os.environ.get("CACHE_TTL_SECONDS", cls.ttl_seconds)),
            lock_ttl_ms=int(os.environ.get("LOCK_TTL_MS", cls.lock_ttl_ms)),
            lock_wait_s=float(os.environ.get("LOCK_WAIT_S", cls.lock_wait_s)),
            source_latency_s=float(os.environ.get("SOURCE_LATENCY_S", cls.source_latency_s)),
        )
