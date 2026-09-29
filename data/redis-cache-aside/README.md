# fastapi-redis-cache

A small `@cached` decorator implementing the cache-aside pattern for async
Python (FastAPI route handlers, or any coroutine), backed by Redis — plus a
demo app and a benchmark script that proves it actually works, not just that
it doesn't crash.

## The library

```python
from cache_aside import cached, configure

configure("redis://localhost:6379/0")  # once, at startup

@cached(ttl_seconds=30, prefix="product")
async def fetch_product(product_id: int) -> dict:
    ...  # slow DB call / external API
```

- Cache key = SHA-256 of `module.qualname + args + kwargs`, so two different
  cached functions can never collide even called with identical arguments.
- Transparent to the caller — the wrapped function's return value is
  unchanged. Hit/miss is only observable via `cache_aside.stats` or the log
  line, so it's safe to drop straight onto a route without touching the
  response shape.
- Only supports async functions on purpose — a sync-blocking Redis call
  inside a FastAPI handler defeats the point of an async framework, so the
  decorator raises `TypeError` at import time instead of silently degrading
  performance.

## Structure

```
cache_aside/__init__.py   # the decorator
app/main.py                 # demo FastAPI app: GET /products/{id}, artificially slow
benchmark.py                 # hits the endpoint N times, measures latency + proves it's really cached
docker-compose.yml
Dockerfile
```

## Usage

```bash
docker compose up -d --build
python3 benchmark.py
```

## Verified — real latency numbers, not estimates

`fetch_product()` sleeps 0.5s to stand in for a slow DB call, and randomizes
the returned `price` on every real execution — so identical prices across
calls is itself proof the handler didn't re-run, independent of the timing:

```
$ docker exec cache-demo-redis redis-cli FLUSHALL
OK
$ python3 benchmark.py
GET /products/42 x5

  call 1:   530.5 ms   price=172.43   COLD (cache miss)
  call 2:    25.6 ms   price=172.43   WARM (cache hit)
  call 3:    24.0 ms   price=172.43   WARM (cache hit)
  call 4:    24.3 ms   price=172.43   WARM (cache hit)
  call 5:    43.1 ms   price=172.43   WARM (cache hit)

OK: price was identical on every call, including the first -> once cached, the handler body never re-ran.

cache stats: {'hits': 13, 'misses': 2}
```

~530ms -> ~25-40ms, roughly a 15-20x latency drop on a cache hit, and the
identical `price` across all 5 calls confirms it's not just fast, it's
actually skipping the handler body.

Two real mistakes I made and fixed while building this, left visible rather
than cleaned up:

1. First version of the decorator returned `(result, was_hit)` instead of
   just `result` — which breaks FastAPI, since the route would then return
   a 2-element JSON array instead of the actual payload. Changed to track
   hits/misses in a separate module-level `stats` dict instead of mangling
   the return value.
2. First version of `benchmark.py` assumed "call 1 is always a cache miss,"
   which is wrong if you re-run the benchmark within the TTL window (the key
   from the previous run is still warm). Fixed by comparing `/cache-stats`
   before and after each call and labeling by what actually happened
   server-side.

Stack: FastAPI, `redis.asyncio`, Redis 7, `httpx` for the benchmark client,
tested on Ubuntu 22.04 with Docker Compose.
