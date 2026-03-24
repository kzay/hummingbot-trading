"""Legacy compatibility wrapper for the shared runtime v2.4 controller.

The actual implementation now lives in ``controllers.runtime.kernel``. Keep this
module for backward-compatible imports, controller ids, configs, artifacts,
and tests that still import selected module-level helpers from here.
"""

from controllers.runtime.kernel.config import (
    _10K,
    _ONE,
    _ZERO,
    EppV24Config,
    _paper_reset_state_on_startup_enabled,
)
from controllers.runtime.kernel.controller import EppV24Controller

__all__ = [
    "_10K",
    "_ONE",
    "_ZERO",
    "EppV24Config",
    "EppV24Controller",
    "_paper_reset_state_on_startup_enabled",
]
