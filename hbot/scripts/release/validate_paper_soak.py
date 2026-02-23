"""Paper soak KPI validator.

Reads ``minute.csv`` from a paper bot over a specified time window and checks
all 7 KPIs required for promotion:

1. ``% running >= 65%``
2. ``turnover_today_x <= 3.0``
3. ``daily_loss_pct < 1.5%``
4. ``drawdown_pct < 2.5%``
5. ``cancel_per_min < cancel_budget_per_min for >95% of samples``
6. ``paper_fill_count > 0``
7. ``paper_reject_count near zero after warmup``

Usage::

    python scripts/release/validate_paper_soak.py --bot bot3 --window-hours 2
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
_HBOT_ROOT = _SCRIPT_DIR.parents[1]
sys.path.insert(0, str(_HBOT_ROOT))

from services.common.utils import safe_float, utc_now, write_json


def _read_minute_rows(path: Path, window_hours: float) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    cutoff_ts = datetime.now(timezone.utc).timestamp() - window_hours * 3600
    rows: List[Dict[str, str]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_str = str(row.get("ts", "")).strip()
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
                except Exception:
                    continue
                if ts >= cutoff_ts:
                    rows.append(row)
    except Exception:
        pass
    return rows


def validate(
    rows: List[Dict[str, str]],
    cancel_budget_per_min: int = 50,
) -> Dict[str, object]:
    """Evaluate all 7 KPIs against the rows and return per-KPI results."""
    if not rows:
        return {
            "status": "FAIL",
            "reason": "no_data",
            "kpis": {},
            "sample_count": 0,
        }

    total = len(rows)
    running_count = sum(1 for r in rows if str(r.get("state", "")).strip() == "running")
    running_pct = running_count / total if total > 0 else 0

    max_turnover = max(safe_float(r.get("turnover_today_x")) for r in rows)
    max_daily_loss = max(safe_float(r.get("daily_loss_pct")) for r in rows)
    max_drawdown = max(safe_float(r.get("drawdown_pct")) for r in rows)

    cancel_ok_count = sum(
        1 for r in rows if safe_float(r.get("cancel_per_min")) < cancel_budget_per_min
    )
    cancel_ok_pct = cancel_ok_count / total if total > 0 else 0

    paper_fills = max(int(safe_float(r.get("paper_fill_count", "0"))) for r in rows) if rows else 0

    warmup_cutoff = max(1, total // 4)
    post_warmup = rows[warmup_cutoff:]
    paper_rejects = max(int(safe_float(r.get("paper_reject_count", "0"))) for r in post_warmup) if post_warmup else 0

    kpis = {
        "running_pct": {
            "value": round(running_pct, 4),
            "threshold": 0.65,
            "pass": running_pct >= 0.65,
        },
        "max_turnover_x": {
            "value": round(max_turnover, 4),
            "threshold": 3.0,
            "pass": max_turnover <= 3.0,
        },
        "max_daily_loss_pct": {
            "value": round(max_daily_loss, 6),
            "threshold": 0.015,
            "pass": max_daily_loss < 0.015,
        },
        "max_drawdown_pct": {
            "value": round(max_drawdown, 6),
            "threshold": 0.025,
            "pass": max_drawdown < 0.025,
        },
        "cancel_budget_compliance_pct": {
            "value": round(cancel_ok_pct, 4),
            "threshold": 0.95,
            "pass": cancel_ok_pct >= 0.95,
        },
        "paper_fill_count": {
            "value": paper_fills,
            "threshold": 1,
            "pass": paper_fills > 0,
        },
        "paper_reject_count_post_warmup": {
            "value": paper_rejects,
            "threshold": 5,
            "pass": paper_rejects <= 5,
        },
    }

    all_pass = all(k["pass"] for k in kpis.values())
    return {
        "status": "PASS" if all_pass else "FAIL",
        "reason": "all_kpis_green" if all_pass else "kpi_failure",
        "sample_count": total,
        "kpis": kpis,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper soak KPI validator")
    parser.add_argument("--bot", default="bot3", help="Bot instance name")
    parser.add_argument("--variant", default="a", help="Controller variant")
    parser.add_argument("--window-hours", type=float, default=2.0, help="Lookback window in hours")
    parser.add_argument("--data-root", default=str(_HBOT_ROOT / "data"), help="Data root path")
    parser.add_argument("--cancel-budget", type=int, default=50, help="Cancel budget per minute")
    args = parser.parse_args()

    minute_path = Path(args.data_root) / args.bot / "logs" / "epp_v24" / f"{args.bot}_{args.variant}" / "minute.csv"
    rows = _read_minute_rows(minute_path, args.window_hours)
    result = validate(rows, cancel_budget_per_min=args.cancel_budget)
    result["ts_utc"] = utc_now()
    result["bot"] = args.bot
    result["variant"] = args.variant
    result["window_hours"] = args.window_hours
    result["minute_path"] = str(minute_path)

    out_dir = _HBOT_ROOT / "reports" / "paper_soak"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"paper_soak_{stamp}.json"
    write_json(out_path, result)
    write_json(out_dir / "latest.json", result)

    print(f"[paper-soak] status={result['status']} samples={result['sample_count']}")
    for name, kpi in result.get("kpis", {}).items():
        marker = "PASS" if kpi["pass"] else "FAIL"
        print(f"  {marker} {name}: {kpi['value']} (threshold: {kpi['threshold']})")
    print(f"[paper-soak] evidence={out_path}")

    sys.exit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
