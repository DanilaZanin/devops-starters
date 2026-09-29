"""Cache-aside with stampede protection and fail-open reads."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as aioredis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from .config import Settings

log = logging.getLogger("app.cache")

# What "Redis is not usable" looks like from redis-py: refused/reset connections
# (OSError), timeouts, protocol and auth errors.
REDIS_ERRORS = (RedisError, OSError, asyncio.TimeoutError)

# Delete the lock only if it is still ours: after the lock TTL expires, another
# request may own it, and a plain DEL would release theirs.
_RELEASE_LOCK = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""

# Cache the value and release the lock in one atomic step, and only if the lock is
# still ours. A loader that outlived its lease must not overwrite the value that the
# new lock owner cached in the meantime. Returns 1 if stored, 0 if the lease was lost.
_STORE_AND_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  redis.call('set', KEYS[2], ARGV[2], 'EX', ARGV[3])
  redis.call('del', KEYS[1])
  return 1
end
return 0
"""

Loader = Callable[[], Awaitable[Any]]


class CacheUnavailable(Exception):
    """A Redis call failed. Reads treat this as a miss served from the source."""


def make_key(prefix: str, name: str, **params: Any) -> str:
    """Stable across processes and restarts. Python's built-in hash() is salted per
    process for strings, so it would give every replica a different key."""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}{name}:{hashlib.sha256(canonical.encode()).hexdigest()[:16]}"


def make_client(settings: Settings) -> aioredis.Redis:
    return aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password or None,
        socket_timeout=settings.socket_timeout_s,
        socket_connect_timeout=settings.socket_timeout_s,
        # redis-py 6+ retries failed calls 3 times with backoff by default; that would
        # multiply the timeout bound above, and fail-open wants the first failure.
        retry=Retry(NoBackoff(), 0),
        decode_responses=True,
    )


class CacheAside:
    def __init__(self, client: aioredis.Redis, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        # One fallback load per key per process (see _bypass).
        self._inflight: dict[str, asyncio.Future] = {}

    async def get_or_load(self, key: str, loader: Loader) -> tuple[Any, str]:
        """Return (value, status). Status is one of:
        hit        served from Redis
        miss       this request took the lock, loaded the value and cached it
        coalesced  another request loaded it while this one waited
        bypass     Redis was unusable (or the wait timed out): served from the source

        Timing: a request waits at most `lock_wait_s` for the lock holder. Keep that
        above the lock lease (`lock_ttl_ms`): then a dead holder's lock expires while
        the waiters are still polling, and exactly one of them takes over. If the wait
        runs out anyway, the fallback loads of one process are merged into one.
        """
        s = self.settings
        lock_key = f"{key}:lock"
        deadline = time.monotonic() + s.lock_wait_s
        waited = False
        try:
            while True:
                raw = await self._redis(self.client.get(key))
                if raw is not None:
                    return json.loads(raw), "coalesced" if waited else "hit"

                token = uuid.uuid4().hex
                if await self._redis(self.client.set(lock_key, token, nx=True, px=s.lock_ttl_ms)):
                    return await self._load_holding_lock(key, lock_key, token, loader)

                if time.monotonic() >= deadline:
                    log.warning("gave up waiting for %s, loading without the lock", key)
                    break
                waited = True
                await asyncio.sleep(s.poll_interval_s)
        except CacheUnavailable as exc:
            # Fail open: a broken cache must cost latency, not availability.
            log.warning("cache unavailable (%s), serving from the source", exc)
        return await self._bypass(key, loader), "bypass"

    async def _bypass(self, key: str, loader: Loader) -> Any:
        """Load without the lock, but let concurrent bypass requests for one key share
        a single call to the source. Bounds the cost of a dead Redis or a spent wait
        budget to one call per key per process instead of one per request.
        ponytail: per process; across replicas it is still one call each."""
        task = self._inflight.get(key)
        if task is None:
            task = self._inflight[key] = asyncio.ensure_future(loader())
            task.add_done_callback(lambda _: self._inflight.pop(key, None))
        return await asyncio.shield(task)

    async def invalidate(self, key: str) -> None:
        """Drop a cached value. Raises CacheUnavailable if Redis cannot be reached, so
        the caller knows the stale value may live on until its TTL."""
        await self._redis(self.client.delete(key))

    async def _load_holding_lock(self, key: str, lock_key: str, token: str, loader: Loader) -> tuple[Any, str]:
        settled = False  # True once _store_and_release ran: the lock is gone or not ours any more
        try:
            # Someone may have filled the key between our GET and taking the lock.
            raw = await self._redis(self.client.get(key))
            if raw is not None:
                return json.loads(raw), "hit"
            value = await loader()
            settled = True
            await self._store_and_release(key, lock_key, token, value)
            return value, "miss"
        finally:
            if not settled:
                await self._release(lock_key, token)

    async def _store_and_release(self, key: str, lock_key: str, token: str, value: Any) -> None:
        try:
            stored = await self.client.eval(
                _STORE_AND_RELEASE, 2, lock_key, key, token, json.dumps(value), self.settings.ttl_seconds
            )
        except REDIS_ERRORS as exc:
            # The value is already loaded; failing to cache it is not worth an error.
            # The lock expires by itself.
            log.warning("could not cache %s: %s", key, exc)
            return
        if not stored:
            log.warning("lock for %s expired before the load finished, result not cached", key)

    async def _release(self, lock_key: str, token: str) -> None:
        try:
            await self.client.eval(_RELEASE_LOCK, 1, lock_key, token)
        except REDIS_ERRORS as exc:
            log.warning("could not release %s (it expires on its own): %s", lock_key, exc)

    @staticmethod
    async def _redis(call: Awaitable[Any]) -> Any:
        try:
            return await call
        except REDIS_ERRORS as exc:
            raise CacheUnavailable(str(exc)) from exc
