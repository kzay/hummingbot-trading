from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _parse_iso_ts(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _row_timestamp(row: Dict[str, str], fieldnames: List[str]) -> datetime | None:
    candidates = ["ts", "timestamp", "ts_utc", "timestamp_utc", "time", "datetime"]
    for key in candidates:
        if key in row:
            parsed = _parse_iso_ts(row.get(key, ""))
            if parsed is not None:
                return parsed
    if fieldnames:
        parsed = _parse_iso_ts(row.get(fieldnames[0], ""))
        if parsed is not None:
            return parsed
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate no-trade behavior from minute.csv window.")
    parser.add_argument("--minute-csv", required=True, help="Path to minute.csv artifact.")
    parser.add_argument("--expected-exchange", default="", help="Expected exchange value in rows.")
    parser.add_argument(
        "--exchange-filter",
        default="",
        help="Filter rows to a single exchange before validation (e.g. bitget_perpetual).",
    )
    parser.add_argument(
        "--since-minutes",
        type=int,
        default=0,
        help="Only keep rows with timestamp >= now - since_minutes (0 disables).",
    )
    parser.add_argument("--min-samples", type=int, default=10, help="Minimum sample rows required.")
    args = parser.parse_args()

    minute_path = Path(args.minute_csv)
    if not minute_path.exists():
        print(f"[notrade-validate] missing_file={minute_path}")
        return 2

    rows: List[Dict[str, str]] = []
    fieldnames: List[str] = []
    with minute_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = [name for name in (reader.fieldnames or []) if name]
        for row in reader:
            rows.append(row)

    total_rows_read = len(rows)
    if total_rows_read == 0:
        print("[notrade-validate] no rows found")
        return 2

    if args.exchange_filter:
        rows = [
            r
            for r in rows
            if str(r.get("exchange", "")).strip() == str(args.exchange_filter).strip()
        ]

    if int(args.since_minutes) > 0:
        cutoff = datetime.now(timezone.utc).timestamp() - int(args.since_minutes) * 60
        filtered_rows: List[Dict[str, str]] = []
        for row in rows:
            row_ts = _row_timestamp(row, fieldnames=fieldnames)
            if row_ts is not None and row_ts.timestamp() >= cutoff:
                filtered_rows.append(row)
        rows = filtered_rows

    sample_count = len(rows)
    if sample_count == 0:
        print("[notrade-validate] no rows found after filters")
        return 2

    fills_series = [_to_float(r.get("fills_count_today", "0")) for r in rows]
    orders_active_series = [_to_float(r.get("orders_active", "0")) for r in rows]
    fills_increase = (max(fills_series) - min(fills_series)) if fills_series else 0.0
    max_orders_active = max(orders_active_series) if orders_active_series else 0.0

    exchange_ok = True
    if args.expected_exchange:
        exchange_ok = all(str(r.get("exchange", "")).strip() == args.expected_exchange for r in rows)

    checks = {
        "min_samples": sample_count >= max(1, args.min_samples),
        "exchange_match": exchange_ok,
        "fills_not_increasing": fills_increase <= 0.0,
        "orders_active_zero": max_orders_active <= 0.0,
    }
    status = "pass" if all(checks.values()) else "fail"

    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "minute_csv": str(minute_path),
        "total_rows_read": total_rows_read,
        "rows_filtered_out": total_rows_read - sample_count,
        "sample_count": sample_count,
        "expected_exchange": args.expected_exchange,
        "exchange_filter": args.exchange_filter,
        "since_minutes": int(args.since_minutes),
        "fills_increase": fills_increase,
        "max_orders_active": max_orders_active,
        "checks": checks,
    }

    out_dir = Path("reports/notrade_validation")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"notrade_validation_{stamp}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_dir / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"[notrade-validate] status={status}")
    print(f"[notrade-validate] evidence={out}")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
