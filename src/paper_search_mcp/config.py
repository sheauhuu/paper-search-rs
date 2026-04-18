"""Configuration loader — environment variables plus built-in defaults."""

from __future__ import annotations

from copy import deepcopy
import os
from typing import Any, Dict, List, Optional

from loguru import logger

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _read_env(name: str) -> Optional[str]:
    """Return a stripped env value when explicitly provided."""
    if name not in os.environ:
        return None
    return os.environ[name].strip()


def _parse_bool(name: str, default: bool) -> bool:
    value = _read_env(name)
    if value is None:
        return default

    lowered = value.lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False

    logger.warning(f"[config] Invalid boolean for {name}: {value!r}; using {default}")
    return default


def _parse_int(name: str, default: int) -> int:
    value = _read_env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning(f"[config] Invalid integer for {name}: {value!r}; using {default}")
        return default


def _parse_float(name: str, default: float) -> float:
    value = _read_env(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning(f"[config] Invalid float for {name}: {value!r}; using {default}")
        return default


def _parse_csv(name: str, default: List[str]) -> List[str]:
    value = _read_env(name)
    if value is None:
        return default
    return [part.strip() for part in value.split(",") if part.strip()]


def _parse_text(name: str, default: str) -> str:
    value = _read_env(name)
    if value is None:
        return default
    return value


_DEFAULT_CONFIG: Dict[str, Any] = {
    "search": {
        "default_platforms": ["arxiv", "semantic_scholar", "google_scholar", "crossref"],
        "max_results_per_platform": 10,
        "max_concurrent_searches": 5,
        "timeout_seconds": 30,
    },
    "platforms": {
        "arxiv": {"enabled": True, "max_results": 50, "rate_limit_rps": 0.33},
        "google_scholar": {"enabled": True, "max_results": 20, "rate_limit_rps": 0.5, "proxy": True},
        "semantic_scholar": {"enabled": True, "max_results": 100, "rate_limit_rps": 3.0, "api_key": ""},
        "crossref": {"enabled": True, "max_results": 100, "rate_limit_rps": 3.0, "mailto": ""},
        "pubmed": {"enabled": False, "api_key": "", "rate_limit_rps": 3.0},
        "scopus": {"enabled": False, "api_key": "", "rate_limit_rps": 2.0},
        "biorxiv": {"enabled": False, "rate_limit_rps": 1.0},
        "medrxiv": {"enabled": False, "rate_limit_rps": 1.0},
        "webofscience": {"enabled": False, "api_key": "", "rate_limit_rps": 5.0, "max_results": 50},
    },
    "proxy": {
        "http": "",
        "https": "",
        "socks5": "",
    },
    "cache": {
        "max_size": 100,
        "ttl_seconds": 3600,
    },
    "retry": {
        "max_retries": 3,
        "initial_delay_seconds": 1.0,
        "max_delay_seconds": 30.0,
    },
    "jcr": {
        "enabled": False,
        "data_dir": "",
        "auto_update": False,
        "max_age_days": 30,
    },
    "debug": {
        "enabled": False,
    },
}


_PLATFORM_SECRET_ENV = {
    "semantic_scholar": {"api_key": "SEMANTIC_SCHOLAR_API_KEY"},
    "crossref": {"mailto": "CROSSREF_MAILTO"},
    "pubmed": {"api_key": "PUBMED_API_KEY"},
    "scopus": {"api_key": "SCOPUS_API_KEY"},
    "webofscience": {"api_key": "WOS_API_KEY"},
}


def _apply_env_overrides(config: dict[str, Any]) -> None:
    """Overlay built-in defaults with environment variables."""
    search = config["search"]
    search["default_platforms"] = _parse_csv(
        "PAPER_SEARCH_DEFAULT_PLATFORMS",
        search["default_platforms"],
    )
    search["max_results_per_platform"] = _parse_int(
        "PAPER_SEARCH_MAX_RESULTS_PER_PLATFORM",
        search["max_results_per_platform"],
    )
    search["max_concurrent_searches"] = _parse_int(
        "PAPER_SEARCH_MAX_CONCURRENT_SEARCHES",
        search["max_concurrent_searches"],
    )
    search["timeout_seconds"] = _parse_int(
        "PAPER_SEARCH_TIMEOUT_SECONDS",
        search["timeout_seconds"],
    )

    cache = config["cache"]
    cache["max_size"] = _parse_int("PAPER_SEARCH_CACHE_MAX_SIZE", cache["max_size"])
    cache["ttl_seconds"] = _parse_int("PAPER_SEARCH_CACHE_TTL_SECONDS", cache["ttl_seconds"])

    retry = config["retry"]
    retry["max_retries"] = _parse_int("PAPER_SEARCH_RETRY_MAX_RETRIES", retry["max_retries"])
    retry["initial_delay_seconds"] = _parse_float(
        "PAPER_SEARCH_RETRY_INITIAL_DELAY_SECONDS",
        retry["initial_delay_seconds"],
    )
    retry["max_delay_seconds"] = _parse_float(
        "PAPER_SEARCH_RETRY_MAX_DELAY_SECONDS",
        retry["max_delay_seconds"],
    )

    jcr = config["jcr"]
    jcr["enabled"] = _parse_bool("PAPER_SEARCH_JCR_ENABLED", jcr["enabled"])
    jcr["data_dir"] = _parse_text("PAPER_SEARCH_JCR_DATA_DIR", jcr["data_dir"])
    jcr["auto_update"] = _parse_bool("PAPER_SEARCH_JCR_AUTO_UPDATE", jcr["auto_update"])
    jcr["max_age_days"] = _parse_int("PAPER_SEARCH_JCR_MAX_AGE_DAYS", jcr["max_age_days"])

    debug = config["debug"]
    debug["enabled"] = _parse_bool("PAPER_SEARCH_DEBUG", debug["enabled"])

    proxy = config["proxy"]
    proxy["http"] = _parse_text("HTTP_PROXY", proxy["http"])
    proxy["https"] = _parse_text("HTTPS_PROXY", proxy["https"])
    proxy["socks5"] = _parse_text("SOCKS_PROXY", proxy["socks5"])

    for platform_name, platform_config in config["platforms"].items():
        prefix = f"PAPER_SEARCH_PLATFORM_{platform_name.upper()}_"
        platform_config["enabled"] = _parse_bool(f"{prefix}ENABLED", platform_config["enabled"])
        platform_config["max_results"] = _parse_int(
            f"{prefix}MAX_RESULTS",
            platform_config.get("max_results", config["search"]["max_results_per_platform"]),
        )
        platform_config["rate_limit_rps"] = _parse_float(
            f"{prefix}RATE_LIMIT_RPS",
            platform_config["rate_limit_rps"],
        )
        platform_config["proxy"] = _parse_bool(
            f"{prefix}PROXY",
            platform_config.get("proxy", False),
        )

        for key, env_name in _PLATFORM_SECRET_ENV.get(platform_name, {}).items():
            platform_config[key] = _parse_text(env_name, platform_config.get(key, ""))


class Config:
    """Application configuration loaded from environment variables."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        self._raw: Dict[str, Any] = {}
        self._load(config_path)

    def _load(self, config_path: Optional[str] = None) -> None:
        self._raw = deepcopy(_DEFAULT_CONFIG)

        if config_path:
            logger.warning(
                "[config] config files are deprecated and ignored; use environment variables instead"
            )

        _apply_env_overrides(self._raw)
        logger.info("Loaded config from environment variables and built-in defaults")

    # --- Convenience accessors ---

    @property
    def search(self) -> dict:
        return self._raw.get("search", {})

    @property
    def default_platforms(self) -> List[str]:
        return self.search.get("default_platforms", ["arxiv"])

    @property
    def max_results_per_platform(self) -> int:
        return self.search.get("max_results_per_platform", 10)

    @property
    def max_concurrent_searches(self) -> int:
        return self.search.get("max_concurrent_searches", 5)

    @property
    def timeout_seconds(self) -> int:
        return self.search.get("timeout_seconds", 30)

    @property
    def platforms(self) -> dict:
        return self._raw.get("platforms", {})

    def platform_config(self, name: str) -> dict:
        """Get merged config for a specific platform."""
        return self.platforms.get(name, {})

    def is_platform_enabled(self, name: str) -> bool:
        return self.platform_config(name).get("enabled", False)

    @property
    def proxy(self) -> dict:
        return self._raw.get("proxy", {})

    @property
    def cache(self) -> dict:
        return self._raw.get("cache", {})

    @property
    def retry(self) -> dict:
        return self._raw.get("retry", {})

    @property
    def jcr(self) -> dict:
        return self._raw.get("jcr", {})

    @property
    def debug(self) -> dict:
        return self._raw.get("debug", {})

    @property
    def debug_enabled(self) -> bool:
        return bool(self.debug.get("enabled", False))

    def enabled_platforms(self) -> List[str]:
        """Return list of enabled platform names, respecting default_platforms order."""
        platforms = []
        for name in self.default_platforms:
            if self.is_platform_enabled(name):
                platforms.append(name)
        # Add any enabled platforms not in default list
        for name, cfg in self.platforms.items():
            if cfg.get("enabled", False) and name not in platforms:
                platforms.append(name)
        return platforms

    def to_dict(self) -> dict:
        return deepcopy(self._raw)
