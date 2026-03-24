"""CLI for running parameter sweeps from YAML configs."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from decimal import Decimal
from pathlib import Path

from controllers.backtesting.config_loader import load_sweep_config
from controllers.backtesting.sweep import SweepRunner

logger = logging.getLogger(__name__)


class _DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return str(o)
        return super().default(o)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a parameter sweep backtest")
    parser.add_argument("--config", required=True, help="Path to sweep YAML config")
    parser.add_argument("--output", default="", help="Path to write JSON results")
    parser.add_argument("--top", type=int, default=10, help="Print top N results to stdout")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s  %(message)s",
        stream=sys.stdout,
    )

    sweep_config = load_sweep_config(args.config)
    n_combos = 1
    for sp in sweep_config.param_spaces:
        if sp.mode == "grid":
            n_combos *= len(sp.values)
        elif sp.mode == "range":
            import math
            n_combos *= max(1, int(math.ceil((sp.max_val - sp.min_val) / sp.step)) + 1)
        else:
            n_combos *= max(1, sp.num_points)

    logger.info(
        "Sweep: %d param combinations, mode=%s, objective=%s, workers=%d",
        n_combos, sweep_config.sweep_mode, sweep_config.objective, sweep_config.workers,
    )

    runner = SweepRunner(sweep_config)
    results = runner.run()

    report = []
    for r in results:
        entry = {
            "rank": r.rank,
            "params": r.params,
            "error": r.error or None,
        }
        if r.result:
            entry["sharpe_ratio"] = r.result.sharpe_ratio
            entry["sortino_ratio"] = r.result.sortino_ratio
            entry["total_return_pct"] = r.result.total_return_pct
            entry["max_drawdown_pct"] = r.result.max_drawdown_pct
            entry["calmar_ratio"] = r.result.calmar_ratio
            entry["win_rate"] = r.result.win_rate
            entry["profit_factor"] = r.result.profit_factor
            entry["fill_count"] = r.result.fill_count
        report.append(entry)

    output_path = args.output or "reports/sweep/bot7_pullback_sweep.json"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(
        json.dumps(report, indent=2, cls=_DecimalEncoder),
        encoding="utf-8",
    )
    logger.info("Sweep results written to %s", output_path)

    top_n = min(args.top, len(results))
    print("=" * 80)
    print(f"  TOP {top_n} RESULTS (by {sweep_config.objective})")
    print("=" * 80)
    for r in results[:top_n]:
        if r.result:
            params_str = ", ".join(f"{k}={v}" for k, v in r.params.items())
            print(
                f"  #{r.rank:2d}  Sharpe={r.result.sharpe_ratio:+.3f}  "
                f"Return={r.result.total_return_pct:+.2f}%  "
                f"MaxDD={r.result.max_drawdown_pct:.2f}%  "
                f"Fills={r.result.fill_count}  "
                f"WR={r.result.win_rate:.1%}  "
                f"PF={r.result.profit_factor:.2f}"
            )
            print(f"        {params_str}")
        elif r.error:
            print(f"  #{r.rank:2d}  ERROR: {r.error[:100]}")
    print("=" * 80)

    ok = sum(1 for r in results if r.result is not None)
    errors = sum(1 for r in results if r.error)
    print(f"\n  {ok} successful / {errors} errors / {len(results)} total")

    if results and results[0].result:
        best = results[0]
        print("\n  Best config overrides:")
        for k, v in best.params.items():
            print(f"    {k}: {v}")
    print()


if __name__ == "__main__":
    main()
