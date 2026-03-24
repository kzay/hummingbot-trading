"""Backward-compat shim — real implementation in controllers.runtime.kernel.

All classes, constants, and helpers have moved to the kernel package.
This module re-exports them so existing importers continue to work.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── Classes ───────────────────────────────────────────────────────────
from controllers.runtime.kernel.controller import (  # noqa: F401
    EppV24Controller,
    SharedMmV24Config,
    SharedMmV24Controller,
    SharedRuntimeKernel,
    SharedRuntimeV24Config,
    SharedRuntimeV24Controller,
)

# ── Config ────────────────────────────────────────────────────────────
from controllers.runtime.kernel.config import (  # noqa: F401
    EppV24Config,
    _10K,
    _100,
    _BALANCE_EPSILON,
    _BOT_MODE_WARNED_INVALID,
    _FILL_FACTOR_LO,
    _INVENTORY_DERISK_REASONS,
    _MIN_SKEW_CAP,
    _MIN_SPREAD,
    _ONE,
    _TWO,
    _ZERO,
    _canonical_connector_name,
    _clip,
    _config_is_paper,
    _identity_text,
    _market_making_adapter,
    _paper_reset_state_on_startup_enabled,
    _runtime_bot_mode,
    _runtime_compat_surface,
    _runtime_family_adapter,
)

__all__ = [
    "EppV24Config",
    "EppV24Controller",
    "SharedMmV24Config",
    "SharedMmV24Controller",
    "SharedRuntimeKernel",
    "SharedRuntimeV24Config",
    "SharedRuntimeV24Controller",
]
