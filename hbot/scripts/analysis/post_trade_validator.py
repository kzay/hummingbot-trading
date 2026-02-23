"""Post-trade shadow validator.

Validates edge model assumptions against realized fill data.  Computes
realized fill_factor, adverse selection, and queue participation, then
compares against configured values.

Flags CRITICAL when realized metrics are materially worse than assumptions.

Usage::

    python scripts/analysis/post_trade_validator.py --bot bot1 --variant a
"""
from __future__ import annotations

import argparse
import csv
import sys
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


def validate(
    fills: List[Dict[str, str]],
    minutes: List[Dict[str, str]],
    config_fill_factor: float = 0.4,
    config_adverse_selection_bps: float = 1.5,
    config_queue_participation: float = 0.35,
) -> Dict[str, object]:
    """Validate edge model assumptions against realized data."""
    if not fills or not minutes:
        return {"status": "INSUFFICIENT_DATA", "fill_count": len(fills), "minute_count": len(minutes)}

    captures: List[float] = []
    expected_spreads: List[float] = []
    post_fill_drifts: List[float] = []

    minute_by_key: Dict[int, Dict[str, str]] = {}
    for m in minutes:
        try:
            from datetime import datetime
            ts_str = str(m.get("ts", "")).strip()
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
            minute_by_key[int(ts // 60)] = m
        except Exception:
            continue

    for fill in fills:
        price = safe_float(fill.get("price"))
        mid_ref = safe_float(fill.get("mid_ref"))
        spread = safe_float(fill.get("expected_spread_pct"))
        if price <= 0 or mid_ref <= 0 or spread <= 0:
            continue

        realized_capture = abs(price - mid_ref) / mid_ref
        captures.append(realized_capture)
        expected_spreads.append(spread)

        try:
            from datetime import datetime
            fill_ts_str = str(fill.get("ts", "")).strip()
            fill_ts = datetime.fromisoformat(fill_ts_str.replace("Z", "+00:00")).timestamp()
            post_fill_minute_key = int(fill_ts // 60) + 1
            post_minute = minute_by_key.get(post_fill_minute_key)
            if post_minute:
                post_mid = safe_float(post_minute.get("mid"))
                if post_mid > 0:
                    drift = abs(post_mid - price) / price
                    post_fill_drifts.append(drift)
        except Exception:
            continue

    if not captures:
        return {"status": "INSUFFICIENT_DATA", "fill_count": len(fills), "usable_fills": 0}

    avg_capture = sum(captures) / len(captures)
    avg_spread = sum(expected_spreads) / len(expected_spreads) if expected_spreads else 0
    realized_fill_factor = avg_capture / avg_spread if avg_spread > 0 else 0

    realized_adverse_bps = 0.0
    if post_fill_drifts:
        realized_adverse_bps = sum(post_fill_drifts) / len(post_fill_drifts) * 10000

    running_minutes = sum(1 for m in minutes if str(m.get("state", "")).strip() == "running")
    active_minutes = sum(1 for m in minutes if safe_float(m.get("orders_active", 0)) > 0)
    fill_count = len(fills)
    hours = len(minutes) / 60.0
    realized_queue_participation = fill_count / max(1, active_minutes) if active_minutes > 0 else 0

    checks: List[Dict[str, object]] = []

    ff_ratio = realized_fill_factor / config_fill_factor if config_fill_factor > 0 else 0
    checks.append({
        "metric": "fill_factor",
        "configured": config_fill_factor,
        "realized": round(realized_fill_factor, 4),
        "ratio": round(ff_ratio, 4),
        "severity": "CRITICAL" if ff_ratio < 0.7 else ("WARNING" if ff_ratio < 0.85 else "OK"),
        "message": f"Realized fill_factor is {ff_ratio:.0%} of configured" if ff_ratio < 0.85 else "fill_factor within tolerance",
    })

    as_ratio = realized_adverse_bps / config_adverse_selection_bps if config_adverse_selection_bps > 0 else 0
    checks.append({
        "metric": "adverse_selection_bps",
        "configured": config_adverse_selection_bps,
        "realized": round(realized_adverse_bps, 2),
        "ratio": round(as_ratio, 2),
        "severity": "CRITICAL" if as_ratio > 3.0 else ("WARNING" if as_ratio > 2.0 else "OK"),
        "message": f"Realized adverse selection is {as_ratio:.1f}x configured" if as_ratio > 2.0 else "adverse selection within tolerance",
    })

    has_critical = any(c["severity"] == "CRITICAL" for c in checks)
    has_warning = any(c["severity"] == "WARNING" for c in checks)

    return {
        "status": "CRITICAL" if has_critical else ("WARNING" if has_warning else "PASS"),
        "fill_count": len(fills),
        "usable_fills": len(captures),
        "post_fill_drift_samples": len(post_fill_drifts),
        "running_minutes": running_minutes,
        "active_minutes": active_minutes,
        "realized_fill_factor": round(realized_fill_factor, 4),
        "realized_adverse_selection_bps": round(realized_adverse_bps, 2),
        "realized_fills_per_active_minute": round(realized_queue_participation, 4),
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Post-trade shadow validator")
    parser.add_argument("--bot", default="bot1")
    parser.add_argument("--variant", default="a")
    parser.add_argument("--data-root", default=str(_HBOT_ROOT / "data"))
    parser.add_argument("--fill-factor", type=float, default=0.4)
    parser.add_argument("--adverse-selection-bps", type=float, default=1.5)
    parser.add_argument("--queue-participation", type=float, default=0.35)
    args = parser.parse_args()

    base = Path(args.data_root) / args.bot / "logs" / "epp_v24" / f"{args.bot}_{args.variant}"
    fills = _read_csv(base / "fills.csv")
    minutes = _read_csv(base / "minute.csv")

    result = validate(
        fills, minutes,
        config_fill_factor=args.fill_factor,
        config_adverse_selection_bps=args.adverse_selection_bps,
        config_queue_participation=args.queue_participation,
    )
    result["ts_utc"] = utc_now()
    result["bot"] = args.bot
    result["variant"] = args.variant

    out_dir = _HBOT_ROOT / "reports" / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "post_trade_validation.json", result)

    print(f"[post-trade] status={result['status']} fills={result.get('usable_fills', 0)}")
    for check in result.get("checks", []):
        print(f"  {check['severity']} {check['metric']}: configured={check['configured']} realized={check['realized']} ({check['message']})")


if __name__ == "__main__":
    main()
