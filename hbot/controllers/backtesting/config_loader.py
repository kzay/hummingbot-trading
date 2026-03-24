"""YAML configuration loader for backtesting engine.

Loads and validates YAML configs into BacktestConfig, SweepConfig, and
WalkForwardConfig typed dataclasses.  Provides default-filling for optional
fields and early validation of required fields.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from controllers.backtesting.types import (
    BacktestConfig,
    DataSourceConfig,
    ParamSpace,
    SweepConfig,
    SynthesisConfig,
    WalkForwardConfig,
)

logger = logging.getLogger(__name__)

_REQUIRED_BACKTEST_FIELDS = ["strategy_class", "data_source"]


# ---------------------------------------------------------------------------
# Backtest config
# ---------------------------------------------------------------------------

def load_backtest_config(path: str | Path) -> BacktestConfig:
    """Load a single-run backtest config from YAML."""
    raw = _load_yaml(path)
    return _parse_backtest_config(raw)


def _parse_backtest_config(raw: dict[str, Any]) -> BacktestConfig:
    """Parse a raw dict into a BacktestConfig."""
    for field in _REQUIRED_BACKTEST_FIELDS:
        if field not in raw:
            raise ValueError(f"Missing required field: {field}")

    ds_raw = raw.get("data_source", {})
    synth_raw = raw.get("synthesis", {})

    additional = [
        _parse_data_source(d) for d in raw.get("additional_instruments", [])
    ]

    return BacktestConfig(
        strategy_class=raw["strategy_class"],
        strategy_config=raw.get("strategy_config", {}),
        data_source=_parse_data_source(ds_raw),
        initial_equity=Decimal(str(raw.get("initial_equity", "500"))),
        fill_model=raw.get("fill_model", "latency_aware"),
        fill_model_preset=raw.get("fill_model_preset", "balanced"),
        seed=raw.get("seed", 42),
        leverage=raw.get("leverage", 1),
        step_interval_s=raw.get("step_interval_s", 60),
        warmup_bars=raw.get("warmup_bars", 60),
        synthesis=_parse_synthesis(synth_raw),
        additional_instruments=additional,
        insert_latency_ms=raw.get("insert_latency_ms", 0),
        cancel_latency_ms=raw.get("cancel_latency_ms", 0),
        latency_model=raw.get("latency_model", "none"),
        output_dir=raw.get("output_dir", "reports/backtest"),
        run_id=raw.get("run_id", ""),
        progress_dir=raw.get("progress_dir", ""),
    )


def _parse_data_source(raw: dict[str, Any]) -> DataSourceConfig:
    return DataSourceConfig(
        exchange=raw.get("exchange", "bitget"),
        pair=raw.get("pair", "BTC-USDT"),
        resolution=raw.get("resolution", "1m"),
        start_date=raw.get("start_date", ""),
        end_date=raw.get("end_date", ""),
        instrument_type=raw.get("instrument_type", "perp"),
        data_path=raw.get("data_path", ""),
        catalog_dir=raw.get("catalog_dir", "data/historical"),
    )


def _parse_synthesis(raw: dict[str, Any]) -> SynthesisConfig:
    if not raw:
        return SynthesisConfig()
    return SynthesisConfig(
        base_spread_bps=Decimal(str(raw.get("base_spread_bps", "5.0"))),
        vol_spread_mult=Decimal(str(raw.get("vol_spread_mult", "1.0"))),
        depth_levels=raw.get("depth_levels", 5),
        depth_decay=Decimal(str(raw.get("depth_decay", "0.70"))),
        base_depth_size=Decimal(str(raw.get("base_depth_size", "1.0"))),
        steps_per_bar=raw.get("steps_per_bar", 1),
        seed=raw.get("seed", 42),
    )


# ---------------------------------------------------------------------------
# Sweep config
# ---------------------------------------------------------------------------

def load_sweep_config(path: str | Path) -> SweepConfig:
    """Load a parameter sweep config from YAML."""
    raw = _load_yaml(path)

    base_raw = raw.get("base_config", raw)  # Allow flat or nested
    base_config = _parse_backtest_config(base_raw)

    spaces_raw = raw.get("param_spaces", [])
    param_spaces = [_parse_param_space(s) for s in spaces_raw]

    return SweepConfig(
        base_config=base_config,
        param_spaces=param_spaces,
        sweep_mode=raw.get("sweep_mode", "grid"),
        n_samples=raw.get("n_samples", 50),
        objective=raw.get("objective", "sharpe_ratio"),
        workers=raw.get("workers", 0),
        seed=raw.get("seed", 42),
    )


def _parse_param_space(raw: dict[str, Any]) -> ParamSpace:
    return ParamSpace(
        name=raw["name"],
        mode=raw.get("mode", "grid"),
        values=raw.get("values", []),
        min_val=raw.get("min_val", 0.0),
        max_val=raw.get("max_val", 0.0),
        step=raw.get("step", 0.0),
        num_points=raw.get("num_points", 0),
    )


# ---------------------------------------------------------------------------
# Walk-forward config
# ---------------------------------------------------------------------------

def load_walkforward_config(path: str | Path) -> WalkForwardConfig:
    """Load a walk-forward validation config from YAML.

    Expected YAML layout::

        sweep_config:
            base_config:
                strategy_class: ...
                data_source: ...
            param_spaces: [...]
            sweep_mode: grid
        window_mode: anchored
        train_ratio: 0.70
        ...
    """
    raw = _load_yaml(path)

    sweep_raw = raw.get("sweep_config", raw)
    base_raw = sweep_raw.get("base_config", sweep_raw)
    base_config = _parse_backtest_config(base_raw)
    spaces_raw = sweep_raw.get("param_spaces", [])
    param_spaces = [_parse_param_space(s) for s in spaces_raw]

    sweep_config = SweepConfig(
        base_config=base_config,
        param_spaces=param_spaces,
        sweep_mode=sweep_raw.get("sweep_mode", "grid"),
        n_samples=sweep_raw.get("n_samples", 50),
        objective=sweep_raw.get("objective", "sharpe_ratio"),
        workers=sweep_raw.get("workers", 0),
        seed=sweep_raw.get("seed", 42),
    )

    return WalkForwardConfig(
        sweep_config=sweep_config,
        window_mode=raw.get("window_mode", "anchored"),
        train_ratio=raw.get("train_ratio", 0.70),
        min_train_days=raw.get("min_train_days", 30),
        min_test_days=raw.get("min_test_days", 7),
        n_windows=raw.get("n_windows", 0),
        strategy_type=raw.get("strategy_type", "mm"),
        block_bootstrap_replications=raw.get("block_bootstrap_replications", 1000),
        block_size_minutes=raw.get("block_size_minutes", 30),
        monte_carlo_seed=raw.get("monte_carlo_seed", 42),
        fee_stress_multipliers=raw.get("fee_stress_multipliers", [1.0, 1.5, 2.0]),
        stressed_maker_ratio=raw.get("stressed_maker_ratio", 0.60),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: str | Path) -> dict[str, Any]:
    """Load and return a YAML file as a dict."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML mapping, got {type(data)}")
    return data
