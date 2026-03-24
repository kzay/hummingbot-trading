"""CLI: Run a parameter sweep over a backtest configuration.

Usage:
    python -m scripts.backtest.run_sweep --config data/backtest_configs/bot1_sweep.yml
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Run a parameter sweep")
    ap.add_argument("--config", required=True, help="YAML sweep config file")
    ap.add_argument("--top", type=int, default=5, help="Show top N results")
    ap.add_argument("--output", default="", help="Output JSON path for results")
    args = ap.parse_args()

    import yaml

    from controllers.backtesting.sweep import SweepRunner
    from controllers.backtesting.types import (
        BacktestConfig,
        DataSourceConfig,
        ParamSpace,
        SweepConfig,
        SynthesisConfig,
    )

    with open(args.config) as f:
        raw = yaml.safe_load(f)

    # Parse base config
    base_raw = raw.get("base_config", {})
    ds_raw = base_raw.get("data_source", {})
    synth_raw = base_raw.get("synthesis", {})

    from decimal import Decimal

    base_config = BacktestConfig(
        strategy_class=base_raw.get("strategy_class", ""),
        strategy_config=base_raw.get("strategy_config", {}),
        data_source=DataSourceConfig(**ds_raw) if ds_raw else DataSourceConfig(),
        initial_equity=Decimal(str(base_raw.get("initial_equity", "500"))),
        fill_model=base_raw.get("fill_model", "latency_aware"),
        seed=base_raw.get("seed", 42),
        step_interval_s=base_raw.get("step_interval_s", 60),
        warmup_bars=base_raw.get("warmup_bars", 60),
        synthesis=SynthesisConfig(**{k: Decimal(str(v)) if isinstance(v, (int, float)) else v for k, v in synth_raw.items()}) if synth_raw else SynthesisConfig(),
    )

    # Parse param spaces
    spaces_raw = raw.get("param_spaces", [])
    param_spaces = []
    for s in spaces_raw:
        param_spaces.append(ParamSpace(
            name=s["name"],
            mode=s.get("mode", "grid"),
            values=s.get("values", []),
            min_val=s.get("min_val", 0.0),
            max_val=s.get("max_val", 0.0),
            step=s.get("step", 0.0),
            num_points=s.get("num_points", 0),
        ))

    sweep_config = SweepConfig(
        base_config=base_config,
        param_spaces=param_spaces,
        sweep_mode=raw.get("sweep_mode", "grid"),
        n_samples=raw.get("n_samples", 50),
        objective=raw.get("objective", "sharpe_ratio"),
        workers=raw.get("workers", 0),
        seed=raw.get("seed", 42),
    )

    runner = SweepRunner(sweep_config)
    results = runner.run()

    # Print top N
    print(f"\nTop {args.top} results (by {sweep_config.objective}):")
    print(f"{'Rank':>4} {'Sharpe':>8} {'Return%':>8} {'MaxDD%':>8} {'Fills':>6}  Params")
    print("-" * 70)
    for r in results[:args.top]:
        if r.result:
            print(
                f"{r.rank:>4} {r.result.sharpe_ratio:>8.3f} {r.result.total_return_pct:>8.2f} "
                f"{r.result.max_drawdown_pct:>8.2f} {r.result.fill_count:>6}  {r.params}"
            )
        else:
            print(f"{r.rank:>4}  ERROR: {r.error[:60]}")

    print(f"\n{len(results)} total runs completed.")

    # Save JSON output
    if args.output:
        output = []
        for r in results:
            entry = {"rank": r.rank, "params": r.params, "error": r.error}
            if r.result:
                entry["sharpe_ratio"] = r.result.sharpe_ratio
                entry["total_return_pct"] = r.result.total_return_pct
                entry["max_drawdown_pct"] = r.result.max_drawdown_pct
            output.append(entry)
        Path(args.output).write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
