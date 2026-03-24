"""Typed exception hierarchy for the simulation engine.

All simulation-layer exceptions inherit from ``SimulationError`` so callers
can catch broadly when needed, but specific sub-types enable precise handling
where it matters (e.g. matching engine vs. portfolio vs. bridge).
"""
from __future__ import annotations


class SimulationError(Exception):
    """Base exception for all simulation-layer errors."""


class MatchingEngineError(SimulationError):
    """Raised when the order matching engine encounters an unrecoverable state."""


class PortfolioError(SimulationError):
    """Raised on portfolio constraint violations (margin, balance, position limits)."""


class BridgeError(SimulationError):
    """Raised when the Hummingbot bridge fails to translate or route events."""


class FeedError(SimulationError):
    """Raised when a market data feed cannot deliver required data."""


class StateStoreError(SimulationError):
    """Raised on persistence failures (Redis, JSON file, event journal)."""


class ConfigurationError(SimulationError, ValueError):
    """Raised when simulation configuration is invalid or inconsistent."""
