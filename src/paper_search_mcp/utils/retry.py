"""Exponential-backoff retry with full jitter.

Ported from paper-search-mcp-nodejs ErrorHandler.retryWithBackoff.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Callable, Coroutine, TypeVar

from loguru import logger

T = TypeVar("T")

# Status codes that are retryable
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
# Status codes that should NOT be retried
NON_RETRYABLE_STATUS = {400, 401, 403, 404, 405}


def is_retryable_status(status_code: int | None) -> bool:
    """Check if an HTTP status code is worth retrying."""
    if status_code is None:
        return True  # Network errors / timeouts are retryable
    return status_code in RETRYABLE_STATUS


async def retry_with_backoff(
    fn: Callable[[], Coroutine[Any, Any, T]],
    *,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    context: str = "operation",
) -> T:
    """Retry an async function with exponential backoff and full jitter.

    Respects Retry-After headers on 429 responses.
    Only retries on retryable HTTP status codes (429/5xx/timeout).
    """
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as exc:
            last_error = exc
            if attempt >= max_retries:
                break

            # Determine status code from httpx exception
            status_code = getattr(getattr(exc, "response", None), "status_code", None)

            if not is_retryable_status(status_code):
                logger.warning(f"[{context}] Non-retryable error ({status_code}): {exc}")
                raise

            # Check Retry-After header for 429
            retry_after: float | None = None
            if status_code == 429:
                resp = getattr(exc, "response", None)
                if resp is not None:
                    ra = resp.headers.get("retry-after")
                    if ra is not None:
                        try:
                            retry_after = float(ra)
                        except ValueError:
                            pass

            if retry_after is not None:
                delay = min(max_delay, retry_after)
            else:
                # Exponential backoff with full jitter
                base_delay = min(max_delay, initial_delay * (2 ** attempt))
                delay = random.uniform(0, base_delay)

            logger.info(
                f"[{context}] Attempt {attempt + 1}/{max_retries} failed "
                f"({status_code}), retrying in {delay:.1f}s"
            )
            await asyncio.sleep(delay)

    assert last_error is not None
    raise last_error
