"""Strategy-agnostic runtime base aliases for shared v2.4 controller stack."""

from controllers.epp_v2_4 import EppV24Config, EppV24Controller

StrategyRuntimeV24Config = EppV24Config
StrategyRuntimeV24Controller = EppV24Controller

__all__ = [
    "StrategyRuntimeV24Config",
    "StrategyRuntimeV24Controller",
]
