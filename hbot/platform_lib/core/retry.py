"""Retry utilities with exponential backoff for exchange API calls.

Handles 429 (rate limit) and 5xx errors with configurable retries.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Retryable: 429, 5xx, connection errors
_RETRYABLE_PATTERNS = ("429", "503", "502", "504", "500", "timeout", "connection", "rate limit")


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(p in msg for p in _RETRYABLE_PATTERNS)


def with_retry(
    fn: Callable[[], T],
    max_attempts: int = 4,
    base_delay_s: float = 2.0,
    max_delay_s: float = 60.0,
    retryable: Callable[[Exception], bool] | None = None,
) -> T:
    """Execute fn with exponential backoff on retryable errors.

    Args:
        fn: Callable that takes no args and returns T
        max_attempts: Max attempts (default 4)
        base_delay_s: Initial delay in seconds (default 2)
        max_delay_s: Cap on delay (default 60)
        retryable: Optional predicate; default checks for 429/5xx/timeout

    Returns:
        Result of fn()

    Raises:
        Last exception if all attempts fail
    """
    pred = retryable or _is_retryable
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt == max_attempts - 1 or not pred(e):
                raise
            delay = min(base_delay_s * (2 ** attempt), max_delay_s)
            delay *= 1.0 + random.uniform(0, 0.5)
            logger.warning("Retry %d/%d after %s: %s — sleeping %.1fs", attempt + 1, max_attempts, type(e).__name__, e, delay)
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


async def async_with_retry(
    fn: Callable[[], Awaitable[T]],
    max_attempts: int = 4,
    base_delay_s: float = 2.0,
    max_delay_s: float = 60.0,
    retryable: Callable[[Exception], bool] | None = None,
) -> T:
    """Execute async fn with exponential backoff on retryable errors.

    Args:
        fn: Async callable that takes no args and returns T
        max_attempts: Max attempts (default 4)
        base_delay_s: Initial delay in seconds (default 2)
        max_delay_s: Cap on delay (default 60)
        retryable: Optional predicate; default checks for 429/5xx/timeout

    Returns:
        Result of await fn()

    Raises:
        Last exception if all attempts fail
    """
    pred = retryable or _is_retryable
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await fn()
        except Exception as e:
            last_exc = e
            if attempt == max_attempts - 1 or not pred(e):
                raise
            delay = min(base_delay_s * (2 ** attempt), max_delay_s)
            delay *= 1.0 + random.uniform(0, 0.5)
            logger.warning("Retry %d/%d after %s: %s — sleeping %.1fs", attempt + 1, max_attempts, type(e).__name__, e, delay)
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc
