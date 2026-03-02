"""Multi-day paper trading summary for bot1.

Aggregates daily summaries across a date range, computes:
- Sharpe ratio (annualized)
- Max drawdown
- Win rate (days with positive PnL)
- Regime breakdown
- Fee efficiency

Required for ROAD-1 gate: run after 20 consecutive days of paper trading.

Usage:
    python hbot/scripts/analysis/bot1_multi_day_summary.py --start 2026-01-01 --end 2026-01-20
    python hbot/scripts/analysis/bot1_multi_day_summary.py --start 2026-01-01 --end 2026-01-20 --save
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional


_ZERO = Decimal("0")
def _repo_root() -> Path:
    if Path("/.dockerenv").exists():
        return Path("/workspace/hbot")
    return Path(__file__).resolve().parents[2]


_REPORTS_DIR = _repo_root() / "reports" / "strategy"


def _date_range(start: str, end: str) -> List[str]:
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    result = []
    current = d0
    while current <= d1:
        result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def _run_day_summary(day: str, root: str) -> Optional[Dict]:
    """Run bot1_paper_day_summary.py for a single day and return parsed output."""
    script = Path(__file__).parent / "bot1_paper_day_summary.py"
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--day", day, "--root", root],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout)
    except Exception:
        return None


def _daily_table_markdown(rows: List[Dict]) -> str:
    header = "| date | net_pnl_usdt | net_pnl_bps | drawdown_pct | fills | turnover_x | dominant_regime |"
    sep = "|---|---:|---:|---:|---:|---:|---|"

    def _fmt(val: object, nd: int = 4) -> str:
        if val is None:
            return "n/a"
        try:
            return f"{float(val):.{nd}f}"
        except Exception:
            return "n/a"

    body = [
        f"| {r['date']} | {_fmt(r['net_pnl_usdt'], 4)} | {_fmt(r['net_pnl_bps'], 2)} | {_fmt(r['drawdown_pct'], 4)} | {r['fills']} | {_fmt(r['turnover_x'], 3)} | {r['dominant_regime']} |"
        for r in rows
    ]
    return "\n".join([header, sep, *body])


def _d(x) -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        return _ZERO


def compute_summary(
    start: str,
    end: str,
    root: str = "",
    save: bool = False,
) -> Dict:
    if not root:
        root = str(_repo_root() / "data" / "bot1" / "logs" / "epp_v24" / "bot1_a")
    days = _date_range(start, end)
    daily_results: List[Dict] = []
    missing_days: List[str] = []

    for day in days:
        result = _run_day_summary(day, root)
        if result is None:
            missing_days.append(day)
            continue
        fills_agg = result.get("fills_agg", {})
        minute_snap = result.get("minute_snapshot", {})
        fills = int(fills_agg.get("fills", 0))
        if fills == 0 and not minute_snap.get("rows"):
            missing_days.append(day)
            continue

        realized_pnl = _d(fills_agg.get("realized_pnl_sum_quote", "0"))
        fees = _d(fills_agg.get("fees_quote", "0"))
        net_pnl = realized_pnl - fees

        minute_rows = int(minute_snap.get("rows", 0) or 0)
        equity_str = minute_snap.get("equity_quote", "0") or "0"
        equity = _d(equity_str)

        turnover = _d(minute_snap.get("turnover_today_x", "0") or "0") if minute_rows > 0 else _ZERO
        drawdown_pct = _d(minute_snap.get("drawdown_pct", "0") or "0") if minute_rows > 0 else _ZERO
        daily_loss_pct = _d(minute_snap.get("daily_loss_pct", "0") or "0") if minute_rows > 0 else _ZERO
        cap_active_rows = int(minute_snap.get("spread_competitiveness_cap_active_rows", 0) or 0) if minute_rows > 0 else 0
        cap_observed_rows = int(minute_snap.get("spread_competitiveness_cap_observed_rows", minute_rows) or 0) if minute_rows > 0 else 0
        cap_hit_ratio = (
            float(Decimal(cap_active_rows) / Decimal(cap_observed_rows))
            if cap_observed_rows > 0
            else None
        )

        regime_counts = minute_snap.get("regime_counts", {})
        dominant_regime = max(regime_counts, key=regime_counts.get) if regime_counts else "unknown"
        has_equity = equity > _ZERO
        has_regime = bool(regime_counts)
        if minute_rows > 0 and has_equity and has_regime:
            confidence = "high"
        elif minute_rows > 0:
            confidence = "medium"
        else:
            confidence = "low"

        net_pnl_bps = None if equity <= _ZERO else float(net_pnl / equity * Decimal("10000"))

        daily_results.append({
            "date": day,
            "realized_pnl_usdt": float(realized_pnl),
            "fees_usdt": float(fees),
            "net_pnl_usdt": float(net_pnl),
            "net_pnl_bps": net_pnl_bps,
            "drawdown_pct": float(drawdown_pct),
            "daily_loss_pct": float(daily_loss_pct),
            "fills": fills,
            "turnover_x": float(turnover),
            "dominant_regime": dominant_regime,
            "equity_quote": float(equity),
            "regime_counts": regime_counts,
            "spread_competitiveness_cap_active_rows": cap_active_rows,
            "spread_competitiveness_cap_observed_rows": cap_observed_rows,
            "spread_competitiveness_cap_hit_ratio": cap_hit_ratio,
            "data_quality": {
                "confidence": confidence,
                "minute_rows": minute_rows,
                "has_equity_quote": has_equity,
                "has_regime_counts": has_regime,
            },
        })

    if not daily_results:
        return {
            "error": "no_data",
            "days_checked": len(days),
            "days_with_data": 0,
            "missing_days": missing_days,
        }

    pnl_values = [Decimal(str(d["net_pnl_usdt"])) for d in daily_results]
    n = len(pnl_values)
    mean_pnl = sum(pnl_values, _ZERO) / Decimal(n)
    variance = sum((p - mean_pnl) ** 2 for p in pnl_values) / Decimal(n)
    std_pnl = variance.sqrt() if variance > _ZERO else Decimal("0.0001")
    sharpe = float(mean_pnl / std_pnl) * math.sqrt(252) if std_pnl > _ZERO else 0.0

    winning_days = sum(1 for d in daily_results if d["net_pnl_usdt"] > 0)
    win_rate = winning_days / n

    max_dd = max((float(d["drawdown_pct"]) for d in daily_results), default=0.0)
    hard_stop_days = sum(1 for d in daily_results if d["daily_loss_pct"] >= 0.03)
    confidence_counts: Dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for d in daily_results:
        c = str(d.get("data_quality", {}).get("confidence", "low"))
        confidence_counts[c] = confidence_counts.get(c, 0) + 1

    all_regimes: Dict[str, int] = {}
    for d in daily_results:
        for r, cnt in d.get("regime_counts", {}).items():
            all_regimes[r] = all_regimes.get(r, 0) + cnt

    total_fills = sum(d["fills"] for d in daily_results)
    total_fees = sum(_d(d["fees_usdt"]) for d in daily_results)
    total_net_pnl = sum(_d(d["net_pnl_usdt"]) for d in daily_results)
    total_cap_active_rows = sum(int(d.get("spread_competitiveness_cap_active_rows", 0) or 0) for d in daily_results)
    total_cap_observed_rows = sum(int(d.get("spread_competitiveness_cap_observed_rows", 0) or 0) for d in daily_results)
    cap_hit_ratio = (
        float(Decimal(total_cap_active_rows) / Decimal(total_cap_observed_rows))
        if total_cap_observed_rows > 0
        else None
    )

    road1_gate = (
        float(mean_pnl) > 0
        and sharpe >= 1.5
        and max_dd < 0.02
        and hard_stop_days == 0
    )

    output = {
        "period": {"start": start, "end": end},
        "n_days": n,
        "days_with_data": n,
        "days_checked": len(days),
        "missing_days_count": len(missing_days),
        "missing_days": missing_days,
        "warnings": (
            ([f"missing_or_empty_days={len(missing_days)}"] if missing_days else [])
            + ([f"medium_confidence_days={confidence_counts.get('medium', 0)}"] if confidence_counts.get("medium", 0) else [])
            + ([f"low_confidence_days={confidence_counts.get('low', 0)}"] if confidence_counts.get("low", 0) else [])
        ),
        "data_quality": {
            "confidence_counts": confidence_counts,
            "high_confidence_days": confidence_counts.get("high", 0),
            "medium_confidence_days": confidence_counts.get("medium", 0),
            "low_confidence_days": confidence_counts.get("low", 0),
        },
        "total_net_pnl_usdt": float(total_net_pnl),
        "total_fees_usdt": float(total_fees),
        "mean_daily_pnl_usdt": float(mean_pnl),
        "std_daily_pnl_usdt": float(std_pnl),
        "sharpe_annualized": round(sharpe, 3),
        "win_rate": round(win_rate, 3),
        "winning_days": winning_days,
        "losing_days": n - winning_days,
        "max_single_day_drawdown_pct": round(max_dd, 4),
        "hard_stop_days": hard_stop_days,
        "total_fills": total_fills,
        "spread_competitiveness_cap_active_rows": total_cap_active_rows,
        "spread_competitiveness_cap_observed_rows": total_cap_observed_rows,
        "spread_competitiveness_cap_hit_ratio": cap_hit_ratio,
        "regime_breakdown": all_regimes,
        "daily_table_markdown": _daily_table_markdown(daily_results),
        "road1_gate": {
            "pass": road1_gate,
            "criteria": {
                "mean_daily_pnl_positive": float(mean_pnl) > 0,
                "sharpe_gte_1_5": sharpe >= 1.5,
                "max_drawdown_lt_2pct": max_dd < 0.02,
                "no_hard_stop_days": hard_stop_days == 0,
            },
        },
        "daily_breakdown": daily_results,
    }

    if save:
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = _REPORTS_DIR / "multi_day_summary_latest.json"
        out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(f"Saved to {out_path}", file=sys.stderr)

    return output


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Multi-day paper trading summary for bot1")
    ap.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    ap.add_argument("--root", default="", help="Optional bot log root; defaults to data/bot1/logs/epp_v24/bot1_a")
    ap.add_argument("--save", action="store_true", help="Save result to reports/strategy/multi_day_summary_latest.json")
    args = ap.parse_args()

    result = compute_summary(start=args.start, end=args.end, root=args.root, save=args.save)
    print(json.dumps(result, indent=2))

    gate = result.get("road1_gate", {})
    if gate.get("pass"):
        print("\n✓ ROAD-1 gate: PASS — 20-day paper edge confirmed", file=sys.stderr)
    else:
        criteria = gate.get("criteria", {})
        failed = [k for k, v in criteria.items() if not v]
        print(f"\n✗ ROAD-1 gate: FAIL — criteria not met: {', '.join(failed)}", file=sys.stderr)
