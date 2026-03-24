"""Typed exception hierarchy for platform infrastructure.

All platform-layer exceptions inherit from ``PlatformError`` so callers
can catch broadly, while specific sub-types enable precise handling for
market data, execution, persistence, and connectivity issues.
"""
from __future__ import annotations


class PlatformError(Exception):
    """Base exception for all platform infrastructure errors."""


class MarketDataError(PlatformError):
    """Raised when market data acquisition or parsing fails."""


class StaleDataError(MarketDataError):
    """Raised when market data is older than the freshness threshold."""


class ExecutionError(PlatformError):
    """Raised on order execution infrastructure failures."""


class ConnectivityError(PlatformError):
    """Raised when a required external connection (Redis, exchange, DB) is unavailable."""


class RetryExhaustedError(PlatformError):
    """Raised when all retry attempts have been exhausted."""
