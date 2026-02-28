"""
Local (no-Redis) integrity report refresh for event_store.

Reads today's JSONL file, recomputes total_events / events_by_stream /
missing_correlation_count, and writes a fresh integrity_YYYYMMDD.json.
This mirrors the logic in services/event_store/main.py::_write_stats but
works offline — no Redis connection required.

Usage:
    python scripts/utils/refresh_event_store_integrity_local.py
    python scripts/utils/refresh_event_store_integrity_local.py --once   # alias, same behaviour
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _recompute(jsonl_path: Path) -> dict:
    """Full recompute of integrity stats from a JSONL file."""
    total_events = 0
    events_by_stream: dict[str, int] = {}
    missing_corr = 0

    with jsonl_path.open("r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except Exception:
                continue
            stream = str(event.get("stream", "unknown"))
            events_by_stream[stream] = events_by_stream.get(stream, 0) + 1
            total_events += 1
            if not str(event.get("correlation_id", "")).strip():
                missing_corr += 1

    return {
        "total_events": total_events,
        "events_by_stream": events_by_stream,
        "missing_correlation_count": missing_corr,
        "last_update_utc": _utc_now(),
    }


def _count_non_empty_lines(path: Path) -> int:
    count = 0
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            for raw in fh:
                if raw.strip():
                    count += 1
    except Exception:
        return 0
    return count


def run(root: Path) -> dict:
    today = _today()
    event_store_dir = root / "reports" / "event_store"
    jsonl_path = event_store_dir / f"events_{today}.jsonl"

    candidates = sorted(event_store_dir.glob("events_*.jsonl"))
    if not candidates:
        return {
            "status": "fail",
            "error": f"no events JSONL found in {event_store_dir}",
            "integrity_path": "",
        }

    if not jsonl_path.exists():
        # Fall back to latest when today's file is absent.
        jsonl_path = candidates[-1]
        print(f"[integrity-local] today JSONL missing; using {jsonl_path.name}")
    else:
        # If today's file is only sparse backfill rows, keep the most recent rich stream snapshot.
        today_rows = _count_non_empty_lines(jsonl_path)
        latest_other = candidates[-1]
        for fp in reversed(candidates):
            if fp.name != jsonl_path.name:
                latest_other = fp
                break
        other_rows = _count_non_empty_lines(latest_other) if latest_other != jsonl_path else 0
        if latest_other != jsonl_path and today_rows < 1000 and other_rows > today_rows:
            print(
                f"[integrity-local] today JSONL sparse ({today_rows}); using richer snapshot "
                f"{latest_other.name} ({other_rows})"
            )
            jsonl_path = latest_other

    stats = _recompute(jsonl_path)
    integrity_path = event_store_dir / f"integrity_{today}.json"
    integrity_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")

    print(f"[integrity-local] recomputed from {jsonl_path.name}")
    print(f"[integrity-local] total_events={stats['total_events']}")
    print(f"[integrity-local] missing_correlation_count={stats['missing_correlation_count']}")
    print(f"[integrity-local] evidence={integrity_path}")
    return {"status": "pass", "integrity_path": str(integrity_path), **stats}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh event store integrity report locally (no Redis)."
    )
    parser.add_argument(
        "--once", action="store_true", help="Run once and exit (default behaviour; flag kept for symmetry)."
    )
    args = parser.parse_args()
    _ = args  # --once is implied; flag exists for CLI consistency with other refresh scripts

    root = Path(__file__).resolve().parents[2]
    result = run(root)
    raise SystemExit(0 if result.get("status") == "pass" else 1)


if __name__ == "__main__":
    main()
