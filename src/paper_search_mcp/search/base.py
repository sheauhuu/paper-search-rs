"""Base searcher class — unified HTTP with retry, rate-limiting, caching, proxy."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from ..config import Config
from ..models import Paper
from ..utils.cache import RequestCache
from ..utils.proxy import parse_proxy_from_config
from ..utils.rate_limiter import RateLimiter
from ..utils.retry import retry_with_backoff


class BaseSearcher(ABC):
    """Abstract base class for all platform searchers.

    Provides:
    - Unified async HTTP via httpx
    - Token-bucket rate limiting
    - Exponential-backoff retry with full jitter
    - LRU request caching
    - Proxy support per-platform
    """

    platform_name: str = ""
    base_url: str = ""

    def __init__(self, config: Config) -> None:
        self.config = config
        plat_cfg = config.platform_config(self.platform_name)

        # Rate limiter
        rps = plat_cfg.get("rate_limit_rps", 1.0)
        self.rate_limiter = RateLimiter(requests_per_second=rps)

        # Cache (shared settings from config)
        cache_cfg = config.cache
        self.cache = RequestCache(
            max_size=cache_cfg.get("max_size", 100),
            ttl_seconds=cache_cfg.get("ttl_seconds", 3600),
        )

        # Retry settings
        retry_cfg = config.retry
        self.max_retries = retry_cfg.get("max_retries", 3)
        self.initial_delay = retry_cfg.get("initial_delay_seconds", 1.0)
        self.max_delay = retry_cfg.get("max_delay_seconds", 30.0)

        # Timeout
        self.timeout = config.timeout_seconds

        # Proxy — platform-level override
        self._use_proxy = plat_cfg.get("proxy", False)
        proxy_cfg = config.proxy if self._use_proxy else {}
        self.proxy_url = parse_proxy_from_config(proxy_cfg)

        # Platform-specific fields (e.g., api_key)
        self.api_key: Optional[str] = plat_cfg.get("api_key") or None
        self.max_results: int = plat_cfg.get("max_results", config.max_results_per_platform)
        self.last_diagnostics: Dict[str, Any] = {
            "platform": self.platform_name,
            "enabled": True,
            "api_key_present": bool(self.api_key),
        }

    def reset_diagnostics(self, **kwargs: Any) -> None:
        """Reset per-search diagnostics for the next request."""
        self.last_diagnostics = {
            "platform": self.platform_name,
            "enabled": True,
            "api_key_present": bool(self.api_key),
        }
        self.last_diagnostics.update(kwargs)

    def update_diagnostics(self, **kwargs: Any) -> None:
        """Merge additional diagnostic fields for the current request."""
        self.last_diagnostics.update(kwargs)

    def diagnostics_snapshot(self) -> Dict[str, Any]:
        """Return a copy of the latest diagnostics."""
        return dict(self.last_diagnostics)

    @abstractmethod
    async def search(self, query: str, **kwargs: Any) -> List[Paper]:
        """Search for papers. Subclasses must implement."""
        ...

    async def _request(
        self,
        url: str,
        *,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
        method: str = "GET",
        **kwargs: Any,
    ) -> httpx.Response:
        """Unified HTTP request with rate limiting, retry, and proxy.

        Raises httpx.HTTPStatusError on non-retryable failures after retries exhausted.
        """
        # Rate limit
        await self.rate_limiter.acquire()

        # Check cache for GET requests
        if method == "GET":
            cache_key = RequestCache.generate_key(self.platform_name, url, params)
            cached = self.cache.get(cache_key)
            if cached is not None:
                logger.debug(f"[{self.platform_name}] Cache hit for {url}")
                return cached

        # Build client with proxy and redirect following
        client_kwargs: dict[str, Any] = {
            "timeout": self.timeout,
            "follow_redirects": True,
        }
        if self.proxy_url:
            client_kwargs["proxy"] = self.proxy_url

        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.request(
                    method, url, params=params, headers=headers, **kwargs
                )
                response.raise_for_status()
                return response

        # Retry with backoff
        response = await retry_with_backoff(
            _do_request,
            max_retries=self.max_retries,
            initial_delay=self.initial_delay,
            max_delay=self.max_delay,
            context=f"{self.platform_name} {method} {url}",
        )

        # Cache successful GET responses
        if method == "GET":
            self.cache.set(cache_key, response)

        return response

    async def _get_json(self, url: str, **kwargs: Any) -> Any:
        """Convenience: GET request returning parsed JSON."""
        response = await self._request(url, **kwargs)
        return response.json()

    async def _get_text(self, url: str, **kwargs: Any) -> str:
        """Convenience: GET request returning text."""
        response = await self._request(url, **kwargs)
        return response.text
