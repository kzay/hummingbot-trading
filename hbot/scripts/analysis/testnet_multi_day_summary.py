#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, date, datetime
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _repo_root() -> Path:
    if Path("/.dockerenv").exists():
        return Path("/workspace/hbot")
    return Path(__file__).resolve().parents[2]


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _extract_day_from_filename(path: Path) -> str | None:
    stem = path.stem
    prefix = "testnet_daily_scorecard_"
    if not stem.startswith(prefix):
        return None
    suffix = stem[len(prefix):]
    if len(suffix) != 8 or not suffix.isdigit():
        return None
    return f"{suffix[0:4]}-{suffix[4:6]}-{suffix[6:8]}"


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _annualized_sharpe(daily_pnl: list[float]) -> float:
    if len(daily_pnl) < 2:
        return 0.0
    n = len(daily_pnl)
    mean = sum(daily_pnl) / float(n)
    variance = sum((x - mean) ** 2 for x in daily_pnl) / float(n)
    if variance <= 0:
        return 0.0
    std = math.sqrt(variance)
    if std <= 0:
        return 0.0
    return (mean / std) * math.sqrt(252.0)


def build_summary(
    *,
    reports_root: Path,
    start: str = "",
    end: str = "",
) -> dict[str, object]:
    strategy_root = reports_root / "strategy"
    scorecard_paths = sorted(strategy_root.glob("testnet_daily_scorecard_*.json"))
    d0 = date.fromisoformat(start) if str(start).strip() else None
    d1 = date.fromisoformat(end) if str(end).strip() else None

    rows: list[dict[str, object]] = []
    warnings: list[str] = []
    for path in scorecard_paths:
        day_str = _extract_day_from_filename(path)
        if day_str is None:
            continue
        day_obj = date.fromisoformat(day_str)
        if d0 is not None and day_obj < d0:
            continue
        if d1 is not None and day_obj > d1:
            continue

        payload = _read_json(path)
        if not payload:
            warnings.append(f"invalid_payload:{path.name}")
            continue
        metrics = payload.get("metrics", {})
        metrics = metrics if isinstance(metrics, dict) else {}
        rows.append(
            {
                "day": day_str,
                "status": str(payload.get("status", "")).strip().lower(),
                "path": str(path),
                "testnet_fill_count": _safe_int(metrics.get("testnet_fill_count", 0)),
                "paper_fill_count": _safe_int(metrics.get("paper_fill_count", 0)),
                "rejection_count": _safe_int(metrics.get("rejection_count", 0)),
                "avg_testnet_slippage_bps": _safe_float(metrics.get("avg_testnet_slippage_bps", 0.0)),
                "avg_paper_slippage_bps": _safe_float(metrics.get("avg_paper_slippage_bps", 0.0)),
                "hard_stop_incident_count": _safe_int(metrics.get("hard_stop_incident_count", 0)),
                "testnet_net_pnl_quote": _safe_float(metrics.get("testnet_net_pnl_quote", 0.0)),
                "paper_net_pnl_quote": _safe_float(metrics.get("paper_net_pnl_quote", 0.0)),
            }
        )

    rows.sort(key=lambda r: str(r.get("day", "")))

    coverage_days = len(rows)
    trading_days = sum(1 for r in rows if int(r.get("testnet_fill_count", 0) or 0) > 0)
    passing_days = sum(1 for r in rows if str(r.get("status", "")).lower() == "pass")

    total_testnet_fills = sum(int(r.get("testnet_fill_count", 0) or 0) for r in rows)
    total_paper_fills = sum(int(r.get("paper_fill_count", 0) or 0) for r in rows)
    total_rejections = sum(int(r.get("rejection_count", 0) or 0) for r in rows)
    hard_stop_incident_days = sum(1 for r in rows if int(r.get("hard_stop_incident_count", 0) or 0) > 0)
    hard_stop_incident_total = sum(int(r.get("hard_stop_incident_count", 0) or 0) for r in rows)

    weighted_testnet_slippage = (
        sum(float(r.get("avg_testnet_slippage_bps", 0.0)) * int(r.get("testnet_fill_count", 0) or 0) for r in rows)
        / float(total_testnet_fills)
        if total_testnet_fills > 0
        else None
    )
    weighted_paper_slippage = (
        sum(float(r.get("avg_paper_slippage_bps", 0.0)) * int(r.get("paper_fill_count", 0) or 0) for r in rows)
        / float(total_paper_fills)
        if total_paper_fills > 0
        else None
    )
    slippage_delta_bps = (
        abs(float(weighted_testnet_slippage) - float(weighted_paper_slippage))
        if weighted_testnet_slippage is not None and weighted_paper_slippage is not None
        else None
    )

    rejection_rate = (float(total_rejections) / float(total_testnet_fills)) if total_testnet_fills > 0 else None

    # Compute Sharpe on matched active (testnet-trading) days.
    testnet_daily_pnl = [float(r.get("testnet_net_pnl_quote", 0.0)) for r in rows if int(r.get("testnet_fill_count", 0) or 0) > 0]
    paper_daily_pnl = [float(r.get("paper_net_pnl_quote", 0.0)) for r in rows if int(r.get("testnet_fill_count", 0) or 0) > 0]
    testnet_sharpe = _annualized_sharpe(testnet_daily_pnl)
    paper_sharpe = _annualized_sharpe(paper_daily_pnl)
    sharpe_ratio_vs_paper = (testnet_sharpe / paper_sharpe) if paper_sharpe > 0 else None

    road5_required_gate_criteria = [
        "calendar_coverage_days_gte_28",
        "trading_days_gte_20",
        "no_hard_stop_incidents",
        "slippage_delta_lt_2bps",
        "rejection_rate_lt_0_5pct",
        "testnet_sharpe_gte_0_8x_paper",
    ]
    road5_criteria = {
        "calendar_coverage_days_gte_28": coverage_days >= 28,
        "trading_days_gte_20": trading_days >= 20,
        "no_hard_stop_incidents": hard_stop_incident_total == 0,
        "slippage_delta_lt_2bps": slippage_delta_bps is not None and float(slippage_delta_bps) < 2.0,
        "rejection_rate_lt_0_5pct": rejection_rate is not None and float(rejection_rate) < 0.005,
        "testnet_sharpe_gte_0_8x_paper": (
            sharpe_ratio_vs_paper is not None and float(sharpe_ratio_vs_paper) >= 0.8
        ),
    }
    road5_failed_criteria = [k for k in road5_required_gate_criteria if not bool(road5_criteria.get(k, False))]
    road5_pass = len(road5_failed_criteria) == 0

    if coverage_days == 0:
        warnings.append("no_scorecards_in_window")
    if slippage_delta_bps is None:
        warnings.append("slippage_delta_unavailable")
    if rejection_rate is None:
        warnings.append("rejection_rate_unavailable")
    if sharpe_ratio_vs_paper is None:
        warnings.append("sharpe_ratio_vs_paper_unavailable_or_invalid")

    if rows:
        period_start = str(rows[0].get("day", ""))
        period_end = str(rows[-1].get("day", ""))
    else:
        period_start = str(start or "")
        period_end = str(end or "")

    return {
        "ts_utc": _utc_now(),
        "period": {
            "start": period_start,
            "end": period_end,
            "requested_start": str(start or ""),
            "requested_end": str(end or ""),
        },
        "coverage_days": int(coverage_days),
        "trading_days_count": int(trading_days),
        "passing_days_count": int(passing_days),
        "warnings": warnings,
        "metrics": {
            "total_testnet_fills": int(total_testnet_fills),
            "total_paper_fills": int(total_paper_fills),
            "total_rejections": int(total_rejections),
            "rejection_rate": rejection_rate,
            "weighted_avg_testnet_slippage_bps": weighted_testnet_slippage,
            "weighted_avg_paper_slippage_bps": weighted_paper_slippage,
            "slippage_delta_bps": slippage_delta_bps,
            "hard_stop_incident_days": int(hard_stop_incident_days),
            "hard_stop_incident_total": int(hard_stop_incident_total),
            "testnet_sharpe_annualized": float(testnet_sharpe),
            "paper_sharpe_annualized": float(paper_sharpe),
            "sharpe_ratio_vs_paper": sharpe_ratio_vs_paper,
        },
        "road5_gate": {
            "pass": bool(road5_pass),
            "required_gate_criteria": road5_required_gate_criteria,
            "criteria": road5_criteria,
            "failed_criteria": road5_failed_criteria,
        },
        "daily_breakdown": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate ROAD-5 testnet daily scorecards.")
    root = _repo_root()
    parser.add_argument("--start", default="", help="Optional start day YYYY-MM-DD (inclusive).")
    parser.add_argument("--end", default="", help="Optional end day YYYY-MM-DD (inclusive).")
    parser.add_argument("--reports-root", default=str(root / "reports"), help="Reports root path.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when ROAD-5 gate is not pass.")
    args = parser.parse_args()

    reports_root = Path(args.reports_root)
    payload = build_summary(
        reports_root=reports_root,
        start=str(args.start or ""),
        end=str(args.end or ""),
    )
    out_dir = reports_root / "strategy"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_ts = out_dir / f"testnet_multi_day_summary_{stamp}.json"
    out_latest = out_dir / "testnet_multi_day_summary_latest.json"
    raw = json.dumps(payload, indent=2)
    out_ts.write_text(raw, encoding="utf-8")
    out_latest.write_text(raw, encoding="utf-8")
    print(f"[testnet-multi-day-summary] road5_pass={payload.get('road5_gate', {}).get('pass', False)}")
    print(f"[testnet-multi-day-summary] evidence={out_latest}")
    if args.strict and not bool(payload.get("road5_gate", {}).get("pass", False)):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
