"""LRU request cache with SHA-256 key hashing.

Ported from paper-search-mcp-nodejs RequestCache.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from typing import Any, Optional

from loguru import logger


class RequestCache:
    """Simple LRU cache for search results.

    Uses SHA-256 hash of (platform, query, options) as key.
    Supports configurable TTL and max size.
    """

    def __init__(self, max_size: int = 100, ttl_seconds: int = 3600) -> None:
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def generate_key(platform: str, query: str, options: Optional[dict] = None) -> str:
        data = json.dumps(
            {"platform": platform, "query": query.lower().strip(), "options": options or {}},
            sort_keys=True,
        )
        return hashlib.sha256(data.encode()).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            ts, value = self._cache[key]
            if time.monotonic() - ts < self.ttl:
                self._cache.move_to_end(key)
                self._hits += 1
                return value
            # Expired — remove
            del self._cache[key]
        self._misses += 1
        return None

    def set(self, key: str, value: Any) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = (time.monotonic(), value)
        # Evict oldest if over capacity
        while len(self._cache) > self.max_size:
            self._cache.popitem(last=False)

    def clear(self) -> None:
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0,
        }
