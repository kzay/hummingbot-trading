"""Declarative strategy registry for the v3 trading desk.

Mirrors the backtesting adapter_registry pattern. Adding a new strategy
requires only a signal module and one entry here.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any

from controllers.runtime.v3.protocols import StrategySignalSource

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StrategyEntry:
    """Registration metadata for a production strategy."""

    module_path: str
    """Importable module path (e.g. 'controllers.bots.bot7.pullback_signals')."""

    signal_class: str
    """Class name implementing StrategySignalSource."""

    config_class: str = ""
    """Optional config dataclass name in the same module."""

    execution_family: str = "mm_grid"
    """Which ExecutionAdapter to use: 'mm_grid', 'directional', 'hybrid'."""

    risk_profile: str = "moderate"
    """Risk profile name for DeskRiskGate configuration."""

    decimal_attrs: tuple[str, ...] = ()
    """Config attributes that should be hydrated as Decimal."""

    int_attrs: tuple[str, ...] = ()
    """Config attributes that should be hydrated as int."""

    bool_attrs: tuple[str, ...] = ()
    """Config attributes that should be hydrated as bool."""


# ── Registry ─────────────────────────────────────────────────────────
# Entries are added as bots are migrated (Phases 9-12).
# During the shim phase, legacy bots don't appear here.

STRATEGY_REGISTRY: dict[str, StrategyEntry] = {
    # Phase 9: Bot1 migration
    "bot1_baseline": StrategyEntry(
        module_path="controllers.bots.bot1.baseline_signals",
        signal_class="BaselineSignalSource",
        config_class="BaselineConfig",
        execution_family="mm_grid",
        risk_profile="conservative",
        decimal_attrs=("min_spread_pct", "quote_size_pct"),
        int_attrs=("levels",),
        bool_attrs=("edge_gate_enabled",),
    ),

    # Phase 10: Bot7 migration
    "bot7_pullback": StrategyEntry(
        module_path="controllers.bots.bot7.pullback_signal_source",
        signal_class="PullbackSignalSource",
        config_class="PullbackConfig",
        execution_family="directional",
        risk_profile="moderate",
        decimal_attrs=(
            "rsi_long_min", "rsi_long_max", "rsi_short_min", "rsi_short_max",
            "adx_min", "adx_max", "pullback_zone_pct", "zone_atr_mult",
            "per_leg_risk_pct", "grid_spacing_atr_mult",
            "sl_atr_mult", "tp_atr_mult", "min_basis_slope_pct",
            "signal_score_threshold", "target_net_base_pct",
        ),
        int_attrs=("bb_period", "rsi_period", "adx_period", "atr_period", "max_grid_legs", "trend_sma_period"),
        bool_attrs=("session_filter_enabled",),
    ),

    # Phase 11: Bot5 migration
    "bot5_ift_jota": StrategyEntry(
        module_path="controllers.bots.bot5.flow_signal_source",
        signal_class="FlowSignalSource",
        config_class="FlowConfig",
        execution_family="hybrid",
        risk_profile="moderate",
        decimal_attrs=(
            "imbalance_threshold", "trend_threshold_pct",
            "bias_threshold", "directional_threshold",
            "target_net_base_pct", "max_base_pct",
        ),
    ),

    # Phase 12: Bot6 migration
    "bot6_cvd_divergence": StrategyEntry(
        module_path="controllers.bots.bot6.cvd_signal_source",
        signal_class="CvdSignalSource",
        config_class="CvdConfig",
        execution_family="directional",
        risk_profile="moderate",
        decimal_attrs=(
            "adx_threshold", "divergence_threshold_pct",
            "target_net_base_pct", "dynamic_size_floor_mult",
            "dynamic_size_cap_mult", "per_leg_risk_pct", "spread_pct",
        ),
        int_attrs=("sma_fast_period", "sma_slow_period", "adx_period", "signal_score_threshold"),
    ),

    # Bot7 ML signal-driven strategy
    "bot7_ml_signal": StrategyEntry(
        module_path="controllers.bots.bot7.ml_signal_source",
        signal_class="MlSignalSource",
        config_class="MlSignalConfig",
        execution_family="hybrid",
        risk_profile="moderate",
        decimal_attrs=(
            "base_size_quote", "base_spread_pct", "spread_step_pct",
            "target_net_base_pct",
        ),
        int_attrs=("max_levels",),
        bool_attrs=("use_ml_sizing",),
    ),
}


# ── Module cache ─────────────────────────────────────────────────────

_module_cache: dict[str, Any] = {}


def _import_module(module_path: str) -> Any:
    """Lazy import with caching."""
    if module_path not in _module_cache:
        _module_cache[module_path] = importlib.import_module(module_path)
    return _module_cache[module_path]


# ── Factory ──────────────────────────────────────────────────────────

def load_strategy(
    name: str,
    config: dict[str, Any] | None = None,
) -> StrategySignalSource:
    """Instantiate a strategy signal source by registry name.

    Args:
        name: Key in STRATEGY_REGISTRY.
        config: Optional config dict — hydrated into the config dataclass
                if the entry specifies one.

    Returns:
        An instance satisfying the StrategySignalSource protocol.

    Raises:
        KeyError: If name not in registry.
        ImportError: If module cannot be loaded.
        AttributeError: If class not found in module.
    """
    if name not in STRATEGY_REGISTRY:
        available = ", ".join(sorted(STRATEGY_REGISTRY.keys())) or "(none)"
        raise KeyError(
            f"Strategy '{name}' not in registry. Available: {available}"
        )

    entry = STRATEGY_REGISTRY[name]
    mod = _import_module(entry.module_path)
    signal_cls = getattr(mod, entry.signal_class)

    # Hydrate config if specified
    if entry.config_class and config:
        config_cls = getattr(mod, entry.config_class)
        cfg_instance = _hydrate_config(config_cls, config, entry)
        return signal_cls(cfg_instance)

    if config:
        return signal_cls(config)

    return signal_cls()


def _hydrate_config(
    config_cls: type,
    raw: dict[str, Any],
    entry: StrategyEntry,
) -> Any:
    """Convert raw dict values to typed config dataclass."""
    from decimal import Decimal

    hydrated = {}
    for key, val in raw.items():
        if key in entry.decimal_attrs:
            hydrated[key] = Decimal(str(val))
        elif key in entry.int_attrs:
            hydrated[key] = int(val)
        elif key in entry.bool_attrs:
            hydrated[key] = bool(val)
        else:
            hydrated[key] = val

    # Only pass keys that the config class accepts
    import dataclasses
    if dataclasses.is_dataclass(config_cls):
        valid_fields = {f.name for f in dataclasses.fields(config_cls)}
        hydrated = {k: v for k, v in hydrated.items() if k in valid_fields}

    return config_cls(**hydrated)


def get_entry(name: str) -> StrategyEntry:
    """Get registry entry by name. Raises KeyError if not found."""
    return STRATEGY_REGISTRY[name]


def list_strategies() -> list[str]:
    """Return sorted list of registered strategy names."""
    return sorted(STRATEGY_REGISTRY.keys())


def clear_module_cache() -> None:
    """Clear the lazy import cache (useful for testing)."""
    _module_cache.clear()


__all__ = [
    "STRATEGY_REGISTRY",
    "StrategyEntry",
    "clear_module_cache",
    "get_entry",
    "list_strategies",
    "load_strategy",
]
