"""CLI entrypoint for running a single backtest from a config file.

Used by the backtest API to spawn worker subprocesses.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from decimal import Decimal
from pathlib import Path

import yaml

from controllers.backtesting.harness import BacktestHarness
from controllers.backtesting.types import BacktestConfig, DataSourceConfig, SynthesisConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s  %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _default_data_catalog_dir(ds_raw: dict) -> str:
    """Resolve catalog base dir (contains catalog.json + exchange/...).

    Prefer YAML ``catalog_dir``, then env ``BACKTEST_CATALOG_DIR``, then
    ``HB_DATA_ROOT``.  Falls back to ``data/historical`` (cwd-relative) with
    a legacy check for ``hbot/data/historical`` when running outside ``hbot/``.
    """
    if ds_raw.get("catalog_dir"):
        return str(ds_raw["catalog_dir"])
    env = os.environ.get("BACKTEST_CATALOG_DIR", "").strip()
    if env:
        return env
    hr = os.environ.get("HB_DATA_ROOT", "").strip()
    if hr:
        return str(Path(hr) / "historical")
    if Path("data/historical").exists():
        return "data/historical"
    if Path("hbot/data/historical").exists():
        return "hbot/data/historical"
    return "data/historical"


def _parse_config(path: str, overrides: dict[str, str]) -> BacktestConfig:
    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    for key, val in overrides.items():
        raw[key] = val

    ds_raw = raw.get("data_source", {})
    ds = DataSourceConfig(
        exchange=ds_raw.get("exchange", "bitget"),
        pair=ds_raw.get("pair", "BTC-USDT"),
        instrument_type=ds_raw.get("instrument_type", "perp"),
        resolution=ds_raw.get("resolution", "1m"),
        start_date=ds_raw.get("start_date", ""),
        end_date=ds_raw.get("end_date", ""),
        data_path=ds_raw.get("data_path", ""),
        catalog_dir=_default_data_catalog_dir(ds_raw),
    )

    synth_raw = raw.get("synthesis", {})
    synthesis = SynthesisConfig(
        base_spread_bps=Decimal(str(synth_raw.get("base_spread_bps", synth_raw.get("spread_bps", "5.0")))),
        vol_spread_mult=Decimal(str(synth_raw.get("vol_spread_mult", "1.0"))),
        depth_levels=synth_raw.get("depth_levels", 10),
        depth_decay=Decimal(str(synth_raw.get("depth_decay", "0.70"))),
        base_depth_size=Decimal(str(synth_raw.get("base_depth_size", synth_raw.get("depth_qty_per_level", "0.5")))),
        steps_per_bar=synth_raw.get("steps_per_bar", 4),
    )

    return BacktestConfig(
        strategy_class=raw.get("strategy_class", ""),
        strategy_config=raw.get("strategy_config", {}),
        data_source=ds,
        initial_equity=Decimal(str(raw.get("initial_equity", "500"))),
        fill_model=raw.get("fill_model", "latency_aware"),
        fill_model_preset=raw.get("fill_model_preset", "balanced"),
        seed=int(raw.get("seed", 42)),
        leverage=int(raw.get("leverage", 1)),
        step_interval_s=int(raw.get("step_interval_s", 60)),
        warmup_bars=int(raw.get("warmup_bars", 60)),
        synthesis=synthesis,
        insert_latency_ms=int(raw.get("insert_latency_ms", 0)),
        cancel_latency_ms=int(raw.get("cancel_latency_ms", 0)),
        latency_model=raw.get("latency_model", "none"),
        output_dir=raw.get("output_dir", "reports/backtest"),
        run_id=raw.get("run_id", ""),
        progress_dir=raw.get("progress_dir", ""),
    )


def _result_to_dict(result) -> dict:
    """Serialize BacktestResult to a JSON-safe dict."""
    return {
        "total_return_pct": result.total_return_pct,
        "sharpe_ratio": result.sharpe_ratio,
        "sortino_ratio": result.sortino_ratio,
        "calmar_ratio": result.calmar_ratio,
        "max_drawdown_pct": result.max_drawdown_pct,
        "max_drawdown_duration_days": result.max_drawdown_duration_days,
        "cagr_pct": result.cagr_pct,
        "fill_count": result.fill_count,
        "closed_trade_count": result.closed_trade_count,
        "winning_trade_count": result.winning_trade_count,
        "losing_trade_count": result.losing_trade_count,
        "order_count": result.order_count,
        "total_ticks": result.total_ticks,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "gross_profit_quote": str(result.gross_profit_quote),
        "gross_loss_quote": str(result.gross_loss_quote),
        "avg_win_quote": str(result.avg_win_quote),
        "avg_loss_quote": str(result.avg_loss_quote),
        "expectancy_quote": str(result.expectancy_quote),
        "realized_net_pnl_quote": str(result.realized_net_pnl_quote),
        "residual_pnl_quote": str(result.residual_pnl_quote),
        "total_fees": str(result.total_fees),
        "maker_fill_ratio": result.maker_fill_ratio,
        "fee_drag_pct": result.fee_drag_pct,
        "avg_slippage_bps": result.avg_slippage_bps,
        "spread_capture_efficiency": result.spread_capture_efficiency,
        "inventory_half_life_minutes": result.inventory_half_life_minutes,
        "terminal_position_base": str(result.terminal_position_base),
        "terminal_position_notional": str(result.terminal_position_notional),
        "terminal_mark_price": str(result.terminal_mark_price),
        "run_duration_s": result.run_duration_s,
        "warnings": result.warnings,
        "equity_curve": [
            {
                "date": s.date,
                "equity": str(s.equity),
                "drawdown_pct": str(s.drawdown_pct),
                "daily_return_pct": str(s.daily_return_pct),
            }
            for s in (result.equity_curve or [])
        ],
        "config": result.config,
    }


def main():
    parser = argparse.ArgumentParser(description="Run a single backtest")
    parser.add_argument("--config", required=True, help="Path to YAML config")
    parser.add_argument("--output", default="", help="Path to write JSON report")
    parser.add_argument("--progress-dir", default="", help="Directory for progress.json")
    parser.add_argument("--override", action="append", default=[], help="key=value overrides")
    args = parser.parse_args()

    overrides = {}
    for ov in args.override:
        if "=" in ov:
            k, v = ov.split("=", 1)
            overrides[k.strip()] = v.strip()

    config = _parse_config(args.config, overrides)
    if args.progress_dir:
        config.progress_dir = args.progress_dir

    logger.info("Starting backtest: %s", config.strategy_class)
    harness = BacktestHarness(config)
    result = harness.run()

    output_path = args.output or f"{config.output_dir}/{config.run_id or 'result'}.json"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(_result_to_dict(result), indent=2, default=str))
    logger.info("Report written to %s", output_path)


if __name__ == "__main__":
    main()
