#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _utc_now() -> datetime:
    return datetime.now(UTC)


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


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _iter_csv(path: Path) -> Iterable[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def _filter_window(rows: Iterable[dict[str, str]], since: datetime, until: datetime) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        ts = _parse_ts(str(row.get("ts", "")))
        if ts is None:
            continue
        if since <= ts <= until:
            out.append(row)
    return out


@dataclass
class WindowMetrics:
    root: str
    minute_rows: int
    fill_rows: int
    fills_per_hour: float
    avg_spread_bps: float
    avg_net_edge_bps: float
    avg_turnover_x: float
    avg_pnl_governor_deficit_ratio: float
    pnl_governor_active_rate: float
    size_boost_active_rate: float
    avg_size_mult: float
    net_realized_delta_quote: float
    governor_activation_reason_counts: dict[str, int]
    governor_size_boost_reason_counts: dict[str, int]
    dominant_activation_block_reason: str
    dominant_size_boost_block_reason: str


def _reason_counts(rows: list[dict[str, str]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        reason = str(row.get(key, "")).strip() or "unknown"
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _dominant_block_reason(counts: dict[str, int]) -> str:
    blocked = {k: v for k, v in counts.items() if k not in {"active"}}
    if not blocked:
        return "none"
    return max(sorted(blocked.keys()), key=lambda k: blocked.get(k, 0))


def _compute_metrics(root: Path, since: datetime, until: datetime) -> WindowMetrics:
    minute_rows = _filter_window(_iter_csv(root / "minute.csv"), since, until)
    fill_rows = _filter_window(_iter_csv(root / "fills.csv"), since, until)
    hrs = max(1e-6, (until - since).total_seconds() / 3600.0)

    spread_samples = [_safe_float(r.get("spread_pct", 0.0)) * 10000.0 for r in minute_rows]
    edge_samples = [_safe_float(r.get("net_edge_pct", 0.0)) * 10000.0 for r in minute_rows]
    turnover_samples = [_safe_float(r.get("turnover_today_x", 0.0)) for r in minute_rows]
    deficit_samples = [_safe_float(r.get("pnl_governor_deficit_ratio", 0.0)) for r in minute_rows]
    size_mult_samples = [_safe_float(r.get("pnl_governor_size_mult", 1.0), 1.0) for r in minute_rows]
    governor_active = sum(1 for r in minute_rows if _safe_bool(r.get("pnl_governor_active", False)))
    size_boost_active = sum(1 for r in minute_rows if _safe_bool(r.get("pnl_governor_size_boost_active", False)))
    activation_reason_counts = _reason_counts(minute_rows, "pnl_governor_activation_reason")
    size_reason_counts = _reason_counts(minute_rows, "pnl_governor_size_boost_reason")

    net_realized_start = _safe_float(minute_rows[0].get("net_realized_pnl_today_quote", 0.0)) if minute_rows else 0.0
    net_realized_end = _safe_float(minute_rows[-1].get("net_realized_pnl_today_quote", 0.0)) if minute_rows else 0.0

    def _avg(samples: list[float], default: float = 0.0) -> float:
        return sum(samples) / len(samples) if samples else default

    return WindowMetrics(
        root=str(root),
        minute_rows=len(minute_rows),
        fill_rows=len(fill_rows),
        fills_per_hour=(len(fill_rows) / hrs),
        avg_spread_bps=_avg(spread_samples),
        avg_net_edge_bps=_avg(edge_samples),
        avg_turnover_x=_avg(turnover_samples),
        avg_pnl_governor_deficit_ratio=_avg(deficit_samples),
        pnl_governor_active_rate=(governor_active / len(minute_rows)) if minute_rows else 0.0,
        size_boost_active_rate=(size_boost_active / len(minute_rows)) if minute_rows else 0.0,
        avg_size_mult=_avg(size_mult_samples, 1.0),
        net_realized_delta_quote=(net_realized_end - net_realized_start),
        governor_activation_reason_counts=activation_reason_counts,
        governor_size_boost_reason_counts=size_reason_counts,
        dominant_activation_block_reason=_dominant_block_reason(activation_reason_counts),
        dominant_size_boost_block_reason=_dominant_block_reason(size_reason_counts),
    )


def _build_report(
    label_a: str,
    label_b: str,
    metrics_a: WindowMetrics,
    metrics_b: WindowMetrics,
    hours: int,
    since: datetime,
    until: datetime,
) -> dict:
    return {
        "ts_utc": _utc_now().isoformat(),
        "window_hours": hours,
        "window": {"since_utc": since.isoformat(), "until_utc": until.isoformat()},
        "A": {"label": label_a, **metrics_a.__dict__},
        "B": {"label": label_b, **metrics_b.__dict__},
        "delta_b_minus_a": {
            "fills_per_hour": metrics_b.fills_per_hour - metrics_a.fills_per_hour,
            "avg_spread_bps": metrics_b.avg_spread_bps - metrics_a.avg_spread_bps,
            "avg_net_edge_bps": metrics_b.avg_net_edge_bps - metrics_a.avg_net_edge_bps,
            "avg_turnover_x": metrics_b.avg_turnover_x - metrics_a.avg_turnover_x,
            "net_realized_delta_quote": metrics_b.net_realized_delta_quote - metrics_a.net_realized_delta_quote,
            "pnl_governor_active_rate": metrics_b.pnl_governor_active_rate - metrics_a.pnl_governor_active_rate,
            "size_boost_active_rate": metrics_b.size_boost_active_rate - metrics_a.size_boost_active_rate,
            "avg_size_mult": metrics_b.avg_size_mult - metrics_a.avg_size_mult,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="A/B tuning window report for PnL-governor and sizing changes.")
    parser.add_argument("--a-root", default="", help="Path to profile A bot log root (contains minute.csv/fills.csv).")
    parser.add_argument("--b-root", default="", help="Path to profile B bot log root (contains minute.csv/fills.csv).")
    parser.add_argument(
        "--single-root",
        default="",
        help="Use one root and compare previous window (A) vs latest window (B). Overrides --a-root/--b-root.",
    )
    parser.add_argument("--label-a", default="A")
    parser.add_argument("--label-b", default="B")
    parser.add_argument("--hours", type=int, required=True, choices=[2, 24], help="Comparison window in hours.")
    parser.add_argument("--out", default="", help="Optional explicit output path.")
    args = parser.parse_args()

    until = _utc_now()
    hours = int(args.hours)
    since = until - timedelta(hours=hours)

    if args.single_root:
        root = Path(args.single_root)
        a_until = since
        a_since = a_until - timedelta(hours=hours)
        b_since = since
        b_until = until
        a_metrics = _compute_metrics(root, a_since, a_until)
        b_metrics = _compute_metrics(root, b_since, b_until)
        report = _build_report(args.label_a, args.label_b, a_metrics, b_metrics, hours, b_since, b_until)
        report["mode"] = "single_root_sequential"
        report["A"]["window"] = {"since_utc": a_since.isoformat(), "until_utc": a_until.isoformat()}
        report["B"]["window"] = {"since_utc": b_since.isoformat(), "until_utc": b_until.isoformat()}
    else:
        if not args.a_root or not args.b_root:
            raise SystemExit("Provide both --a-root and --b-root, or use --single-root")
        a_root = Path(args.a_root)
        b_root = Path(args.b_root)
        a_metrics = _compute_metrics(a_root, since, until)
        b_metrics = _compute_metrics(b_root, since, until)
        report = _build_report(args.label_a, args.label_b, a_metrics, b_metrics, hours, since, until)
        report["mode"] = "two_root_parallel"

    if args.out:
        out_path = Path(args.out)
    else:
        root = Path(__file__).resolve().parents[2]
        out_dir = root / "reports" / "strategy"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"pnl_governor_ab_{int(args.hours)}h_latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[ab-tuning] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
