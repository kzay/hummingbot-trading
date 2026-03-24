"""Fill-preset sensitivity sweep: run a backtest config across all four fill
presets (optimistic, balanced, conservative, pessimistic) and compare results.

Usage:
    PYTHONPATH=hbot python -m scripts.backtest.run_fill_preset_sweep \
        --config data/backtest_configs/bot7_pullback.yml

    # Include latency stress:
    PYTHONPATH=hbot python -m scripts.backtest.run_fill_preset_sweep \
        --config data/backtest_configs/bot7_pullback.yml --with-latency

A strategy that only profits under 'optimistic' has no real edge.
Aim for profitability at least under 'balanced', ideally 'conservative'.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from controllers.backtesting.config_loader import load_backtest_config
from controllers.backtesting.harness import BacktestHarness
from controllers.backtesting.report import save_json_report
from controllers.backtesting.types import BacktestResult

PRESETS = ["optimistic", "balanced", "conservative", "pessimistic"]

LATENCY_PROFILES = {
    "none": {"insert_latency_ms": 0, "cancel_latency_ms": 0, "latency_model": "none"},
    "fast": {"insert_latency_ms": 50, "cancel_latency_ms": 30, "latency_model": "fast"},
    "realistic": {"insert_latency_ms": 100, "cancel_latency_ms": 50, "latency_model": "realistic"},
}


def _run_single(config, preset: str, latency_name: str) -> BacktestResult | None:
    cfg = replace(config, fill_model_preset=preset)
    lat = LATENCY_PROFILES[latency_name]
    cfg = replace(
        cfg,
        insert_latency_ms=lat["insert_latency_ms"],
        cancel_latency_ms=lat["cancel_latency_ms"],
        latency_model=lat["latency_model"],
    )
    tag = f"{preset}+{latency_name}" if latency_name != "none" else preset
    print(f"\n{'='*60}")
    print(f"  Running preset: {tag}")
    print(f"{'='*60}")
    try:
        harness = BacktestHarness(cfg)
        return harness.run()
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return None


def _fmt(v: float, width: int = 8, fmt: str = ".2f") -> str:
    return f"{v:{fmt}}".rjust(width)


def _print_comparison(rows: list[tuple[str, BacktestResult]]) -> None:
    print("\n")
    print("=" * 90)
    print("  FILL-PRESET SENSITIVITY COMPARISON")
    print("=" * 90)
    header = (
        f"  {'Preset':<24} {'Return%':>8} {'Sharpe':>8} {'MaxDD%':>8} "
        f"{'Fills':>7} {'WinRate':>8} {'PF':>7} {'Fees':>10} {'Slip bps':>9}"
    )
    print(header)
    print("-" * 90)

    for tag, r in rows:
        print(
            f"  {tag:<24} "
            f"{_fmt(r.total_return_pct)} "
            f"{_fmt(r.sharpe_ratio)} "
            f"{_fmt(r.max_drawdown_pct)} "
            f"{r.fill_count:>7} "
            f"{_fmt(r.win_rate * 100, fmt='.1f')}% "
            f"{_fmt(r.profit_factor)} "
            f"{r.total_fees!s:>10} "
            f"{_fmt(r.avg_slippage_bps)}"
        )

    print("=" * 90)

    best = rows[0][1]
    worst = rows[-1][1]
    if best.sharpe_ratio > 0 and worst.sharpe_ratio > 0:
        degradation = 1 - worst.sharpe_ratio / best.sharpe_ratio
        print(f"\n  Sharpe degradation (best → worst): {degradation:.0%}")
    elif best.sharpe_ratio > 0 and worst.sharpe_ratio <= 0:
        print("\n  WARNING: Strategy unprofitable under worst preset!")

    balanced_row = next((r for tag, r in rows if "balanced" in tag), None)
    if balanced_row and balanced_row.sharpe_ratio < 0.5:
        print("  WARNING: Sharpe < 0.5 under balanced preset — weak edge.")
    elif balanced_row and balanced_row.sharpe_ratio >= 1.0:
        print("  GOOD: Sharpe >= 1.0 under balanced preset.")

    conservative_row = next((r for tag, r in rows if "conservative" in tag), None)
    if conservative_row and conservative_row.total_return_pct > 0:
        print("  GOOD: Strategy profitable under conservative fill model.")
    elif conservative_row:
        print("  CAUTION: Strategy unprofitable under conservative fills.")

    print()


def main() -> None:
    ap = argparse.ArgumentParser(description="Fill-preset sensitivity sweep")
    ap.add_argument("--config", required=True, help="YAML backtest config file")
    ap.add_argument(
        "--with-latency", action="store_true",
        help="Also test with realistic latency",
    )
    ap.add_argument("--output-dir", default="", help="Save JSON reports here")
    ap.add_argument("--presets", default="", help="Comma-separated subset of presets to run")
    args = ap.parse_args()

    config = load_backtest_config(args.config)
    presets = args.presets.split(",") if args.presets else PRESETS
    latency_modes = ["none"]
    if args.with_latency:
        latency_modes.append("realistic")

    results: list[tuple[str, BacktestResult]] = []

    for latency_name in latency_modes:
        for preset in presets:
            tag = f"{preset}+{latency_name}" if latency_name != "none" else preset
            result = _run_single(config, preset, latency_name)
            if result is not None:
                results.append((tag, result))

                if args.output_dir:
                    out_dir = Path(args.output_dir)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    save_json_report(result, out_dir / f"preset_{tag}.json")

    if results:
        _print_comparison(results)
    else:
        print("No successful runs.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
