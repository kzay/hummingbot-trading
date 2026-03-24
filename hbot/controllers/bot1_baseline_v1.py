"""Neutral convenience re-export for bot1 baseline lane.

Canonical implementation: ``controllers.bots.bot1.baseline_v1``
"""
from controllers.bots.bot1.baseline_v1 import Bot1BaselineV1Config, Bot1BaselineV1Controller  # noqa: F401

__all__ = ["Bot1BaselineV1Config", "Bot1BaselineV1Controller"]
