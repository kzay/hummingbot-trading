"""Strategy-agnostic runtime base aliases for shared v2.4 controller stack."""

from controllers.runtime.directional_config import DirectionalRuntimeConfig
from controllers.runtime.directional_runtime import DirectionalRuntimeController
from controllers.shared_runtime_v24 import SharedMmV24Config, SharedMmV24Controller

StrategyRuntimeV24Config = SharedMmV24Config
StrategyRuntimeV24Controller = SharedMmV24Controller

DirectionalStrategyRuntimeV24Config = DirectionalRuntimeConfig
DirectionalStrategyRuntimeV24Controller = DirectionalRuntimeController

__all__ = [
    "DirectionalStrategyRuntimeV24Config",
    "DirectionalStrategyRuntimeV24Controller",
    "StrategyRuntimeV24Config",
    "StrategyRuntimeV24Controller",
]
