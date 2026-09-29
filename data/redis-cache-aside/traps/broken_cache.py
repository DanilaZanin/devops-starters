"""Cache-aside as it is usually written first. Do not use this; it exists so the
tests can show what goes wrong. Same interface as app.cache.CacheAside.

1. Stampede. On a cold key, every concurrent request misses, and every one of them
   calls the source. 50 requests in flight means 50 database queries for one value.

2. No fail-open. Any Redis error propagates out of the request handler, so a Redis
   outage (or a restart, or a network blip) becomes a 500 on every endpoint that
   uses the cache, even though the source of truth is fine.
"""
from __future__ import annotations

import json

from app.cache import Loader


class BrokenCacheAside:
    def __init__(self, client, settings) -> None:
        self.client = client
        self.settings = settings

    async def get_or_load(self, key: str, loader: Loader):
        raw = await self.client.get(key)  # trap 2: raises when Redis is down
        if raw is not None:
            return json.loads(raw), "hit"
        value = await loader()  # trap 1: nothing stops N callers from all getting here
        await self.client.set(key, json.dumps(value), ex=self.settings.ttl_seconds)
        return value, "miss"

    async def invalidate(self, key: str) -> None:
        await self.client.delete(key)
