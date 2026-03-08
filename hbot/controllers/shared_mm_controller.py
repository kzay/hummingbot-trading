"""Compatibility alias for historical `shared_mm_controller` imports.

Prefer importing from `controllers.strategy_runtime_base`.
"""

from controllers.runtime.base import (
    StrategyRuntimeV24Config,
    StrategyRuntimeV24Controller,
)

SharedMmV24Config = StrategyRuntimeV24Config
SharedMmV24Controller = StrategyRuntimeV24Controller

__all__ = [
    "SharedMmV24Config",
    "SharedMmV24Controller",
]
