"""Fill factor calibration from historical fills data.

Reads fills.csv + minute.csv to compute the realized fill factor:
``realized_fill_factor = mean(|fill_price - mid_ref| / mid_ref) / mean(spread_pct)``

This tells us what fraction of the quoted spread is actually captured per fill,
accounting for queue position, partial fills, and price movement.

Usage::

    python scripts/analysis/calibrate_fill_factor.py --bot bot1 --variant a
"""
from __future__ import annotations

import argparse
import csv
import sys
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
_HBOT_ROOT = _SCRIPT_DIR.parents[1]
sys.path.insert(0, str(_HBOT_ROOT))

from services.common.utils import safe_float, utc_now, write_json


def _read_fills(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def calibrate(fills: List[Dict[str, str]]) -> Dict[str, object]:
    """Compute realized fill factor from fills data."""
    spread_captures: List[float] = []
    expected_spreads: List[float] = []
    maker_count = 0
    taker_count = 0

    for fill in fills:
        fill_price = safe_float(fill.get("price"))
        mid_ref = safe_float(fill.get("mid_ref"))
        expected_spread = safe_float(fill.get("expected_spread_pct"))
        side = str(fill.get("side", "")).lower()

        if fill_price <= 0 or mid_ref <= 0 or expected_spread <= 0:
            continue

        realized_capture = abs(fill_price - mid_ref) / mid_ref
        spread_captures.append(realized_capture)
        expected_spreads.append(expected_spread)

        if side == "buy" and fill_price < mid_ref:
            maker_count += 1
        elif side == "sell" and fill_price > mid_ref:
            maker_count += 1
        else:
            taker_count += 1

    if not spread_captures or not expected_spreads:
        return {
            "status": "insufficient_data",
            "fill_count": len(fills),
            "usable_fills": 0,
        }

    avg_capture = sum(spread_captures) / len(spread_captures)
    avg_spread = sum(expected_spreads) / len(expected_spreads)
    realized_fill_factor = avg_capture / avg_spread if avg_spread > 0 else 0

    total_classified = maker_count + taker_count
    maker_ratio = maker_count / total_classified if total_classified > 0 else 0

    return {
        "status": "ok",
        "fill_count": len(fills),
        "usable_fills": len(spread_captures),
        "avg_spread_capture_pct": round(avg_capture, 8),
        "avg_expected_spread_pct": round(avg_spread, 8),
        "realized_fill_factor": round(realized_fill_factor, 4),
        "maker_count": maker_count,
        "taker_count": taker_count,
        "maker_ratio": round(maker_ratio, 4),
        "recommendation": (
            f"Set fill_factor={round(realized_fill_factor, 2)} in controller config"
            if realized_fill_factor > 0
            else "Not enough data to calibrate"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate fill_factor from fills.csv")
    parser.add_argument("--bot", default="bot1")
    parser.add_argument("--variant", default="a")
    parser.add_argument("--data-root", default=str(_HBOT_ROOT / "data"))
    args = parser.parse_args()

    fills_path = Path(args.data_root) / args.bot / "logs" / "epp_v24" / f"{args.bot}_{args.variant}" / "fills.csv"
    fills = _read_fills(fills_path)
    result = calibrate(fills)
    result["ts_utc"] = utc_now()
    result["bot"] = args.bot
    result["variant"] = args.variant
    result["fills_path"] = str(fills_path)

    out_dir = _HBOT_ROOT / "reports" / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "fill_factor_calibration.json", result)

    print(f"[calibrate] status={result['status']}")
    print(f"[calibrate] usable_fills={result.get('usable_fills', 0)}")
    print(f"[calibrate] realized_fill_factor={result.get('realized_fill_factor', 'n/a')}")
    print(f"[calibrate] maker_ratio={result.get('maker_ratio', 'n/a')}")
    print(f"[calibrate] recommendation: {result.get('recommendation', 'n/a')}")


if __name__ == "__main__":
    main()
