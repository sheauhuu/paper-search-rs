"""Proxy configuration parser for httpx."""

from __future__ import annotations

from typing import Optional


def build_proxy_url(
    http_proxy: str = "",
    https_proxy: str = "",
    socks5_proxy: str = "",
) -> Optional[str]:
    """Build a proxy URL suitable for httpx from config values.

    httpx supports a single proxy via `proxy` parameter or
    a dict via `proxies={"http://": ..., "https://": ...}`.

    Priority: socks5 > https > http
    """
    if socks5_proxy:
        return f"socks5://{socks5_proxy}" if not socks5_proxy.startswith("socks5://") else socks5_proxy
    if https_proxy:
        return https_proxy
    if http_proxy:
        return http_proxy
    return None


def parse_proxy_from_config(config: dict) -> Optional[str]:
    """Extract proxy URL from a proxy config dict."""
    if not config:
        return None
    return build_proxy_url(
        http_proxy=config.get("http", ""),
        https_proxy=config.get("https", ""),
        socks5_proxy=config.get("socks5", ""),
    )
