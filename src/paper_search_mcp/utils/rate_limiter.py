"""Token-bucket rate limiter for asyncio.

Ported from paper-search-mcp-nodejs RateLimiter.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from loguru import logger


class RateLimiter:
    """Async token-bucket rate limiter.

    Each platform gets its own instance with a configured RPS.
    Supports burst capacity and asyncio-friendly waiting.
    """

    def __init__(
        self,
        requests_per_second: float = 1.0,
        burst_capacity: Optional[int] = None,
    ) -> None:
        self.rps = requests_per_second
        self.interval = 1.0 / requests_per_second if requests_per_second > 0 else 1.0
        self.burst = burst_capacity or max(1, int(requests_per_second))
        self.tokens = float(self.burst)
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        if elapsed >= self.interval:
            tokens_to_add = elapsed / self.interval if self.interval > 0 else 0
            self.tokens = min(float(self.burst), self.tokens + tokens_to_add)
            self.last_refill = now

    async def acquire(self) -> None:
        """Wait until a request token is available."""
        while True:
            async with self._lock:
                self._refill()
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return

            # Wait one interval and try again
            await asyncio.sleep(self.interval)

    @property
    def status(self) -> dict:
        self._refill()
        return {
            "available_tokens": self.tokens,
            "max_tokens": self.burst,
            "rps": self.rps,
        }
