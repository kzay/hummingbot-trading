"""Token bucket rate limiter for exchange API calls.

Tracks per-exchange request budgets and provides back-off signals.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict

logger = logging.getLogger(__name__)


@dataclass
class TokenBucket:
    """Simple token bucket rate limiter.

    ``capacity`` tokens are available per ``refill_interval_s``.
    Each ``consume()`` removes one token; ``wait_if_needed()`` blocks
    until a token is available.
    """

    capacity: int
    refill_interval_s: float
    _tokens: float = field(init=False)
    _last_refill_ts: float = field(init=False)

    def __post_init__(self) -> None:
        self._tokens = float(self.capacity)
        self._last_refill_ts = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill_ts
        added = elapsed / self.refill_interval_s * self.capacity
        self._tokens = min(float(self.capacity), self._tokens + added)
        self._last_refill_ts = now

    @property
    def tokens_remaining(self) -> float:
        self._refill()
        return self._tokens

    def try_consume(self, n: int = 1) -> bool:
        """Consume *n* tokens if available. Returns True on success."""
        self._refill()
        if self._tokens >= n:
            self._tokens -= n
            return True
        return False

    def wait_if_needed(self, n: int = 1) -> float:
        """Block until *n* tokens are available. Returns seconds waited."""
        waited = 0.0
        while not self.try_consume(n):
            sleep_s = self.refill_interval_s / max(1, self.capacity) * n
            time.sleep(sleep_s)
            waited += sleep_s
        if waited > 0:
            logger.debug("Rate limiter waited %.3fs for %d token(s)", waited, n)
        return waited


class ExchangeRateLimiter:
    """Per-exchange rate limiter registry.

    Default budgets (conservative):
    - Bitget: 10 req/s (orders), 20 req/s (queries)
    - Binance: 20 req/s (orders), 40 req/s (queries)
    """

    def __init__(self) -> None:
        self._buckets: Dict[str, TokenBucket] = {}

    def get_or_create(
        self,
        exchange: str,
        capacity: int = 10,
        refill_interval_s: float = 1.0,
    ) -> TokenBucket:
        """Get or create a rate limiter for *exchange*."""
        canonical = exchange.replace("_paper_trade", "").replace("_testnet", "")
        if canonical not in self._buckets:
            self._buckets[canonical] = TokenBucket(
                capacity=capacity,
                refill_interval_s=refill_interval_s,
            )
        return self._buckets[canonical]

    def consume(self, exchange: str, n: int = 1) -> bool:
        """Try to consume *n* tokens from *exchange*'s bucket."""
        bucket = self.get_or_create(exchange)
        return bucket.try_consume(n)

    def remaining(self, exchange: str) -> float:
        """Return remaining tokens for *exchange*."""
        bucket = self.get_or_create(exchange)
        return bucket.tokens_remaining
