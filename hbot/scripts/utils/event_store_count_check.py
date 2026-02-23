from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    import redis  # type: ignore
except Exception as exc:  # pragma: no cover
    raise RuntimeError("redis package is required. Install with `python -m pip install redis`.") from exc


STREAMS = (
    "hb.market_data.v1",
    "hb.signal.v1",
    "hb.ml_signal.v1",
    "hb.risk_decision.v1",
    "hb.execution_intent.v1",
    "hb.audit.v1",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _latest_integrity_file(reports_dir: Path) -> Path | None:
    files = sorted(reports_dir.glob("integrity_*.json"))
    if not files:
        return None
    return files[-1]


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    reports_dir = root / "reports" / "event_store"
    integrity_path = _latest_integrity_file(reports_dir)
    out_path = root / "reports" / "event_store" / f"source_compare_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    baseline_path = root / "reports" / "event_store" / "baseline_counts.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    redis_db = int(os.getenv("REDIS_DB", "0"))
    redis_password = os.getenv("REDIS_PASSWORD", "")

    client = redis.Redis(
        host=redis_host,
        port=redis_port,
        db=redis_db,
        password=redis_password or None,
        decode_responses=True,
    )

    stored = _load_json(integrity_path, {"total_events": 0, "events_by_stream": {}}) if integrity_path else {"total_events": 0, "events_by_stream": {}}
    stored_by_stream = stored.get("events_by_stream", {})

    source_by_stream = {}
    deltas_abs = {}
    for stream in STREAMS:
        source_count = int(client.xlen(stream))
        stored_count = int(stored_by_stream.get(stream, 0))
        source_by_stream[stream] = source_count
        deltas_abs[stream] = source_count - stored_count

    baseline_default = {
        "created_at_utc": _utc_now(),
        "source_by_stream": source_by_stream,
        "stored_by_stream": {k: int(stored_by_stream.get(k, 0)) for k in STREAMS},
    }
    if not baseline_path.exists():
        baseline_path.write_text(json.dumps(baseline_default, indent=2), encoding="utf-8")
    baseline = _load_json(baseline_path, baseline_default)

    source_baseline = baseline.get("source_by_stream", {})
    stored_baseline = baseline.get("stored_by_stream", {})
    produced_since = {}
    ingested_since = {}
    deltas_since = {}
    for stream in STREAMS:
        produced = int(source_by_stream.get(stream, 0)) - int(source_baseline.get(stream, 0))
        ingested = int(stored_by_stream.get(stream, 0)) - int(stored_baseline.get(stream, 0))
        produced_since[stream] = produced
        ingested_since[stream] = ingested
        deltas_since[stream] = produced - ingested

    payload = {
        "ts_utc": _utc_now(),
        "integrity_file": str(integrity_path) if integrity_path else "",
        "baseline_file": str(baseline_path),
        "stored_total_events": int(stored.get("total_events", 0)),
        "stored_events_by_stream": stored_by_stream,
        "source_events_by_stream": source_by_stream,
        "delta_source_minus_stored_by_stream_abs": deltas_abs,
        "produced_since_baseline_by_stream": produced_since,
        "ingested_since_baseline_by_stream": ingested_since,
        "delta_produced_minus_ingested_since_baseline": deltas_since,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()
