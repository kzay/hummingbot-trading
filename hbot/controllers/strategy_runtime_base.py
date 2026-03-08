"""Compatibility alias for the canonical runtime base module.

Prefer importing from `controllers.runtime.base`.
"""

from controllers.runtime.base import StrategyRuntimeV24Config, StrategyRuntimeV24Controller

__all__ = [
    "StrategyRuntimeV24Config",
    "StrategyRuntimeV24Controller",
]
