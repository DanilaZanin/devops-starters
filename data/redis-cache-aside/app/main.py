import asyncio
import os
import random

from fastapi import FastAPI

from cache_aside import cached, configure, stats

app = FastAPI(title="cache-aside demo")


@app.on_event("startup")
async def startup():
    configure(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


@cached(ttl_seconds=30, prefix="product")
async def fetch_product(product_id: int) -> dict:
    # stands in for a slow DB query / external API call
    await asyncio.sleep(0.5)
    return {
        "product_id": product_id,
        "name": f"product-{product_id}",
        "price": round(random.uniform(10, 200), 2),
    }


@app.get("/products/{product_id}")
async def get_product(product_id: int):
    return await fetch_product(product_id)


@app.get("/cache-stats")
async def cache_stats():
    return stats


@app.get("/health")
async def health():
    return {"status": "ok"}
