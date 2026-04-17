"""Configuration loader — YAML with environment variable interpolation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from loguru import logger

# Pattern: ${VAR} or ${VAR:default}
_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")


def _interpolate_env(value: Any) -> Any:
    """Recursively interpolate ${VAR} and ${VAR:default} in config values."""
    if isinstance(value, str):
        def _replace(m: re.Match) -> str:
            var_name = m.group(1)
            default = m.group(2)  # None if no default
            env_val = os.environ.get(var_name)
            if env_val is not None:
                return env_val
            if default is not None:
                return default
            return m.group(0)  # Leave as-is if no env and no default
        return _ENV_PATTERN.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(v) for v in value]
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
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively."""
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class Config:
    """Application configuration loaded from YAML with env-var overrides."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        self._raw: Dict[str, Any] = {}
        self._load(config_path)

    def _load(self, config_path: Optional[str] = None) -> None:
        # Start from defaults
        self._raw = _DEFAULT_CONFIG.copy()

        # Try to load from file
        paths_to_try: list[Path] = []
        if config_path:
            paths_to_try.append(Path(config_path))
        # Also check CWD and package dir
        paths_to_try.extend([
            Path.cwd() / "config.yaml",
            Path(__file__).parent.parent.parent / "config.yaml",
        ])

        for p in paths_to_try:
            if p.is_file():
                logger.info(f"Loading config from {p}")
                with open(p) as f:
                    file_data = yaml.safe_load(f) or {}
                self._raw = _deep_merge(self._raw, file_data)
                break
        else:
            logger.info("No config.yaml found, using defaults")

        # Interpolate environment variables
        self._raw = _interpolate_env(self._raw)

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
        return self._raw.copy()
