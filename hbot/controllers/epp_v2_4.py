"""Legacy compatibility wrapper for the shared market-making v2.4 controller.

The actual implementation now lives in `controllers.shared_mm_v24`. Keep this
module for backward-compatible imports, controller ids, configs, artifacts,
and tests that still import selected module-level helpers from here.
"""

from controllers.shared_mm_v24 import (
    EppV24Config,
    EppV24Controller,
    _10K,
    _ONE,
    _ZERO,
    _paper_reset_state_on_startup_enabled,
)

__all__ = [
    "EppV24Config",
    "EppV24Controller",
    "_ZERO",
    "_ONE",
    "_10K",
    "_paper_reset_state_on_startup_enabled",
]
