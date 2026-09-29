# FastAPI + Redis cache-aside without the stampede: single-flight lock, fail-open when Redis is down (redis-py asyncio)

**Level: verified.** The trap tests run in CI on every PR that touches this folder, and weekly.

An example application, not a library: a FastAPI service that caches a slow lookup in Redis. Copy the pieces you need.

## Problem

Textbook cache-aside is "GET, on miss call the source, SET". On a cold or just-expired hot key, every request that arrives before the first SET also misses, and every one of them calls the source. 50 concurrent requests are 50 database queries for one value, right when the source is least able to take them.

The second symptom shows up on the day Redis restarts or stalls: a `ConnectionError` or timeout from the cache call propagates out of the handler, and every endpoint that uses the cache returns 500, even though the database is healthy.

## Quick start

```bash
make test    # starts Redis 8, then runs the trap tests through uv
make demo    # starts Redis and the app, fires 50 parallel requests at a cold key
make reset   # removes containers
```

Expected `make test` result: `13 passed`. Expected `make demo` output has exactly one `miss`; the other 49 requests are `coalesced` (they waited for that load) or `hit` (they arrived after it finished), and the split varies from run to run:

```
      1 x-cache: miss
     <n> x-cache: coalesced
     <m> x-cache: hit
```

The app listens on http://127.0.0.1:8000. `GET /products/{id}` is cached, `DELETE /products/{id}/cache` invalidates, and the `X-Cache` response header says how the request was served (`hit`, `miss`, `coalesced`, `bypass`).

Requirements: docker with compose v2, [uv](https://docs.astral.sh/uv/), make. `make check-prereqs` verifies them.

| Verified on | RAM | First run (cold image cache) |
|---|---|---|
| 2026-09-29, macOS arm64, colima 4 CPU / 8 GB, Redis 8.10.2, `make test`: 13 passed (not yet run on an ubuntu-24.04 runner) | Redis about 5 MiB, app container about 45 MiB (`make demo`, `docker stats`) | about 30 s including the image pull; about 6 s with the image cached |

## Traps this avoids

1. **Cache stampede** (reproduced in tests). Cold key, 50 parallel requests: the broken cache calls the source 50 times, the real one once. One request takes a lock (`SET key:lock token NX PX 5000`), loads and stores the value; the others poll Redis and read the result.
2. **Redis down means 500** (reproduced in tests). Any Redis error (refused connection, timeout, auth error) is treated as a miss: the request is served from the source with `X-Cache: bypass`. Every Redis call has a 250 ms socket timeout. A request stops using Redis after its first failed call (only the lock release can follow), so a hung Redis costs a request about 250 ms, at most about 500 ms, instead of an unbounded wait. Concurrent bypass requests for one key share a single source call per process. redis-py 6 and later retries failed calls three times with backoff by default; the client here disables that (`Retry(NoBackoff(), 0)`), otherwise a hung Redis cost about 6 s per request in the real test run.
3. **Leaked, expired or foreign lock** (reproduced in tests). The lock has a lease (`LOCK_TTL_MS`, default 5000), so a crashed loader cannot block the key forever. Waiters poll for `LOCK_WAIT_S` (default 6), longer than the lease: when a dead holder's lock expires they are still there and exactly one takes over. The result is cached, and the lock released, by one Lua script that checks the lock token first, so a loader that outlived its lease cannot overwrite the value the new owner cached. A loader that raises releases the lock too. If you set the wait below the lease, waiters that give up share one fallback call per key per process instead of each calling the source.
4. **Unstable cache keys.** Keys are a SHA-256 of canonical JSON of the arguments. Python's `hash()` is salted per process, so it would give every replica and every restart different keys.
5. **Open, unauthenticated Redis.** Redis 8 runs with a password from `.env`, as the `redis` user, on 127.0.0.1, with `maxmemory` and an LRU policy so it behaves as a cache.

## What the test proves / does NOT prove

The tests run a broken cache (`traps/broken_cache.py`) and the real one (`app/cache.py`) through the same FastAPI app against a real Redis, and require the broken one to fail. If the broken variant ever passes, the suite fails.

Proves:
- 50 concurrent requests for a cold key: the test holds every source call until all 50 requests have missed, so the broken cache makes exactly 50 source calls and the real one exactly 1, and all callers get the same value;
- a lock holder that died costs one source call, a 2.5 s source (longer than the old 2 s wait) is loaded once for 50 requests, and a wait budget shorter than the lease still yields one fallback call instead of 50;
- a loader that outlives its lease finishes after the new owner cached a fresh value and does not overwrite it;
- with nothing listening on the Redis port, broken returns 500 and real returns 200 from the source;
- with a Redis that accepts connections and never answers, real still returns 200 within 2 seconds;
- a second request is a hit, invalidation forces a reload, and a failing source does not leave the key locked.

Does NOT prove:
- Behavior of a Redis that is slow but not dead, or a partial outage where reads work and writes fail.
- A race between invalidation and a load that is already in flight: that load can write the old value back after `DELETE`. Versioned keys or a short TTL are the usual answers.
- Correctness across many app replicas. The lock is a single-Redis lock, which is enough for single-flight (a rare duplicate load is harmless) but is not a mutual-exclusion guarantee. A load that runs longer than `LOCK_TTL_MS` is not cached, and another request may start a second load for the same key; size the lease above your slowest normal load.
- Stampede protection across processes on the fail-open path: while Redis is down, each app process makes one source call per key at a time (requests inside a process are merged), so N replicas make up to N. That is the trade.
- Performance under real load. The source is a `sleep`.

## Local demo vs production

- One Redis node, no persistence (`--save ""`), password in a local `.env`. Production needs TLS, a managed or replicated Redis, and a secrets manager.
- Add jitter to TTLs so keys that were loaded together do not all expire together, and consider serving stale data while one request refreshes (stale-while-revalidate) for the hottest keys.
- Put a circuit breaker in front of Redis if timeouts are frequent: each failing call still costs up to 250 ms (a request pays at most two).
- Export hit, miss, coalesced and bypass counts as metrics. A silent 100% `bypass` rate looks healthy from the outside.
- `/health` reports liveness only, on purpose: Redis being down should not take the app out of rotation.

## Copy it into your project

```
app/cache.py    CacheAside (get_or_load, invalidate) and make_key()
app/config.py   settings (`LOCK_TTL_MS`, `LOCK_WAIT_S`, ...)
app/main.py     how the cache is wired into FastAPI (lifespan, routes)
```

Replace `app/source.py` with your real data access and pass a loader (`lambda: source.fetch(id)`) to `get_or_load`. Keep `pyproject.toml` (or the pinned `requirements.txt`), the `Dockerfile` and `.env.example`. The whole folder also works on its own: `cp -r data/redis-cache-aside /elsewhere && cd /elsewhere && make test`.

Pins: Redis 8.10.2, redis-py 8.1.0, FastAPI 0.142.0, Python 3.14.7 (`python:3.14.7-slim`).
