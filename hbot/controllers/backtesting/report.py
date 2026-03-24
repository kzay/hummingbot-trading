"""Backtest report generation: JSON serialization, CSV equity curve, stdout summary."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from controllers.backtesting.types import BacktestResult

logger = logging.getLogger(__name__)


class _DecimalEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        return super().default(o)


def save_json_report(result: BacktestResult, output_path: Path) -> None:
    """Write full backtest result to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(result)
    output_path.write_text(json.dumps(data, cls=_DecimalEncoder, indent=2), encoding="utf-8")
    logger.info("JSON report saved to %s", output_path)


def save_equity_curve_csv(result: BacktestResult, output_path: Path) -> None:
    """Write equity curve to CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["date,equity,drawdown_pct,daily_return_pct,cumulative_return_pct,position_notional,num_fills"]
    for snap in result.equity_curve:
        lines.append(
            f"{snap.date},{snap.equity},{snap.drawdown_pct},{snap.daily_return_pct},"
            f"{snap.cumulative_return_pct},{snap.position_notional},{snap.num_fills}"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Equity curve CSV saved to %s", output_path)


def print_summary(result: BacktestResult) -> None:
    """Print concise summary to stdout (<=25 lines)."""
    print("=" * 60)
    print(f"  BACKTEST REPORT: {result.strategy_name or 'unnamed'}")
    print(f"  Data: {result.data_start} -> {result.data_end}  ({result.total_ticks} ticks)")
    print("=" * 60)
    print(f"  Total Return:     {result.total_return_pct:+.2f}%")
    print(f"  CAGR:             {result.cagr_pct:+.2f}%")
    print(f"  Sharpe:           {result.sharpe_ratio:.2f}")
    print(f"  Sortino:          {result.sortino_ratio:.2f}")
    print(f"  Calmar:           {result.calmar_ratio:.2f}")
    print(f"  Max Drawdown:     {result.max_drawdown_pct:.2f}% ({result.max_drawdown_duration_days}d)")
    print("-" * 60)
    print(f"  Fills:            {result.fill_count}  (fill rate: {result.fill_rate:.1%})")
    print(f"  Maker ratio:      {result.maker_fill_ratio:.1%}")
    print(f"  Fees:             {result.total_fees}  (drag: {result.fee_drag_pct:.1f}%)")
    print(f"  Avg slippage:     {result.avg_slippage_bps:.2f} bps (mid: {result.avg_mid_slippage_bps:.2f} bps)")
    print(f"  Capture eff:      {result.spread_capture_efficiency:.2f}")
    print(f"  Inventory HL:     {result.inventory_half_life_minutes:.0f} min")
    print(f"  Turnover:         {result.turnover_ratio:.1f}x")
    print(f"  Run time:         {result.run_duration_s:.1f}s")

    if result.fill_disclaimer:
        print(f"\n  {result.fill_disclaimer}")

    if result.warnings:
        print("-" * 60)
        for w in result.warnings[:5]:
            print(f"  {w}")
        if len(result.warnings) > 5:
            print(f"  ... and {len(result.warnings) - 5} more warnings")

    print("=" * 60)
