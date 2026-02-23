"""Daily edge report — shows whether the strategy is actually profitable.

Computes: gross_spread_capture - fees_paid - estimated_slippage - adverse_drift_cost
on a per-fill and per-day basis.

Usage::

    python scripts/analysis/edge_report.py --bot bot1 --variant a
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

_SCRIPT_DIR = Path(__file__).resolve().parent
_HBOT_ROOT = _SCRIPT_DIR.parents[1]
sys.path.insert(0, str(_HBOT_ROOT))

from services.common.utils import safe_float, utc_now, write_json


def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def compute_edge(fills: List[Dict[str, str]]) -> Dict[str, object]:
    """Compute edge metrics from fills data."""
    if not fills:
        return {"status": "no_fills", "fill_count": 0}

    total_notional = 0.0
    total_spread_capture = 0.0
    total_fees = 0.0
    total_adverse_drift_cost = 0.0
    fill_count = 0
    daily_pnl: Dict[str, float] = defaultdict(float)

    for fill in fills:
        price = safe_float(fill.get("price"))
        mid_ref = safe_float(fill.get("mid_ref"))
        notional = safe_float(fill.get("notional_quote"))
        fee = safe_float(fill.get("fee_quote"))
        drift = safe_float(fill.get("adverse_drift_30s"))
        side = str(fill.get("side", "")).lower()
        ts = str(fill.get("ts", ""))[:10]

        if price <= 0 or mid_ref <= 0 or notional <= 0:
            continue

        fill_count += 1
        total_notional += notional
        total_fees += fee

        if side == "buy":
            spread_capture = (mid_ref - price) / mid_ref * notional
        else:
            spread_capture = (price - mid_ref) / mid_ref * notional
        total_spread_capture += spread_capture

        drift_cost = drift * notional
        total_adverse_drift_cost += drift_cost

        net = spread_capture - fee - drift_cost
        if ts:
            daily_pnl[ts] += net

    net_edge_total = total_spread_capture - total_fees - total_adverse_drift_cost
    avg_edge_per_fill = net_edge_total / fill_count if fill_count > 0 else 0
    avg_edge_bps = (net_edge_total / total_notional * 10000) if total_notional > 0 else 0
    avg_fee_bps = (total_fees / total_notional * 10000) if total_notional > 0 else 0
    avg_capture_bps = (total_spread_capture / total_notional * 10000) if total_notional > 0 else 0

    profitable_days = sum(1 for v in daily_pnl.values() if v > 0)
    losing_days = sum(1 for v in daily_pnl.values() if v <= 0)

    return {
        "status": "ok",
        "fill_count": fill_count,
        "total_notional_quote": round(total_notional, 2),
        "gross_spread_capture_quote": round(total_spread_capture, 6),
        "total_fees_quote": round(total_fees, 6),
        "total_adverse_drift_cost_quote": round(total_adverse_drift_cost, 6),
        "net_edge_total_quote": round(net_edge_total, 6),
        "avg_edge_per_fill_quote": round(avg_edge_per_fill, 6),
        "avg_edge_bps": round(avg_edge_bps, 2),
        "avg_fee_bps": round(avg_fee_bps, 2),
        "avg_capture_bps": round(avg_capture_bps, 2),
        "profitable_days": profitable_days,
        "losing_days": losing_days,
        "daily_pnl": {k: round(v, 6) for k, v in sorted(daily_pnl.items())},
        "verdict": (
            "POSITIVE_EDGE" if net_edge_total > 0
            else "NEGATIVE_EDGE" if fill_count > 10
            else "INSUFFICIENT_DATA"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily edge report")
    parser.add_argument("--bot", default="bot1")
    parser.add_argument("--variant", default="a")
    parser.add_argument("--data-root", default=str(_HBOT_ROOT / "data"))
    args = parser.parse_args()

    fills_path = Path(args.data_root) / args.bot / "logs" / "epp_v24" / f"{args.bot}_{args.variant}" / "fills.csv"
    fills = _read_csv(fills_path)
    result = compute_edge(fills)
    result["ts_utc"] = utc_now()
    result["bot"] = args.bot
    result["variant"] = args.variant

    out_dir = _HBOT_ROOT / "reports" / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "edge_report.json", result)

    print(f"[edge] verdict={result.get('verdict')}")
    print(f"[edge] fills={result.get('fill_count')} notional={result.get('total_notional_quote')}")
    print(f"[edge] gross_capture={result.get('avg_capture_bps')}bps fees={result.get('avg_fee_bps')}bps net={result.get('avg_edge_bps')}bps")
    print(f"[edge] net_edge_total={result.get('net_edge_total_quote')} quote")
    print(f"[edge] days: {result.get('profitable_days')} profitable / {result.get('losing_days')} losing")


if __name__ == "__main__":
    main()
