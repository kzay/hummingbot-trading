"""Declarative adapter registry for the backtesting harness.

Maps ``adapter_mode`` strings to lazy-importable adapter classes and their
config types.  Provides a generic ``hydrate_config()`` that introspects
dataclass field defaults to convert raw YAML values into the correct
Python type (``Decimal``, ``int``, ``bool``, ``str``, ``float``).

Adding a new adapter only requires one entry in ``ADAPTER_REGISTRY``
and the adapter module itself — no changes to ``harness.py``.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

_TRUTHY = frozenset({"true", "1", "yes", "on"})
_FALSY = frozenset({"false", "0", "no", "off"})


@dataclass(frozen=True)
class AdapterEntry:
    """Registry entry for a single adapter mode."""

    module_path: str
    adapter_class: str
    config_class: str
    decimal_attrs: tuple[str, ...] = ()
    int_attrs: tuple[str, ...] = ()
    bool_attrs: tuple[str, ...] = ()
    is_frozen: bool = False


def _safe_bool(value: Any) -> bool:
    """Convert a value to bool, safely handling string ``"false"``."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.lower().strip()
        if low in _TRUTHY:
            return True
        if low in _FALSY:
            return False
        raise ValueError(f"Cannot convert {value!r} to bool")
    return bool(value)


def hydrate_config(config_obj: Any, raw: dict[str, Any], entry: AdapterEntry) -> Any:
    """Hydrate a config dataclass from raw YAML values.

    Uses the entry's explicit attribute lists when provided (preserving the
    exact behavior of the original per-adapter hydration code).  Falls back
    to introspecting the config's dataclass field defaults.

    Returns the (mutated) config object.
    """
    has_explicit_lists = bool(entry.decimal_attrs or entry.int_attrs or entry.bool_attrs)

    if has_explicit_lists:
        _hydrate_explicit(config_obj, raw, entry)
    else:
        _hydrate_introspect(config_obj, raw, entry)

    return config_obj


def _set(obj: Any, attr: str, val: Any, frozen: bool) -> None:
    if frozen:
        object.__setattr__(obj, attr, val)
    else:
        setattr(obj, attr, val)


def _hydrate_explicit(config_obj: Any, raw: dict[str, Any], entry: AdapterEntry) -> None:
    """Hydrate using explicit type lists — mirrors original ``_build_adapter``."""
    frozen = entry.is_frozen
    for attr in entry.decimal_attrs:
        if attr in raw:
            _set(config_obj, attr, Decimal(str(raw[attr])), frozen)
    for attr in entry.int_attrs:
        if attr in raw:
            _set(config_obj, attr, int(raw[attr]), frozen)
    for attr in entry.bool_attrs:
        if attr in raw:
            _set(config_obj, attr, _safe_bool(raw[attr]), frozen)


def _hydrate_introspect(config_obj: Any, raw: dict[str, Any], entry: AdapterEntry) -> None:
    """Hydrate by inspecting the config dataclass default value types."""
    frozen = entry.is_frozen
    for attr in raw:
        if not hasattr(config_obj, attr):
            continue
        current = getattr(config_obj, attr)
        val = raw[attr]
        if isinstance(current, Decimal):
            _set(config_obj, attr, Decimal(str(val)), frozen)
        elif isinstance(current, bool):
            _set(config_obj, attr, _safe_bool(val), frozen)
        elif isinstance(current, int):
            _set(config_obj, attr, int(val), frozen)
        elif isinstance(current, float):
            _set(config_obj, attr, float(val), frozen)
        else:
            _set(config_obj, attr, val, frozen)


# ---------------------------------------------------------------------------
# Registry — all adapter modes
# ---------------------------------------------------------------------------

ADAPTER_REGISTRY: dict[str, AdapterEntry] = {
    "atr_mm": AdapterEntry(
        module_path="controllers.backtesting.atr_mm_adapter",
        adapter_class="AtrMMAdapter",
        config_class="AtrMMConfig",
        decimal_attrs=(
            "spread_atr_mult", "min_spread_pct", "max_spread_pct",
            "base_size_pct", "max_inventory_pct", "inventory_skew_mult",
            "inventory_size_penalty", "urgency_spread_reduction",
            "max_daily_loss_pct", "max_drawdown_pct", "level_spacing",
        ),
        int_attrs=(
            "atr_period", "min_warmup_bars", "levels",
            "inventory_age_decay_minutes",
        ),
    ),
    "atr_mm_v2": AdapterEntry(
        module_path="controllers.backtesting.atr_mm_v2_adapter",
        adapter_class="AtrMMv2Adapter",
        config_class="AtrMMv2Config",
        decimal_attrs=(
            "spread_atr_mult", "min_spread_pct", "max_spread_pct",
            "base_size_pct", "max_inventory_pct", "inventory_skew_mult",
            "inventory_size_penalty", "urgency_spread_reduction",
            "max_daily_loss_pct", "max_drawdown_pct",
            "level_spacing", "vol_sizing_min_mult", "vol_sizing_max_mult",
            "htf_trend_filter", "htf_contra_size_mult",
        ),
        int_attrs=(
            "atr_period", "min_warmup_bars", "levels",
            "inventory_age_decay_minutes", "vol_sizing_lookback",
            "htf_bars", "htf_ema_period",
        ),
        bool_attrs=("vol_sizing_enabled", "htf_enabled"),
    ),
    "smc_mm": AdapterEntry(
        module_path="controllers.backtesting.smc_mm_adapter",
        adapter_class="SmcMMAdapter",
        config_class="SmcMMConfig",
        decimal_attrs=(
            "spread_atr_mult", "min_spread_pct", "max_spread_pct",
            "base_size_pct", "max_inventory_pct", "inventory_skew_mult",
            "inventory_size_penalty", "urgency_spread_reduction",
            "max_daily_loss_pct", "max_drawdown_pct",
            "level_spacing", "fvg_spread_bias",
            "bb_band_walk_threshold", "bb_contraction_percentile",
            "bb_walk_size_mult", "bb_contract_size_mult",
        ),
        int_attrs=(
            "atr_period", "min_warmup_bars", "levels",
            "inventory_age_decay_minutes", "fvg_decay_bars",
            "bb_period", "bb_width_lookback",
        ),
        bool_attrs=("fvg_enabled", "bb_enabled", "ict_shadow_enabled"),
    ),
    "combo_mm": AdapterEntry(
        module_path="controllers.backtesting.combo_mm_adapter",
        adapter_class="ComboMMAdapter",
        config_class="ComboMMConfig",
        decimal_attrs=(
            "spread_atr_mult", "min_spread_pct", "max_spread_pct",
            "base_size_pct", "max_inventory_pct", "inventory_skew_mult",
            "inventory_size_penalty", "urgency_spread_reduction",
            "max_daily_loss_pct", "max_drawdown_pct", "level_spacing",
            "fvg_spread_bias", "micro_body_threshold", "micro_spread_bias",
            "fill_feedback_spread_bias",
            "adaptive_inv_vol_low_mult", "adaptive_inv_vol_high_mult",
            "level_size_growth", "momentum_spread_widen",
        ),
        int_attrs=(
            "atr_period", "min_warmup_bars", "levels",
            "inventory_age_decay_minutes", "fvg_decay_bars",
            "micro_lookback", "fill_feedback_lookback", "momentum_lookback",
        ),
        bool_attrs=(
            "fvg_enabled", "micro_enabled", "fill_feedback_enabled",
            "adaptive_inventory_enabled", "level_sizing_enabled",
            "momentum_guard_enabled",
        ),
    ),
    "pullback": AdapterEntry(
        module_path="controllers.backtesting.pullback_adapter",
        adapter_class="BacktestPullbackAdapter",
        config_class="PullbackAdapterConfig",
    ),
    "pullback_v2": AdapterEntry(
        module_path="controllers.backtesting.pullback_adapter_v2",
        adapter_class="BacktestPullbackAdapterV2",
        config_class="PullbackV2Config",
    ),
    "momentum_scalper": AdapterEntry(
        module_path="controllers.backtesting.momentum_scalper_adapter",
        adapter_class="MomentumScalperAdapter",
        config_class="MomentumScalperConfig",
    ),
    "directional_mm": AdapterEntry(
        module_path="controllers.backtesting.directional_mm_adapter",
        adapter_class="DirectionalMMAdapter",
        config_class="DirectionalMMConfig",
    ),
    "simple": AdapterEntry(
        module_path="controllers.backtesting.simple_adapter",
        adapter_class="SimpleBacktestAdapter",
        config_class="SimpleAdapterConfig",
        decimal_attrs=(
            "high_vol_band_pct", "shock_drift_pct",
            "max_base_pct", "max_daily_loss_pct", "max_drawdown_pct",
            "spread_mult", "size_mult",
        ),
        int_attrs=("ema_period", "atr_period", "min_warmup_bars"),
    ),
    "ta_composite": AdapterEntry(
        module_path="controllers.backtesting.ta_composite_adapter",
        adapter_class="TaCompositeAdapter",
        config_class="TaCompositeConfig",
    ),
}

_RUNTIME_ENTRY = AdapterEntry(
    module_path="controllers.backtesting.runtime_adapter",
    adapter_class="BacktestRuntimeAdapter",
    config_class="RuntimeAdapterConfig",
    decimal_attrs=(
        "high_vol_band_pct", "turnover_cap_x", "maker_fee_pct",
    ),
    int_attrs=("ema_period", "atr_period", "min_warmup_bars"),
    bool_attrs=("is_perp",),
)


def build_adapter(
    config: Any,
    desk: Any,
    instrument_id: Any,
    instrument_spec: Any,
    *,
    load_strategy_fn: Any = None,
) -> Any:
    """Build the tick adapter for a backtest run.

    For ``adapter_mode="runtime"``, supply ``load_strategy_fn`` (typically
    ``harness._load_strategy``).
    """
    sc = config.strategy_config
    adapter_mode = sc.get("adapter_mode", "simple")

    if adapter_mode == "runtime":
        return _build_runtime_adapter(config, desk, instrument_id, instrument_spec, sc, load_strategy_fn)

    entry = ADAPTER_REGISTRY.get(adapter_mode)
    if entry is None:
        raise ValueError(
            f"Unknown adapter_mode={adapter_mode!r}. "
            f"Available: {sorted(ADAPTER_REGISTRY.keys())}"
        )

    module = importlib.import_module(entry.module_path)
    adapter_cls = getattr(module, entry.adapter_class)
    config_cls = getattr(module, entry.config_class)

    cfg = config_cls()
    hydrate_config(cfg, sc, entry)

    return adapter_cls(
        desk=desk,
        instrument_id=instrument_id,
        instrument_spec=instrument_spec,
        config=cfg,
    )


def _build_runtime_adapter(
    config: Any,
    desk: Any,
    instrument_id: Any,
    instrument_spec: Any,
    sc: dict[str, Any],
    load_strategy_fn: Any,
) -> Any:
    """Build the runtime adapter — special case with strategy loading."""
    from controllers.backtesting.runtime_adapter import (
        BacktestRuntimeAdapter,
        RuntimeAdapterConfig,
    )

    strategy = load_strategy_fn(config.strategy_class, sc)
    adapter_cfg = RuntimeAdapterConfig()

    hydrate_config(adapter_cfg, sc, _RUNTIME_ENTRY)

    if "regime_specs" in sc:
        adapter_cfg.regime_specs = sc["regime_specs"]

    return BacktestRuntimeAdapter(
        strategy=strategy,
        desk=desk,
        instrument_id=instrument_id,
        instrument_spec=instrument_spec,
        config=adapter_cfg,
    )
