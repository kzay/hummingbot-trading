"""Strategy-agnostic runtime base aliases for shared v2.4 controller stack."""

from controllers.shared_mm_v24 import SharedMmV24Config, SharedMmV24Controller

StrategyRuntimeV24Config = SharedMmV24Config
StrategyRuntimeV24Controller = SharedMmV24Controller

__all__ = [
    "StrategyRuntimeV24Config",
    "StrategyRuntimeV24Controller",
]
