"""CLI: Run a single backtest using the v2 backtesting engine.

Usage:
    python -m scripts.backtest.run_backtest_v2 --config data/backtest_configs/bot1_baseline.yml
    python -m scripts.backtest.run_backtest_v2 --config data/backtest_configs/bot7_pullback.yml --output reports/backtest/bot7_run.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Run a single backtest (v2 engine)")
    ap.add_argument("--config", required=True, help="YAML backtest config file")
    ap.add_argument("--output", default="", help="Output JSON report path (default: auto-generated)")
    ap.add_argument("--quiet", action="store_true", help="Suppress stdout summary")
    args = ap.parse_args()

    from controllers.backtesting.config_loader import load_backtest_config
    from controllers.backtesting.harness import BacktestHarness
    from controllers.backtesting.report import print_summary, save_equity_curve_csv, save_json_report

    config = load_backtest_config(args.config)
    harness = BacktestHarness(config)

    try:
        result = harness.run()
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"CONFIG ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Output
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_id = config.run_id or result.strategy_name or "run"
    json_path = args.output or str(output_dir / f"{run_id}_report.json")
    csv_path = str(output_dir / f"{run_id}_equity.csv")

    save_json_report(result, Path(json_path))
    save_equity_curve_csv(result, Path(csv_path))

    if not args.quiet:
        print_summary(result)
        print(f"\nReport: {json_path}")
        print(f"Equity curve: {csv_path}")


if __name__ == "__main__":
    main()
