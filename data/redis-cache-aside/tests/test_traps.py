"""Trap tests. Each trap runs against the broken cache (traps/broken_cache.py) and
the fixed one (app/cache.py). The broken variant MUST show the failure; if it ever
passes, the test fails, so the suite cannot go green by accident.

Needs a running Redis: `make test` starts one.
"""
import asyncio
import dataclasses
import time

import httpx

from app.cache import CacheAside, make_key
from app.main import create_app
from app.source import ProductSource
from traps.broken_cache import BrokenCacheAside

CONCURRENT_REQUESTS = 50


async def call(app, requests):
    """Run `requests(client)` against the app, with lifespan started and app errors
    turned into 500 responses (as a real server would) instead of raised."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await requests(client)


def stampede(cache_cls, settings, source):
    app = create_app(settings, cache_cls, source)

    async def requests(client):
        return await asyncio.gather(*[client.get("/products/1") for _ in range(CONCURRENT_REQUESTS)])

    return asyncio.run(call(app, requests))


# ------------------------------------------------ trap 1: cache stampede

class GatedSource(ProductSource):
    """Holds every fetch until `expected` of them are waiting, so no request can find a
    filled cache before all of them have missed. Removes the timing luck from the test."""

    def __init__(self, expected: int) -> None:
        super().__init__(latency_s=0)
        self.expected, self.entered, self.gate = expected, 0, asyncio.Event()

    async def fetch(self, product_id: int) -> dict:
        self.entered += 1
        if self.entered >= self.expected:
            self.gate.set()
        await asyncio.wait_for(self.gate.wait(), timeout=10)
        return await super().fetch(product_id)


def test_broken_cache_stampedes_on_cold_key(settings, sync_redis):
    source = GatedSource(CONCURRENT_REQUESTS)
    responses = stampede(BrokenCacheAside, settings, source)

    assert all(r.status_code == 200 for r in responses)
    assert source.calls == CONCURRENT_REQUESTS, f"expected a stampede, the source was called {source.calls} times"


def test_fixed_cache_loads_a_cold_key_once(settings, sync_redis):
    source = ProductSource(latency_s=0.3)
    responses = stampede(CacheAside, settings, source)

    assert all(r.status_code == 200 for r in responses)
    assert source.calls == 1, f"the source was called {source.calls} times for one key"
    assert len({r.text for r in responses}) == 1, "every caller must see the same value"
    statuses = [r.headers["X-Cache"] for r in responses]
    assert statuses.count("miss") == 1
    assert set(statuses) <= {"miss", "coalesced", "hit"}
    assert sync_redis.exists(make_key(settings.key_prefix, "product", id=1) + ":lock") == 0, "lock must be released"


# ------------------------------------------ trap 2: Redis down means 500

def redis_down(settings):
    """Nothing listens on port 1: connections are refused, like a stopped Redis."""
    return dataclasses.replace(settings, redis_port=1)


def get_one(cache_cls, settings, source):
    app = create_app(settings, cache_cls, source)

    async def requests(client):
        return await client.get("/products/1")

    return asyncio.run(call(app, requests))


def test_broken_cache_returns_500_when_redis_is_down(settings):
    source = ProductSource(latency_s=0.01)
    response = get_one(BrokenCacheAside, redis_down(settings), source)
    assert response.status_code == 500
    assert source.calls == 0, "the source was never asked, the request died on Redis"


def test_fixed_cache_serves_from_the_source_when_redis_is_down(settings):
    source = ProductSource(latency_s=0.01)
    response = get_one(CacheAside, redis_down(settings), source)
    assert response.status_code == 200
    assert response.headers["X-Cache"] == "bypass"
    assert response.json()["id"] == 1


def test_fixed_cache_still_answers_when_redis_accepts_but_never_replies(settings):
    """A hung Redis is worse than a stopped one: connections succeed, calls never return."""

    async def scenario():
        async def hold_open(reader, writer):
            await reader.read()  # never answers

        server = await asyncio.start_server(hold_open, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        hung = dataclasses.replace(settings, redis_port=port)
        app = create_app(hung, CacheAside, ProductSource(latency_s=0.01))

        async def requests(client):
            started = time.monotonic()
            response = await client.get("/products/1")
            return response, time.monotonic() - started

        try:
            return await call(app, requests)
        finally:
            server.close()

    response, elapsed = asyncio.run(scenario())
    assert response.status_code == 200
    assert response.headers["X-Cache"] == "bypass"
    assert elapsed < 2.0, f"socket timeouts should bound the wait, took {elapsed:.2f}s"


# ------------- lock lifecycle: lease expiry, slow loaders, late writers

def lock_key_of(settings, product_id=1):
    return make_key(settings.key_prefix, "product", id=product_id) + ":lock"


def test_dead_lock_holder_costs_one_source_call(settings, sync_redis):
    """The process that held the lock died. The lease expires, exactly one waiter takes over."""
    settings = dataclasses.replace(settings, lock_ttl_ms=1000)
    sync_redis.set(lock_key_of(settings), "dead-owner", px=settings.lock_ttl_ms)
    source = ProductSource(latency_s=0.05)
    responses = stampede(CacheAside, settings, source)

    assert all(r.status_code == 200 for r in responses)
    assert source.calls == 1, f"{source.calls} source calls after the lock holder died"


def test_giving_up_on_the_lock_still_loads_once_per_process(settings, sync_redis):
    """Wait budget shorter than the lease (a misconfiguration): waiters give up while the
    lock is still held. They must share one fallback load, not send 50 to the source."""
    settings = dataclasses.replace(settings, lock_ttl_ms=3000, lock_wait_s=0.3)
    sync_redis.set(lock_key_of(settings), "slow-or-dead-owner", px=settings.lock_ttl_ms)
    source = ProductSource(latency_s=0.05)
    responses = stampede(CacheAside, settings, source)

    assert all(r.status_code == 200 for r in responses)
    assert source.calls == 1, f"{source.calls} parallel fallback loads"
    assert {r.headers["X-Cache"] for r in responses} == {"bypass"}


def test_source_slower_than_the_old_wait_budget_is_still_loaded_once(settings, sync_redis):
    """2.5 s loads used to outlast the 2 s wait: all 50 waiters gave up and hit the source."""
    source = ProductSource(latency_s=2.5)
    responses = stampede(CacheAside, settings, source)

    assert all(r.status_code == 200 for r in responses)
    assert source.calls == 1, f"{source.calls} source calls for a 2.5 s load"


def test_loader_that_outlives_its_lease_cannot_overwrite_the_new_owners_value(settings, sync_redis):
    """A is slow and loses its lease; B takes over and caches the fresh value; A must not
    write its stale result over it when it finally finishes."""
    settings = dataclasses.replace(settings, lock_ttl_ms=300)

    class SlowThenFast(ProductSource):
        async def fetch(self, product_id):
            self.calls += 1
            if self.calls == 1:
                await asyncio.sleep(1.0)
                return {"version": "stale"}
            return {"version": "fresh"}

    source = SlowThenFast()
    app = create_app(settings, CacheAside, source)

    async def requests(client):
        slow = asyncio.create_task(client.get("/products/1"))
        await asyncio.sleep(0.6)  # A's lease (300 ms) has expired, A is still loading
        fresh = await client.get("/products/1")
        stale = await slow
        after = await client.get("/products/1")
        return fresh, stale, after

    fresh, stale, after = asyncio.run(call(app, requests))

    assert fresh.json() == {"version": "fresh"}
    assert stale.json() == {"version": "stale"}  # A still answers its own caller
    assert after.json() == {"version": "fresh"}, "the late writer clobbered the newer value"
    assert sync_redis.exists(lock_key_of(settings)) == 0


# -------------------------------------------------- normal cache behavior

def test_second_request_is_a_hit_and_invalidate_forces_a_reload(settings, sync_redis):
    source = ProductSource(latency_s=0.01)
    app = create_app(settings, CacheAside, source)

    async def requests(client):
        first = await client.get("/products/7")
        second = await client.get("/products/7")
        dropped = await client.delete("/products/7/cache")
        third = await client.get("/products/7")
        return first, second, dropped, third

    first, second, dropped, third = asyncio.run(call(app, requests))

    assert (first.headers["X-Cache"], second.headers["X-Cache"]) == ("miss", "hit")
    assert first.json() == second.json()
    assert dropped.status_code == 200
    assert third.headers["X-Cache"] == "miss"
    assert source.calls == 2


def test_lock_is_released_when_the_source_fails(settings, sync_redis):
    class FailsOnce(ProductSource):
        async def fetch(self, product_id):
            if self.calls == 0:
                self.calls += 1
                raise RuntimeError("database is down")
            return await super().fetch(product_id)

    app = create_app(settings, CacheAside, FailsOnce(latency_s=0.01))

    async def requests(client):
        failed = await client.get("/products/1")
        started = time.monotonic()
        retried = await client.get("/products/1")
        return failed, retried, time.monotonic() - started

    failed, retried, elapsed = asyncio.run(call(app, requests))

    assert failed.status_code == 500
    assert retried.status_code == 200
    assert elapsed < 1.0, "a leaked lock would make the retry wait for lock_wait_s"


def test_keys_are_stable_and_depend_on_the_arguments():
    key = make_key("shop:", "product", id=1)
    assert key == "shop:product:037c9214eef74cc3"  # fixed digest: must not change between processes
    assert make_key("shop:", "list", page=1, size=10) == make_key("shop:", "list", size=10, page=1)
    assert make_key("shop:", "product", id=1) != make_key("shop:", "product", id=2)


def test_default_wait_budget_outlasts_the_lock_lease():
    from app.config import Settings

    assert Settings().lock_wait_s > Settings().lock_ttl_ms / 1000
