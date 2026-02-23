"""Generic report writer for backtest results.

Produces ``summary.json`` and ``bars.jsonl`` with the same schema
regardless of strategy type.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

from scripts.backtest.harness.portfolio_tracker import PortfolioSnapshot
from services.common.utils import utc_now


def _decimal_default(obj: object) -> object:
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def write_summary(
    run_dir: Path,
    run_id: str,
    strategy_name: str,
    config_hash: str,
    data_source: str,
    venue: str,
    trading_pair: str,
    start_ts: float,
    end_ts: float,
    snapshots: List[PortfolioSnapshot],
    fill_count: int,
    total_fees_quote: Decimal,
    extra: Dict[str, object] = None,
) -> Path:
    """Write ``summary.json`` to *run_dir* and return the path."""
    run_dir.mkdir(parents=True, exist_ok=True)
    final_snap = snapshots[-1] if snapshots else None

    summary = {
        "run_id": run_id,
        "ts_utc": utc_now(),
        "strategy_name": strategy_name,
        "config_hash": config_hash,
        "data_source": data_source,
        "venue": venue,
        "trading_pair": trading_pair,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "bar_count": len(snapshots),
        "fill_count": fill_count,
        "total_fees_quote": str(total_fees_quote),
        "total_pnl_quote": str(final_snap.total_pnl_quote) if final_snap else "0",
        "max_drawdown_pct": str(max((s.drawdown_pct for s in snapshots), default=Decimal("0"))),
        "final_equity_quote": str(final_snap.equity_quote) if final_snap else "0",
        "extra": extra or {},
    }

    path = run_dir / "summary.json"
    path.write_text(json.dumps(summary, indent=2, default=_decimal_default), encoding="utf-8")
    return path


def write_bars(run_dir: Path, snapshots: List[PortfolioSnapshot]) -> Path:
    """Write ``bars.jsonl`` with bar-by-bar portfolio state."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "bars.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for snap in snapshots:
            row = {
                "ts": snap.timestamp_s,
                "equity_quote": str(snap.equity_quote),
                "base_pct": str(snap.base_pct),
                "drawdown_pct": str(snap.drawdown_pct),
                "fill_count": snap.fill_count,
                "total_fees_quote": str(snap.total_fees_quote),
                "total_pnl_quote": str(snap.total_pnl_quote),
            }
            f.write(json.dumps(row) + "\n")
    return path
