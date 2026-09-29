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

def test_broken_cache_stampedes_on_cold_key(settings, sync_redis):
    source = ProductSource(latency_s=0.3)
    responses = stampede(BrokenCacheAside, settings, source)

    assert all(r.status_code == 200 for r in responses)
    assert source.calls >= 40, f"expected a stampede, the source was called {source.calls} times"


def test_fixed_cache_loads_a_cold_key_once(settings, sync_redis):
    source = ProductSource(latency_s=0.3)
    responses = stampede(CacheAside, settings, source)

    assert all(r.status_code == 200 for r in responses)
    assert source.calls <= 2, f"the source was called {source.calls} times for one key"
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
