"""Directional strategy config — inherits shared fields, locks out MM defaults.

Directional bots (bot5, bot6, bot7) extend this config instead of
``EppV24Config`` / ``SharedMmV24Config``.  MM-only subsystem enable flags
are forced to ``False`` so they cannot accidentally activate.  The
corresponding methods are stubbed in ``DirectionalRuntimeController``
but this config layer provides defense-in-depth: even if a YAML sets
``alpha_policy_enabled: true``, the runtime overrides are still in place.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from controllers.shared_runtime_v24 import EppV24Config

_ZERO = Decimal("0")


class DirectionalRuntimeConfig(EppV24Config):
    """Config base for directional strategy lanes.

    Inherits all shared infrastructure fields (risk limits, fee, paper engine,
    regime detection, OB staleness, portfolio guard, etc.) while permanently
    disabling MM-only subsystems via field defaults.

    Bot-specific directional configs (e.g. ``Bot7AdaptiveGridV1Config``)
    should extend this class and add their own strategy fields.
    """

    # ── Strategy archetype ─────────────────────────────────────────────
    strategy_type: str = Field(default="directional")

    # ── Edge gate (disabled — directional bots don't use edge gating) ─
    shared_edge_gate_enabled: bool = Field(default=False)
    min_net_edge_bps: Decimal = Field(default=_ZERO)
    edge_resume_bps: Decimal = Field(default=_ZERO)
    edge_gate_ewma_period: int = Field(default=1, ge=1, le=120)

    # ── Alpha policy (disabled — directional bots use their own signal) ─
    alpha_policy_enabled: bool = Field(default=False)

    # ── Selective quoting (MM-only) ───────────────────────────────────
    selective_quoting_enabled: bool = Field(default=False)

    # ── Adverse fill soft-pause (MM-only) ─────────────────────────────
    adverse_fill_soft_pause_enabled: bool = Field(default=False)

    # ── Edge confidence soft-pause (MM-only) ──────────────────────────
    edge_confidence_soft_pause_enabled: bool = Field(default=False)

    # ── Slippage soft-pause (MM-only) ─────────────────────────────────
    slippage_soft_pause_enabled: bool = Field(default=False)

    # ── PnL governor (MM-only) ────────────────────────────────────────
    pnl_governor_enabled: bool = Field(default=False)

    # ── Adaptive spread params (MM-only) ──────────────────────────────
    adaptive_params_enabled: bool = Field(default=False)

    # ── Auto-calibration (MM-only) ────────────────────────────────────
    auto_calibration_enabled: bool = Field(default=False)

    # ── Kelly sizing (MM-only) ────────────────────────────────────────
    use_kelly_sizing: bool = Field(default=False)

    # ── Spread competitiveness cap (MM-only) ──────────────────────────
    max_quote_to_market_spread_mult: Decimal = Field(default=_ZERO)

    # ── OB imbalance skew (MM-only, directional uses its own signal) ──
    ob_imbalance_skew_weight: Decimal = Field(default=_ZERO)


__all__ = ["DirectionalRuntimeConfig"]
