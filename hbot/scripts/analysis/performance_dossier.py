#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


def _parse_ts(value: str) -> Optional[datetime]:
    s = (value or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _safe_float(v: object, d: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return d


def _iter_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _slippage_bps(side: str, px: float, mid: float) -> float:
    if mid <= 0:
        return 0.0
    side_l = (side or "").lower()
    if side_l == "buy":
        return ((px - mid) / mid) * 10000.0
    if side_l == "sell":
        return ((mid - px) / mid) * 10000.0
    return 0.0


def _percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = int(max(0, min(len(sorted_vals) - 1, (len(sorted_vals) - 1) * p)))
    return sorted_vals[idx]


def build_dossier(root: Path, bot_log_root: Path, lookback_days: int = 5) -> Dict[str, object]:
    fills = _iter_csv(bot_log_root / "fills.csv")
    minute = _iter_csv(bot_log_root / "minute.csv")

    # Per-day rollups from fills (execution truth source).
    by_day: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    slippage_by_day: Dict[str, List[float]] = defaultdict(list)
    maker_count_by_day: Dict[str, int] = defaultdict(int)
    fills_count_by_day: Dict[str, int] = defaultdict(int)

    for r in fills:
        ts = _parse_ts(r.get("ts", ""))
        if ts is None:
            continue
        day = ts.date().isoformat()
        by_day[day]["notional"] += _safe_float(r.get("notional_quote"))
        by_day[day]["fees"] += _safe_float(r.get("fee_quote"))
        by_day[day]["realized"] += _safe_float(r.get("realized_pnl_quote"))
        fills_count_by_day[day] += 1
        if str(r.get("is_maker", "")).lower() == "true":
            maker_count_by_day[day] += 1
        slip = _slippage_bps(
            side=str(r.get("side", "")),
            px=_safe_float(r.get("price")),
            mid=_safe_float(r.get("mid_ref")),
        )
        slippage_by_day[day].append(slip)

    days = sorted(by_day.keys())[-lookback_days:]
    day_rows: List[Dict[str, object]] = []
    for day in days:
        notional = by_day[day]["notional"]
        fees = by_day[day]["fees"]
        realized = by_day[day]["realized"]
        net = realized - fees
        maker_ratio = (maker_count_by_day[day] / fills_count_by_day[day]) if fills_count_by_day[day] > 0 else 0.0
        slips = sorted(slippage_by_day[day])
        day_rows.append(
            {
                "day": day,
                "fills": int(fills_count_by_day[day]),
                "realized_pnl_quote": realized,
                "fees_quote": fees,
                "net_pnl_quote": net,
                "fee_bps": ((fees / notional) * 10000.0) if notional > 0 else 0.0,
                "maker_ratio": maker_ratio,
                "slippage_median_bps": _percentile(slips, 0.50),
                "slippage_p95_bps": _percentile(slips, 0.95),
            }
        )

    # Minute-level runtime health (latest file content only).
    soft_pause_rows = sum(1 for r in minute if str(r.get("soft_pause_edge", "")).lower() == "true")
    stale_rows = sum(1 for r in minute if str(r.get("order_book_stale", "")).lower() == "true")
    max_drawdown = max((_safe_float(r.get("drawdown_pct")) for r in minute), default=0.0)

    # External service health snapshots.
    recon = _read_json(root / "reports" / "reconciliation" / "latest.json")
    portfolio = _read_json(root / "reports" / "portfolio_risk" / "latest.json")
    strict_cycle = _read_json(root / "reports" / "promotion_gates" / "strict_cycle_latest.json")

    # Simple gate checks for operator quick-read.
    total_net = sum(_safe_float(d["net_pnl_quote"]) for d in day_rows)
    mean_fee_bps = (sum(_safe_float(d["fee_bps"]) for d in day_rows) / len(day_rows)) if day_rows else 0.0
    mean_maker_ratio = (sum(_safe_float(d["maker_ratio"]) for d in day_rows) / len(day_rows)) if day_rows else 0.0
    max_slippage_p95 = max((_safe_float(d["slippage_p95_bps"]) for d in day_rows), default=0.0)
    soft_pause_ratio = (soft_pause_rows / len(minute)) if minute else 0.0

    checks = [
        {
            "name": "net_pnl_non_negative",
            "pass": total_net >= 0.0,
            "value": total_net,
            "threshold": 0.0,
        },
        {
            "name": "mean_fee_bps_within_0_to_12",
            "pass": 0.0 <= mean_fee_bps <= 12.0,
            "value": mean_fee_bps,
            "threshold": [0.0, 12.0],
        },
        {
            "name": "maker_ratio_at_least_45pct",
            "pass": mean_maker_ratio >= 0.45,
            "value": mean_maker_ratio,
            "threshold": 0.45,
        },
        {
            "name": "slippage_p95_below_25bps",
            "pass": max_slippage_p95 < 25.0,
            "value": max_slippage_p95,
            "threshold": 25.0,
        },
        {
            "name": "drawdown_below_2pct",
            "pass": max_drawdown < 0.02,
            "value": max_drawdown,
            "threshold": 0.02,
        },
        {
            "name": "soft_pause_ratio_below_30pct",
            "pass": soft_pause_ratio < 0.30,
            "value": soft_pause_ratio,
            "threshold": 0.30,
        },
        {
            "name": "reconciliation_not_critical",
            "pass": _safe_float(recon.get("critical_count"), 0.0) == 0.0,
            "value": _safe_float(recon.get("critical_count"), 0.0),
            "threshold": 0.0,
        },
        {
            "name": "portfolio_risk_not_critical",
            "pass": _safe_float(portfolio.get("critical_count"), 0.0) == 0.0,
            "value": _safe_float(portfolio.get("critical_count"), 0.0),
            "threshold": 0.0,
        },
    ]
    status = "pass" if all(bool(c["pass"]) for c in checks) else "warning"

    return {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "bot_log_root": str(bot_log_root),
        "lookback_days": lookback_days,
        "summary": {
            "days_included": len(day_rows),
            "total_net_pnl_quote": total_net,
            "mean_fee_bps": mean_fee_bps,
            "mean_maker_ratio": mean_maker_ratio,
            "max_slippage_p95_bps": max_slippage_p95,
            "max_drawdown_pct": max_drawdown,
            "soft_pause_ratio": soft_pause_ratio,
            "order_book_stale_rows": stale_rows,
        },
        "checks": checks,
        "daily_breakdown": day_rows,
        "external": {
            "reconciliation": {
                "status": recon.get("status"),
                "critical_count": recon.get("critical_count"),
                "warning_count": recon.get("warning_count"),
            },
            "portfolio_risk": {
                "status": portfolio.get("status"),
                "critical_count": portfolio.get("critical_count"),
                "warning_count": portfolio.get("warning_count"),
            },
            "strict_cycle": {
                "status": strict_cycle.get("strict_gate_status"),
                "rc": strict_cycle.get("strict_gate_rc"),
            },
        },
    }


def _to_markdown(dossier: Dict[str, object]) -> str:
    summary = dossier.get("summary", {})
    checks = dossier.get("checks", [])
    rows = dossier.get("daily_breakdown", [])
    md = [
        "# Performance Dossier",
        "",
        f"- Generated: `{dossier.get('ts_utc', '')}`",
        f"- Status: **{dossier.get('status', 'unknown').upper()}**",
        f"- Days included: `{summary.get('days_included', 0)}`",
        f"- Total net PnL: `{summary.get('total_net_pnl_quote', 0):.4f}`",
        f"- Mean fee bps: `{summary.get('mean_fee_bps', 0):.2f}`",
        f"- Mean maker ratio: `{summary.get('mean_maker_ratio', 0):.2%}`",
        f"- Max p95 slippage: `{summary.get('max_slippage_p95_bps', 0):.2f}` bps",
        f"- Max drawdown: `{summary.get('max_drawdown_pct', 0):.2%}`",
        "",
        "## Checks",
    ]
    for c in checks:
        status = "PASS" if c.get("pass") else "FAIL"
        md.append(f"- [{status}] `{c.get('name')}` value=`{c.get('value')}` threshold=`{c.get('threshold')}`")
    md.append("")
    md.append("## Daily Breakdown")
    md.append("| day | fills | net_pnl | fee_bps | maker_ratio | slippage_p95_bps |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for r in rows:
        md.append(
            f"| {r.get('day')} | {r.get('fills')} | {float(r.get('net_pnl_quote', 0)):.4f} | "
            f"{float(r.get('fee_bps', 0)):.2f} | {float(r.get('maker_ratio', 0)):.2%} | "
            f"{float(r.get('slippage_p95_bps', 0)):.2f} |"
        )
    return "\n".join(md) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate performance dossier for bot logs.")
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    parser.add_argument("--root", default=str(root))
    parser.add_argument("--bot-log-root", default=str(root / "data" / "bot1" / "logs" / "epp_v24" / "bot1_a"))
    parser.add_argument("--lookback-days", type=int, default=5)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    repo_root = Path(args.root)
    bot_root = Path(args.bot_log_root)
    dossier = build_dossier(repo_root, bot_root, lookback_days=max(1, args.lookback_days))
    print(json.dumps(dossier, indent=2))

    if args.save:
        out_dir = repo_root / "reports" / "analysis"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "performance_dossier_latest.json").write_text(json.dumps(dossier, indent=2), encoding="utf-8")
        (out_dir / "performance_dossier_latest.md").write_text(_to_markdown(dossier), encoding="utf-8")
        print(f"[performance-dossier] saved to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
