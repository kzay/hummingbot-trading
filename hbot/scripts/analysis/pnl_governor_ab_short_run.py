#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from scripts.analysis.pnl_governor_ab_tuning import _build_report, _compute_metrics, _utc_now


def _run_window(
    *,
    hours: int,
    a_root: str,
    b_root: str,
    single_root: str,
    label_a: str,
    label_b: str,
) -> Dict:
    until = _utc_now()
    since = until
    if hours > 0:
        from datetime import timedelta

        since = until - timedelta(hours=hours)

    if single_root:
        from datetime import timedelta

        root = Path(single_root)
        a_until = since
        a_since = a_until - timedelta(hours=hours)
        b_since = since
        b_until = until
        a_metrics = _compute_metrics(root, a_since, a_until)
        b_metrics = _compute_metrics(root, b_since, b_until)
        report = _build_report(label_a, label_b, a_metrics, b_metrics, hours, b_since, b_until)
        report["mode"] = "single_root_sequential"
        report["A"]["window"] = {"since_utc": a_since.isoformat(), "until_utc": a_until.isoformat()}
        report["B"]["window"] = {"since_utc": b_since.isoformat(), "until_utc": b_until.isoformat()}
        return report

    a_metrics = _compute_metrics(Path(a_root), since, until)
    b_metrics = _compute_metrics(Path(b_root), since, until)
    report = _build_report(label_a, label_b, a_metrics, b_metrics, hours, since, until)
    report["mode"] = "two_root_parallel"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run short A/B tuning windows (2h and 24h).")
    parser.add_argument("--a-root", default="", help="Path to profile A log root.")
    parser.add_argument("--b-root", default="", help="Path to profile B log root.")
    parser.add_argument("--single-root", default="", help="Compare previous vs latest windows on one root.")
    parser.add_argument("--label-a", default="A")
    parser.add_argument("--label-b", default="B")
    parser.add_argument("--out-dir", default="", help="Optional output directory.")
    args = parser.parse_args()

    if not args.single_root and (not args.a_root or not args.b_root):
        raise SystemExit("Provide both --a-root and --b-root, or use --single-root")

    reports = {
        "2h": _run_window(
            hours=2,
            a_root=args.a_root,
            b_root=args.b_root,
            single_root=args.single_root,
            label_a=args.label_a,
            label_b=args.label_b,
        ),
        "24h": _run_window(
            hours=24,
            a_root=args.a_root,
            b_root=args.b_root,
            single_root=args.single_root,
            label_a=args.label_a,
            label_b=args.label_b,
        ),
    }

    root = Path(__file__).resolve().parents[2]
    out_dir = Path(args.out_dir) if args.out_dir else root / "reports" / "strategy"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_2h = out_dir / "pnl_governor_ab_2h_latest.json"
    out_24h = out_dir / "pnl_governor_ab_24h_latest.json"
    out_combined = out_dir / "pnl_governor_ab_short_run_latest.json"

    out_2h.write_text(json.dumps(reports["2h"], indent=2), encoding="utf-8")
    out_24h.write_text(json.dumps(reports["24h"], indent=2), encoding="utf-8")
    combined = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "reports": reports,
    }
    out_combined.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    print(f"[ab-short-run] wrote {out_2h}")
    print(f"[ab-short-run] wrote {out_24h}")
    print(f"[ab-short-run] wrote {out_combined}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
