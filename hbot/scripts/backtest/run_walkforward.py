"""CLI: Run walk-forward validation with overfitting prevention suite.

Usage:
    python -m scripts.backtest.run_walkforward --config data/backtest_configs/bot1_walkforward.yml
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Run walk-forward validation")
    ap.add_argument("--config", required=True, help="YAML walk-forward config file")
    ap.add_argument("--output", default="", help="Output JSON path for results")
    args = ap.parse_args()

    from decimal import Decimal

    import yaml

    from controllers.backtesting.types import (
        BacktestConfig,
        DataSourceConfig,
        ParamSpace,
        SweepConfig,
        WalkForwardConfig,
    )
    from controllers.backtesting.walkforward import WalkForwardRunner

    with open(args.config) as f:
        raw = yaml.safe_load(f)

    # Parse sweep config (same as run_sweep)
    sweep_raw = raw.get("sweep_config", {})
    base_raw = sweep_raw.get("base_config", {})
    ds_raw = base_raw.get("data_source", {})

    base_config = BacktestConfig(
        strategy_class=base_raw.get("strategy_class", ""),
        strategy_config=base_raw.get("strategy_config", {}),
        data_source=DataSourceConfig(**ds_raw) if ds_raw else DataSourceConfig(),
        initial_equity=Decimal(str(base_raw.get("initial_equity", "500"))),
        fill_model=base_raw.get("fill_model", "latency_aware"),
        seed=base_raw.get("seed", 42),
        step_interval_s=base_raw.get("step_interval_s", 60),
        warmup_bars=base_raw.get("warmup_bars", 60),
    )

    spaces_raw = sweep_raw.get("param_spaces", [])
    param_spaces = [
        ParamSpace(
            name=s["name"], mode=s.get("mode", "grid"),
            values=s.get("values", []),
            min_val=s.get("min_val", 0.0), max_val=s.get("max_val", 0.0),
            step=s.get("step", 0.0), num_points=s.get("num_points", 0),
        )
        for s in spaces_raw
    ]

    sweep_config = SweepConfig(
        base_config=base_config,
        param_spaces=param_spaces,
        sweep_mode=sweep_raw.get("sweep_mode", "grid"),
        n_samples=sweep_raw.get("n_samples", 20),
        objective=sweep_raw.get("objective", "sharpe_ratio"),
        workers=sweep_raw.get("workers", 0),
        seed=sweep_raw.get("seed", 42),
    )

    wf_config = WalkForwardConfig(
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

    runner = WalkForwardRunner(wf_config)
    result = runner.run()

    # Print summary
    print("\n=== Walk-Forward Validation Results ===\n")
    print(f"Windows:             {len(result.windows)}")
    print(f"Mean IS Sharpe:      {result.mean_is_sharpe:.3f}")
    print(f"Mean OOS Sharpe:     {result.mean_oos_sharpe:.3f}")
    print(f"OOS/IS Ratio:        {result.oos_degradation_ratio:.3f} (threshold: {result.oos_threshold:.2f})")
    print(f"Deflated Sharpe:     {result.deflated_sharpe:.3f} (p={result.dsr_pvalue:.3f}, trials={result.dsr_n_trials})")
    print(f"Bootstrap %ile:      {result.bootstrap_percentile:.2f}")

    if result.param_cv:
        print("\nParameter Stability (CV):")
        for name, cv in result.param_cv.items():
            flag = " *** UNSTABLE ***" if cv > 0.5 else ""
            print(f"  {name}: {cv:.3f}{flag}")

    if result.warnings:
        print(f"\nWarnings ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"  - {w}")

    print("\nPer-Window Detail:")
    print(f"{'Win':>4} {'Train':>21} {'Test':>21} {'IS':>8} {'OOS':>8} {'Ratio':>8}")
    print("-" * 75)
    for w in result.windows:
        ratio = w.oos_sharpe / w.is_sharpe if abs(w.is_sharpe) > 0.01 else 0
        print(
            f"{w.window_index:>4} {w.train_start}→{w.train_end} "
            f"{w.test_start}→{w.test_end} "
            f"{w.is_sharpe:>8.3f} {w.oos_sharpe:>8.3f} {ratio:>8.3f}"
        )

    # Save JSON output
    if args.output:
        output = {
            "mean_is_sharpe": result.mean_is_sharpe,
            "mean_oos_sharpe": result.mean_oos_sharpe,
            "oos_degradation_ratio": result.oos_degradation_ratio,
            "deflated_sharpe": result.deflated_sharpe,
            "dsr_pvalue": result.dsr_pvalue,
            "bootstrap_percentile": result.bootstrap_percentile,
            "param_cv": result.param_cv,
            "warnings": result.warnings,
            "windows": [
                {
                    "index": w.window_index,
                    "train": f"{w.train_start}→{w.train_end}",
                    "test": f"{w.test_start}→{w.test_end}",
                    "is_sharpe": w.is_sharpe,
                    "oos_sharpe": w.oos_sharpe,
                    "best_params": w.best_params,
                }
                for w in result.windows
            ],
        }
        Path(args.output).write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
