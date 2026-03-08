"""Neutral entrypoint for the shared market-making v2.4 base controller.

Use this module for new strategy lanes so controller names do not encode the
historical EPP label.
"""

from controllers.runtime.base import StrategyRuntimeV24Config, StrategyRuntimeV24Controller


class SharedMmV24Config(StrategyRuntimeV24Config):
    """Config alias for the shared market-making v2.4 base."""

    controller_name: str = "shared_mm_v24"


class SharedMmV24Controller(StrategyRuntimeV24Controller):
    """Controller alias for the shared market-making v2.4 base."""


__all__ = [
    "SharedMmV24Config",
    "SharedMmV24Controller",
]
