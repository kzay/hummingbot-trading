"""Bot7 ML strategy — thin controller wrapper over MlSignalSource + V3 desk.

Uses the standard market-making runtime (two-sided quotes, regime-aware
spreads) as the base execution engine.  The ML signal source provides
regime detection, adverse veto, and optional directional bias via the
V3 desk overlay.
"""
from __future__ import annotations

from pydantic import Field

from controllers.runtime.base import StrategyRuntimeV24Config, StrategyRuntimeV24Controller


class Bot7MlV1Config(StrategyRuntimeV24Config):
    """Bot7 ML strategy configuration.

    ML-specific parameters are exposed here so they can be set via YAML
    without touching the signal source code.
    """

    controller_name: str = "bot7_ml_v1"
    shared_edge_gate_enabled: bool = Field(default=True)

    # ── ML confidence thresholds ──────────────────────────────────────
    ml_direction_high_confidence: float = Field(default=0.70, ge=0.50, le=0.99)
    ml_direction_med_confidence: float = Field(default=0.60, ge=0.40, le=0.95)
    ml_adverse_confidence_threshold: float = Field(default=0.60, ge=0.30, le=0.95)
    ml_regime_min_confidence: float = Field(default=0.40, ge=0.20, le=0.90)

    # ── ML sizing ─────────────────────────────────────────────────────
    ml_use_sizing_model: bool = False
    ml_base_size_quote: float = Field(default=200.0, ge=10.0, le=5000.0)
    ml_max_levels: int = Field(default=3, ge=1, le=5)
    ml_base_spread_pct: float = Field(default=0.0015, ge=0.0005, le=0.0100)
    ml_spread_step_pct: float = Field(default=0.0010, ge=0.0002, le=0.0050)

    # ── ML position targets ───────────────────────────────────────────
    ml_target_net_base_pct: float = Field(default=0.04, ge=0.0, le=0.20)
    ml_fallback_regime: str = "neutral_low_vol"

    # ── ML model source ───────────────────────────────────────────────
    ml_exchange: str = "bitget"
    ml_pair: str = "BTC-USDT"


class Bot7MlV1Controller(StrategyRuntimeV24Controller):
    """Bot7 ML strategy controller — market-making base with ML overlay.

    Uses the standard SharedRuntimeKernel two-sided quoting as the
    execution engine.  The V3 desk (when enabled) adds ML-driven
    regime detection and directional bias on top.
    """
