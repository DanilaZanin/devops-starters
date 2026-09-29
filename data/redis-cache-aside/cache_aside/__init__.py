"""
Small cache-aside decorator for async functions (FastAPI route handlers or
any coroutine), backed by Redis. Not trying to be a general-purpose caching
framework — just the pattern I keep rewriting by hand: check Redis, on miss
call the function and store the result, on hit skip the function entirely.
"""
import functools
import hashlib
import inspect
import json
import logging

import redis.asyncio as redis

logger = logging.getLogger("cache_aside")

_client: redis.Redis | None = None
stats = {"hits": 0, "misses": 0}


def configure(redis_url: str) -> None:
    """Call once at app startup. Keeping a module-level client is fine here —
    redis.asyncio.Redis is safe to share across requests, it pools connections
    internally."""
    global _client
    _client = redis.from_url(redis_url, decode_responses=True)


def _make_key(prefix: str, func, args, kwargs) -> str:
    # Includes the function's qualified name so two different cached
    # functions can't collide even if called with the same arguments.
    raw = f"{func.__module__}.{func.__qualname__}:{args}:{sorted(kwargs.items())}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{prefix}:{func.__name__}:{digest}"


def cached(ttl_seconds: int = 60, prefix: str = "cache"):
    """Decorator for async functions. Serializes the return value as JSON,
    so it only works for JSON-serializable results (dicts, lists, primitives)
    — which covers the overwhelming majority of API handler return values.

    Transparent to the caller: the wrapped function's return value is
    unchanged, cache hit/miss is only observable via `cache_aside.stats`
    or the log line, so it's safe to drop straight onto a FastAPI route.
    """

    def decorator(func):
        if not inspect.iscoroutinefunction(func):
            raise TypeError(f"@cached only supports async functions, got {func!r}")

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            if _client is None:
                raise RuntimeError("cache_aside.configure(redis_url) was never called")

            key = _make_key(prefix, func, args, kwargs)
            cached_value = await _client.get(key)
            if cached_value is not None:
                stats["hits"] += 1
                logger.info("cache HIT  %s", key)
                return json.loads(cached_value)

            stats["misses"] += 1
            logger.info("cache MISS %s", key)
            result = await func(*args, **kwargs)
            await _client.set(key, json.dumps(result), ex=ttl_seconds)
            return result

        return wrapper

    return decorator
