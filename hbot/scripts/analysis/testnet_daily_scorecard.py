#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, Iterable, List


MICRO_BENCHMARK_THRESHOLDS = {
    "max_fill_rate_delta": 0.50,
    "max_slippage_delta_bps": 10.0,
    "max_reject_rate_delta": 0.05,
    "max_cancel_before_fill_rate_delta": 0.20,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str) -> datetime | None:
    s = (value or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _iter_csv(path: Path) -> Iterable[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def _filter_day(rows: Iterable[Dict[str, str]], day: str) -> List[Dict[str, str]]:
    d = date.fromisoformat(day)
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    out: List[Dict[str, str]] = []
    for row in rows:
        ts = _parse_ts(row.get("ts", ""))
        if ts is None:
            continue
        if start <= ts < end:
            out.append(row)
    return out


def _safe_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _is_truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "y"}


def _daily_net_pnl(rows: List[Dict[str, str]]) -> tuple[float, float, float]:
    realized = sum((_safe_decimal(r.get("realized_pnl_quote", "0")) for r in rows), Decimal("0"))
    fees = sum((_safe_decimal(r.get("fee_quote", "0")) for r in rows), Decimal("0"))
    net = realized - fees
    return float(net), float(realized), float(fees)


def _hard_stop_incidents(rows: List[Dict[str, str]]) -> tuple[int, int]:
    """Return (hard_stop_row_count, hard_stop_transition_count)."""
    hard_stop_row_count = 0
    hard_stop_transition_count = 0
    was_hard_stop = False
    for row in rows:
        state = str(row.get("state", "")).strip().lower()
        hard_stop_now = (
            state == "hard_stop"
            or _is_truthy(row.get("hard_stop"))
            or _is_truthy(row.get("is_hard_stop"))
        )
        if hard_stop_now:
            hard_stop_row_count += 1
        if hard_stop_now and not was_hard_stop:
            hard_stop_transition_count += 1
        was_hard_stop = hard_stop_now
    return hard_stop_row_count, hard_stop_transition_count


def _repo_root() -> Path:
    if Path("/.dockerenv").exists():
        return Path("/workspace/hbot")
    return Path(__file__).resolve().parents[2]


def _reject_rate(rows: List[Dict[str, str]]) -> tuple[int, float]:
    rejected = sum(
        1
        for r in rows
        if str(r.get("event_type", "")).strip().lower() in {"order_rejected", "reject"}
        or str(r.get("status", "")).strip().lower() in {"rejected", "failed"}
    )
    rate = (rejected / len(rows)) if rows else 0.0
    return rejected, rate


def _avg_slippage_bps(rows: List[Dict[str, str]]) -> float:
    samples = [_safe_float(r.get("pnl_vs_mid_pct", "0")) * 10000.0 for r in rows if r.get("pnl_vs_mid_pct") not in (None, "")]
    return (sum(samples) / len(samples)) if samples else 0.0


def _cancel_before_fill_rate(rows: List[Dict[str, str]]) -> tuple[int, float]:
    count = sum(
        1
        for r in rows
        if _safe_float(r.get("cancel_per_min", "0")) > 0 and _safe_float(r.get("fills_count_today", "0")) == 0
    )
    rate = (count / len(rows)) if rows else 0.0
    return count, rate


def build_scorecard(day: str, testnet_root: Path, paper_root: Path, reports_root: Path) -> Dict:
    testnet_fills = _filter_day(_iter_csv(testnet_root / "fills.csv"), day)
    paper_fills = _filter_day(_iter_csv(paper_root / "fills.csv"), day)
    testnet_minute = _filter_day(_iter_csv(testnet_root / "minute.csv"), day)
    paper_minute = _filter_day(_iter_csv(paper_root / "minute.csv"), day)

    testnet_fill_count = len(testnet_fills)
    paper_fill_count = len(paper_fills)
    fill_count_ratio = (testnet_fill_count / paper_fill_count) if paper_fill_count > 0 else 0.0
    testnet_fill_rate = (testnet_fill_count / len(testnet_minute)) if testnet_minute else 0.0
    paper_fill_rate = (paper_fill_count / len(paper_minute)) if paper_minute else 0.0

    rejection_count, rejection_rate = _reject_rate(testnet_fills)
    paper_rejection_count, paper_rejection_rate = _reject_rate(paper_fills)

    avg_testnet_slippage_bps = _avg_slippage_bps(testnet_fills)
    avg_paper_slippage_bps = _avg_slippage_bps(paper_fills)

    cancel_before_fill, cancel_before_fill_rate = _cancel_before_fill_rate(testnet_minute)
    paper_cancel_before_fill, paper_cancel_before_fill_rate = _cancel_before_fill_rate(paper_minute)
    testnet_net_pnl_quote, testnet_realized_pnl_quote, testnet_fees_quote = _daily_net_pnl(testnet_fills)
    paper_net_pnl_quote, paper_realized_pnl_quote, paper_fees_quote = _daily_net_pnl(paper_fills)
    hard_stop_row_count, hard_stop_incident_count = _hard_stop_incidents(testnet_minute)

    drift_alarm_count = sum(
        1 for r in testnet_minute if _safe_float(r.get("position_drift_pct", "0")) > 0.01
    )

    status = "pass"
    failures: List[str] = []
    # "no_testnet_fills" should only fire when testnet has zero fills.
    # A missing paper baseline (paper_fill_count == 0) should not erase
    # real testnet activity.
    if testnet_fill_count == 0:
        status = "fail"
        failures.append("no_testnet_fills")
    if rejection_rate > 0.005:
        status = "fail"
        failures.append("rejection_rate_gt_0_5pct")
    if hard_stop_incident_count > 0:
        status = "fail"
        failures.append("hard_stop_incident_detected")

    benchmark_checks: List[Dict[str, object]] = []
    benchmark_status = "insufficient_data"
    # Require both fills and minute baselines on each side before evaluating
    # fill-rate/cancel-rate deltas; otherwise mark micro-benchmark inconclusive.
    if testnet_fill_count > 0 and paper_fill_count > 0 and testnet_minute and paper_minute:
        benchmark_status = "pass"
        fill_rate_delta = abs(testnet_fill_rate - paper_fill_rate)
        slippage_delta_bps = abs(avg_testnet_slippage_bps - avg_paper_slippage_bps)
        reject_rate_delta = abs(rejection_rate - paper_rejection_rate)
        cancel_before_fill_rate_delta = abs(cancel_before_fill_rate - paper_cancel_before_fill_rate)
        benchmark_checks = [
            {
                "name": "fill_rate_delta",
                "pass": fill_rate_delta <= MICRO_BENCHMARK_THRESHOLDS["max_fill_rate_delta"],
                "delta": fill_rate_delta,
                "max_allowed": MICRO_BENCHMARK_THRESHOLDS["max_fill_rate_delta"],
            },
            {
                "name": "slippage_delta_bps",
                "pass": slippage_delta_bps <= MICRO_BENCHMARK_THRESHOLDS["max_slippage_delta_bps"],
                "delta": slippage_delta_bps,
                "max_allowed": MICRO_BENCHMARK_THRESHOLDS["max_slippage_delta_bps"],
            },
            {
                "name": "reject_rate_delta",
                "pass": reject_rate_delta <= MICRO_BENCHMARK_THRESHOLDS["max_reject_rate_delta"],
                "delta": reject_rate_delta,
                "max_allowed": MICRO_BENCHMARK_THRESHOLDS["max_reject_rate_delta"],
            },
            {
                "name": "cancel_before_fill_rate_delta",
                "pass": cancel_before_fill_rate_delta
                <= MICRO_BENCHMARK_THRESHOLDS["max_cancel_before_fill_rate_delta"],
                "delta": cancel_before_fill_rate_delta,
                "max_allowed": MICRO_BENCHMARK_THRESHOLDS["max_cancel_before_fill_rate_delta"],
            },
        ]
        if not all(bool(c["pass"]) for c in benchmark_checks):
            benchmark_status = "fail"
            status = "fail"
            failures.append("paper_vs_testnet_micro_benchmark_failed")

    return {
        "ts_utc": _utc_now(),
        "day": day,
        "status": status,
        "failures": failures,
        "inputs": {
            "testnet_root": str(testnet_root),
            "paper_root": str(paper_root),
            "reports_root": str(reports_root),
        },
        "metrics": {
            "testnet_fill_count": testnet_fill_count,
            "paper_fill_count": paper_fill_count,
            "fill_count_ratio": fill_count_ratio,
            "testnet_fill_rate": testnet_fill_rate,
            "paper_fill_rate": paper_fill_rate,
            "avg_testnet_slippage_bps": avg_testnet_slippage_bps,
            "avg_paper_slippage_bps": avg_paper_slippage_bps,
            "rejection_count": rejection_count,
            "rejection_rate": rejection_rate,
            "paper_rejection_count": paper_rejection_count,
            "paper_rejection_rate": paper_rejection_rate,
            "cancel_before_fill_rate": cancel_before_fill_rate,
            "paper_cancel_before_fill_rate": paper_cancel_before_fill_rate,
            "testnet_net_pnl_quote": testnet_net_pnl_quote,
            "testnet_realized_pnl_quote": testnet_realized_pnl_quote,
            "testnet_fees_quote": testnet_fees_quote,
            "paper_net_pnl_quote": paper_net_pnl_quote,
            "paper_realized_pnl_quote": paper_realized_pnl_quote,
            "paper_fees_quote": paper_fees_quote,
            "hard_stop_row_count": hard_stop_row_count,
            "hard_stop_incident_count": hard_stop_incident_count,
            "drift_alarm_count": drift_alarm_count,
        },
        "micro_benchmark": {
            "status": benchmark_status,
            "thresholds": MICRO_BENCHMARK_THRESHOLDS,
            "checks": benchmark_checks,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate ROAD-5 testnet daily scorecard.")
    parser.add_argument("--day", required=True, help="UTC day YYYY-MM-DD")
    root = _repo_root()
    parser.add_argument("--testnet-root", default=str(root / "data" / "bot1" / "logs" / "epp_v24" / "bot1_a"))
    parser.add_argument("--paper-root", default=str(root / "data" / "bot3" / "logs" / "epp_v24" / "bot3_a"))
    parser.add_argument("--reports-root", default=str(root / "reports"))
    args = parser.parse_args()

    testnet_root = Path(args.testnet_root)
    paper_root = Path(args.paper_root)
    reports_root = Path(args.reports_root)

    payload = build_scorecard(args.day, testnet_root=testnet_root, paper_root=paper_root, reports_root=reports_root)
    out_dir = reports_root / "strategy"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts_out = out_dir / f"testnet_daily_scorecard_{args.day.replace('-', '')}.json"
    latest_out = out_dir / "testnet_daily_scorecard_latest.json"
    raw = json.dumps(payload, indent=2)
    ts_out.write_text(raw, encoding="utf-8")
    latest_out.write_text(raw, encoding="utf-8")
    print(f"[testnet-scorecard] status={payload['status']}")
    print(f"[testnet-scorecard] evidence={latest_out}")
    return 0 if payload["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
