"""Phase-one strategy family/template registry with bounded search contracts.

Each registered family defines:
- Supported adapters for that family
- Bounded parameter contracts (min/max for each parameter category)
- Invalid-combination rules
- Required data inputs
- Default risk budget
- Per-trade risk range

Usage::

    from controllers.research.family_registry import FAMILY_REGISTRY, get_family

    family = get_family("trend_continuation")
    violations = family.check_bounds(candidate.effective_search_space)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParameterBounds:
    """Min/max bounds for a named parameter category."""

    name: str
    min_val: float
    max_val: float
    description: str = ""

    def contains(self, value: float) -> bool:
        return self.min_val <= value <= self.max_val


@dataclass
class FamilyTemplate:
    """A specific strategy template within a family."""

    template_id: str
    description: str
    primary_adapters: list[str]
    required_params: list[str]
    default_search_space: dict[str, list[Any]]


@dataclass
class StrategyFamily:
    """Definition of a phase-one strategy family."""

    name: str
    description: str
    supported_adapters: list[str]
    required_data: list[str]
    default_complexity_budget: int
    per_trade_risk_min_pct: float  # % of equity, e.g. 0.25
    per_trade_risk_max_pct: float  # % of equity, e.g. 1.0
    parameter_bounds: list[ParameterBounds]
    invalid_combinations: list[str]  # human-readable rule descriptions
    templates: list[FamilyTemplate] = field(default_factory=list)

    def check_bounds(self, search_space: dict[str, Any]) -> list[str]:
        """Check that all numeric values in search_space respect family bounds.

        Returns a list of violation strings (empty if all valid).
        """
        violations: list[str] = []
        bounds_by_name = {b.name: b for b in self.parameter_bounds}

        for param_name, values in search_space.items():
            if not isinstance(values, list):
                values = [values]
            for bound_name, bounds in bounds_by_name.items():
                # Match bound by substring so 'trend_window' matches 'trend_*'
                if bound_name not in param_name:
                    continue
                for v in values:
                    try:
                        fv = float(v)
                    except (TypeError, ValueError):
                        continue
                    if not bounds.contains(fv):
                        violations.append(
                            f"{param_name}={v} violates {bound_name} bounds "
                            f"[{bounds.min_val}, {bounds.max_val}]"
                        )
        return violations

    def check_monotonicity(self, search_space: dict[str, Any]) -> list[str]:
        """Check that fast/slow pairs and short/long pairs are ordered correctly.

        Returns a list of violation strings (empty if all valid).
        """
        violations: list[str] = []

        pairs = [
            ("fast", "slow"),
            ("short", "long"),
            ("min", "max"),
            ("entry", "exit"),
            ("stop", "target"),
        ]

        for lo_key, hi_key in pairs:
            lo_params = {k: v for k, v in search_space.items() if lo_key in k}
            hi_params = {k: v for k, v in search_space.items() if hi_key in k}
            for lo_name, lo_vals in lo_params.items():
                # Try to find a matching hi param
                for hi_name, hi_vals in hi_params.items():
                    # Match by shared stem minus the fast/slow suffix
                    if not isinstance(lo_vals, list):
                        lo_vals = [lo_vals]
                    if not isinstance(hi_vals, list):
                        hi_vals = [hi_vals]
                    try:
                        lo_min = min(float(v) for v in lo_vals)
                        hi_max = max(float(v) for v in hi_vals)
                        hi_min = min(float(v) for v in hi_vals)
                    except (TypeError, ValueError):
                        continue
                    if lo_min >= hi_min:
                        violations.append(
                            f"Ordering violation: {lo_name} min ({lo_min}) "
                            f">= {hi_name} min ({hi_min})"
                        )
        return violations

    def get_template(self, template_id: str) -> FamilyTemplate | None:
        for t in self.templates:
            if t.template_id == template_id:
                return t
        return None


# ---------------------------------------------------------------------------
# Phase-one family definitions
# ---------------------------------------------------------------------------

_TREND_CONTINUATION = StrategyFamily(
    name="trend_continuation",
    description=(
        "Enter in the direction of an established trend using pullback confirmation. "
        "Hold until trend exhaustion or stop breach."
    ),
    supported_adapters=["pullback", "pullback_v2", "atr_mm_v2", "directional_mm", "ta_composite"],
    required_data=[],
    default_complexity_budget=5,
    per_trade_risk_min_pct=0.25,
    per_trade_risk_max_pct=1.0,
    parameter_bounds=[
        ParameterBounds("trend_window", 20, 200, "trend EMA/SMA period"),
        ParameterBounds("trend_period", 20, 200, "trend period alias"),
        ParameterBounds("ema_period", 20, 200, "EMA period"),
        ParameterBounds("stop_atr", 0.5, 4.0, "stop loss ATR multiple"),
        ParameterBounds("target_atr", 0.5, 4.0, "take profit ATR multiple"),
        ParameterBounds("pullback_depth", 0.25, 1.5, "pullback depth in ATR"),
        ParameterBounds("hold_bars", 1, 48, "max hold in bars"),
        ParameterBounds("cooldown", 1, 48, "cooldown bars after trade"),
    ],
    invalid_combinations=[
        "stop_atr_mult >= tp_atr_mult (stop above target)",
        "fast_ema >= slow_ema (fast window >= slow window)",
        "pullback_depth_atr > 2.0 (pullback deeper than 2 ATR is noise)",
    ],
    templates=[
        FamilyTemplate(
            template_id="trend_continuation_pullback",
            description="Enter on ATR pullback against established trend direction",
            primary_adapters=["pullback", "pullback_v2"],
            required_params=["pullback_depth_atr", "trend_ema", "stop_atr_mult"],
            default_search_space={
                "pullback_depth_atr": [0.3, 0.5, 0.8, 1.2],
                "trend_ema": [50, 100, 150, 200],
                "stop_atr_mult": [1.0, 1.5, 2.0],
            },
        ),
        FamilyTemplate(
            template_id="trend_continuation_htf",
            description="Multi-timeframe trend continuation with HTF filter",
            primary_adapters=["atr_mm_v2", "pullback_v2"],
            required_params=["htf_ema", "stop_atr_mult"],
            default_search_space={
                "htf_ema": [100, 150, 200],
                "stop_atr_mult": [1.0, 1.5, 2.0, 2.5],
                "vol_scalar": [0.5, 1.0, 1.5],
            },
        ),
    ],
)

_TREND_PULLBACK = StrategyFamily(
    name="trend_pullback",
    description=(
        "Enter counter-trend at pullback extremes expecting mean-reversion back "
        "toward the trend. Short hold, tight stops."
    ),
    supported_adapters=["pullback", "pullback_v2", "momentum_scalper", "ta_composite"],
    required_data=[],
    default_complexity_budget=4,
    per_trade_risk_min_pct=0.25,
    per_trade_risk_max_pct=0.75,
    parameter_bounds=[
        ParameterBounds("trend_window", 20, 200, "trend period"),
        ParameterBounds("trend_period", 20, 200, "trend period alias"),
        ParameterBounds("retrace_depth", 0.25, 1.5, "retracement depth in ATR"),
        ParameterBounds("stop_atr", 0.5, 2.5, "stop ATR multiple (tighter for pullback)"),
        ParameterBounds("target_atr", 0.5, 3.0, "target ATR multiple"),
        ParameterBounds("hold_bars", 1, 24, "short hold for pullback entries"),
        ParameterBounds("cooldown", 1, 24, "cooldown bars"),
    ],
    invalid_combinations=[
        "stop_atr_mult >= tp_atr_mult (stop above target)",
        "ltf_rsi threshold > 60 (RSI entry not in oversold/overbought zone)",
    ],
    templates=[
        FamilyTemplate(
            template_id="trend_pullback_rsi",
            description="Enter on RSI extreme during pullback phase",
            primary_adapters=["pullback_v2", "ta_composite"],
            required_params=["ltf_entry_rsi", "stop_atr_mult"],
            default_search_space={
                "ltf_entry_rsi": [25, 30, 35],
                "confirmation_bars": [1, 2, 3],
                "stop_atr_mult": [0.8, 1.2, 1.8],
            },
        ),
    ],
)

_COMPRESSION_BREAKOUT = StrategyFamily(
    name="compression_breakout",
    description=(
        "Enter on breakout from a period of price compression (low ATR / "
        "narrow Bollinger Bands). Direction follows breakout candle."
    ),
    supported_adapters=["momentum_scalper", "ta_composite", "smc_mm", "atr_mm"],
    required_data=[],
    default_complexity_budget=5,
    per_trade_risk_min_pct=0.25,
    per_trade_risk_max_pct=1.0,
    parameter_bounds=[
        ParameterBounds("breakout_lookback", 12, 96, "compression lookback bars"),
        ParameterBounds("vol_window", 10, 50, "volatility window"),
        ParameterBounds("bb_period", 10, 50, "Bollinger Band period"),
        ParameterBounds("stop_atr", 0.5, 3.0, "stop ATR multiple"),
        ParameterBounds("target_atr", 0.5, 4.0, "target ATR multiple"),
        ParameterBounds("hold_bars", 1, 48, "max hold bars"),
        ParameterBounds("cooldown", 1, 48, "cooldown bars"),
    ],
    invalid_combinations=[
        "stop_atr_mult >= tp_atr_mult (stop above target)",
        "breakout_lookback < 12 (too short to detect compression)",
    ],
    templates=[
        FamilyTemplate(
            template_id="compression_breakout_bb_squeeze",
            description="Enter on Bollinger Band squeeze breakout",
            primary_adapters=["ta_composite", "smc_mm"],
            required_params=["bb_period"],
            default_search_space={
                "bb_period": [14, 20, 30],
                "burst_threshold": [1.0, 1.5, 2.0],
                "stop_atr_mult": [1.0, 1.5, 2.0],
            },
        ),
        FamilyTemplate(
            template_id="compression_breakout_atr_low",
            description="Enter when ATR drops below rolling percentile then expands",
            primary_adapters=["momentum_scalper", "atr_mm"],
            required_params=["vol_window", "burst_threshold"],
            default_search_space={
                "vol_window": [12, 20, 30],
                "burst_threshold": [1.2, 1.5, 2.0, 2.5],
                "hold_bars": [4, 8, 16],
            },
        ),
    ],
)

_MEAN_REVERSION = StrategyFamily(
    name="mean_reversion",
    description=(
        "Enter against recent price movement expecting reversion to a moving "
        "average or statistical mean. Typically requires spread control."
    ),
    supported_adapters=["atr_mm", "atr_mm_v2", "smc_mm", "ta_composite", "simple"],
    required_data=[],
    default_complexity_budget=4,
    per_trade_risk_min_pct=0.25,
    per_trade_risk_max_pct=0.75,
    parameter_bounds=[
        ParameterBounds("vol_window", 10, 50, "volatility estimation window"),
        ParameterBounds("band_threshold", 1.0, 3.0, "z-score / band entry threshold"),
        ParameterBounds("zscore_threshold", 1.0, 3.0, "z-score threshold alias"),
        ParameterBounds("stop_atr", 0.5, 3.0, "stop ATR multiple"),
        ParameterBounds("target_atr", 0.5, 3.0, "target ATR multiple"),
        ParameterBounds("hold_bars", 1, 48, "max hold bars"),
        ParameterBounds("atr_period", 10, 50, "ATR period"),
    ],
    invalid_combinations=[
        "stop_atr_mult >= tp_atr_mult (stop above target)",
        "band_threshold < 1.0 (entries too close to mean, no edge)",
    ],
    templates=[
        FamilyTemplate(
            template_id="mean_reversion_zscore",
            description="Enter when price z-score exceeds threshold; exit on mean cross",
            primary_adapters=["ta_composite", "atr_mm"],
            required_params=["zscore_window", "zscore_threshold"],
            default_search_space={
                "zscore_window": [15, 20, 30],
                "zscore_threshold": [1.5, 2.0, 2.5],
                "stop_atr_mult": [1.0, 1.5, 2.0],
            },
        ),
        FamilyTemplate(
            template_id="mean_reversion_mm",
            description="Market-making style mean reversion with inventory control",
            primary_adapters=["atr_mm", "atr_mm_v2"],
            required_params=["atr_period", "spread_multiplier"],
            default_search_space={
                "atr_period": [10, 14, 20],
                "spread_multiplier": [1.5, 2.5, 3.5],
                "inventory_target_base": [0.3, 0.5, 0.7],
            },
        ),
    ],
)

_REGIME_CONDITIONED_MOMENTUM = StrategyFamily(
    name="regime_conditioned_momentum",
    description=(
        "Momentum entry filtered by a detected volatility or trend regime. "
        "Only trades when the regime context supports the directional bet."
    ),
    supported_adapters=["momentum_scalper", "directional_mm", "atr_mm_v2", "ta_composite"],
    required_data=[],
    default_complexity_budget=5,
    per_trade_risk_min_pct=0.25,
    per_trade_risk_max_pct=1.0,
    parameter_bounds=[
        ParameterBounds("trend_window", 20, 200, "regime trend window"),
        ParameterBounds("trend_period", 20, 200, "regime trend period alias"),
        ParameterBounds("vol_window", 10, 50, "volatility window"),
        ParameterBounds("burst_threshold", 0.5, 4.0, "momentum entry threshold"),
        ParameterBounds("stop_atr", 0.5, 4.0, "stop ATR multiple"),
        ParameterBounds("target_atr", 0.5, 4.0, "target ATR multiple"),
        ParameterBounds("hold_bars", 1, 48, "max hold bars"),
        ParameterBounds("cooldown", 1, 48, "cooldown bars"),
    ],
    invalid_combinations=[
        "stop_atr_mult >= tp_atr_mult (stop above target)",
        "burst_threshold < 0.5 (threshold too low, triggers on noise)",
    ],
    templates=[
        FamilyTemplate(
            template_id="regime_conditioned_momentum_scalper",
            description="Short momentum bursts gated by ATR regime",
            primary_adapters=["momentum_scalper"],
            required_params=["burst_threshold", "hold_bars", "trail_atr"],
            default_search_space={
                "burst_threshold": [1.0, 1.5, 2.0, 2.5],
                "hold_bars": [4, 8, 16, 24],
                "trail_atr": [0.5, 1.0, 1.5],
            },
        ),
    ],
)

_FUNDING_DISLOCATION = StrategyFamily(
    name="funding_dislocation",
    description=(
        "Enter based on funding rate dislocations in perpetual futures. "
        "Requires funding history data. Trades the basis convergence."
    ),
    supported_adapters=["ta_composite", "directional_mm", "atr_mm"],
    required_data=["funding"],
    default_complexity_budget=4,
    per_trade_risk_min_pct=0.25,
    per_trade_risk_max_pct=0.75,
    parameter_bounds=[
        ParameterBounds("band_threshold", 1.0, 3.0, "funding z-score threshold"),
        ParameterBounds("zscore_threshold", 1.0, 3.0, "z-score threshold"),
        ParameterBounds("hold_bars", 4, 48, "minimum hold for funding convergence"),
        ParameterBounds("stop_atr", 0.5, 3.0, "stop ATR multiple"),
        ParameterBounds("target_atr", 0.5, 4.0, "target ATR multiple"),
    ],
    invalid_combinations=[
        "stop_atr_mult >= tp_atr_mult (stop above target)",
        "hold_bars < 4 (too short to collect meaningful funding)",
    ],
    templates=[
        FamilyTemplate(
            template_id="funding_dislocation_zscore",
            description="Enter when funding rate z-score exceeds threshold",
            primary_adapters=["ta_composite"],
            required_params=["funding_zscore_window", "funding_zscore_threshold"],
            default_search_space={
                "funding_zscore_threshold": [1.5, 2.0, 2.5],
                "hold_bars": [8, 16, 24],
                "stop_atr_mult": [1.0, 1.5, 2.0],
            },
        ),
    ],
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

FAMILY_REGISTRY: dict[str, StrategyFamily] = {
    "trend_continuation": _TREND_CONTINUATION,
    "trend_pullback": _TREND_PULLBACK,
    "compression_breakout": _COMPRESSION_BREAKOUT,
    "mean_reversion": _MEAN_REVERSION,
    "regime_conditioned_momentum": _REGIME_CONDITIONED_MOMENTUM,
    "funding_dislocation": _FUNDING_DISLOCATION,
}

SUPPORTED_FAMILIES = frozenset(FAMILY_REGISTRY.keys())

# Families that are explicitly not first-class in phase one
_NOT_FIRST_CLASS_PHASE_ONE = frozenset({
    "open_interest_driven",
    "liquidation_cascade",
    "order_flow_imbalance",
})


def get_family(family_name: str) -> StrategyFamily | None:
    """Return the StrategyFamily for name, or None if not registered."""
    return FAMILY_REGISTRY.get(family_name)


def is_supported_family(family_name: str) -> bool:
    return family_name in SUPPORTED_FAMILIES


def is_phase_one_unsupported(family_name: str) -> bool:
    """True when the family is known but explicitly deferred to a later phase."""
    return family_name in _NOT_FIRST_CLASS_PHASE_ONE
