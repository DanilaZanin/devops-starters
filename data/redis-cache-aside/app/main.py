"""FastAPI app. Run with: uvicorn --factory app.main:create_app"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response

from .cache import CacheAside, CacheUnavailable, make_client, make_key
from .config import Settings
from .source import ProductSource


def create_app(settings: Settings | None = None, cache_cls=CacheAside, source: ProductSource | None = None) -> FastAPI:
    """`cache_cls` and `source` are injectable so the tests can swap in the broken
    cache and count calls to the source."""
    settings = settings or Settings.from_env()
    source = source or ProductSource(settings.source_latency_s)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = make_client(settings)
        app.state.cache = cache_cls(client, settings)
        try:
            yield
        finally:
            await client.aclose()

    app = FastAPI(title="cache-aside example", lifespan=lifespan)

    def product_key(product_id: int) -> str:
        return make_key(settings.key_prefix, "product", id=product_id)

    @app.get("/products/{product_id}")
    async def get_product(product_id: int, response: Response):
        value, status = await app.state.cache.get_or_load(product_key(product_id), lambda: source.fetch(product_id))
        response.headers["X-Cache"] = status
        return value

    @app.delete("/products/{product_id}/cache")
    async def invalidate_product(product_id: int):
        try:
            await app.state.cache.invalidate(product_key(product_id))
        except CacheUnavailable:
            raise HTTPException(status_code=503, detail="cache unreachable, stale value may remain until TTL") from None
        return {"invalidated": True}

    @app.get("/health")
    async def health():
        # Liveness only. Redis being down must not take the app out of rotation:
        # the whole point is that it keeps serving from the source.
        return {"status": "ok"}

    return app
