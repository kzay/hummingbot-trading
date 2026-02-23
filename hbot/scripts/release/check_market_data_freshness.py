from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _latest_events_file(event_store_dir: Path) -> Path | None:
    files = sorted(event_store_dir.glob("events_*.jsonl"))
    return files[-1] if files else None


def _minutes_since_mtime(path: Path) -> float:
    try:
        ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 60.0
    except Exception:
        return 1e9


def _count_market_data_rows(path: Path) -> int:
    # Fast substring check is sufficient for contract validation.
    target = '"stream":"hb.market_data.v1"'
    count = 0
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if target in line.replace(" ", ""):
                    count += 1
    except Exception:
        return 0
    return count


def _write_report(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate event-store market data freshness.")
    parser.add_argument("--max-age-min", type=float, default=20.0, help="Max allowed age in minutes for events JSONL.")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    event_store_dir = root / "reports" / "event_store"
    out_dir = root / "reports" / "market_data"
    out_dir.mkdir(parents=True, exist_ok=True)

    latest_file = _latest_events_file(event_store_dir)
    file_exists = latest_file is not None and latest_file.exists()
    age_min = _minutes_since_mtime(latest_file) if latest_file else 1e9
    row_count = _count_market_data_rows(latest_file) if latest_file else 0

    fresh = file_exists and age_min <= float(args.max_age_min)
    has_market_data = row_count > 0
    ok = bool(fresh and has_market_data)

    payload = {
        "ts_utc": _utc_now(),
        "status": "pass" if ok else "fail",
        "max_age_min": float(args.max_age_min),
        "events_file": str(latest_file) if latest_file else "",
        "events_file_exists": bool(file_exists),
        "events_file_age_min": round(float(age_min), 3),
        "market_data_event_rows": int(row_count),
        "checks": {
            "events_file_fresh": bool(fresh),
            "market_data_rows_present": bool(has_market_data),
        },
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"market_data_freshness_{stamp}.json"
    _write_report(out, payload)
    _write_report(out_dir / "latest.json", payload)

    print(f"[market-data-freshness] status={payload['status']}")
    print(f"[market-data-freshness] evidence={out}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
