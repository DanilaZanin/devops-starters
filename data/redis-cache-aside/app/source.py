"""Stand-in for the slow thing behind the cache (a database, an upstream API)."""
from __future__ import annotations

import asyncio


class ProductSource:
    def __init__(self, latency_s: float = 0.5) -> None:
        self.latency_s = latency_s
        self.calls = 0  # how many times the expensive path really ran

    async def fetch(self, product_id: int) -> dict:
        self.calls += 1
        call_number = self.calls
        await asyncio.sleep(self.latency_s)
        return {
            "id": product_id,
            "name": f"product-{product_id}",
            "price": round(10 + (product_id * 7) % 90 + 0.99, 2),
            "loaded_by_call": call_number,
        }
