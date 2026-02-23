from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import redis  # type: ignore


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


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _load_integrity(root: Path) -> dict:
    path = root / "reports" / "event_store" / f"integrity_{_today()}.json"
    if not path.exists():
        return {"total_events": 0, "events_by_stream": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"total_events": 0, "events_by_stream": {}}


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _snapshot(root: Path, client: redis.Redis) -> Path:
    out_path = root / "reports" / "event_store" / f"source_compare_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    baseline_path = root / "reports" / "event_store" / "baseline_counts.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stored = _load_integrity(root)
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
    print(str(out_path), flush=True)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval-sec", type=int, default=int(os.getenv("EVENT_STORE_MONITOR_INTERVAL_SEC", "900")))
    parser.add_argument("--max-runs", type=int, default=0, help="0 means run forever")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    client = redis.Redis(
        host=os.getenv("REDIS_HOST", "127.0.0.1"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=int(os.getenv("REDIS_DB", "0")),
        password=os.getenv("REDIS_PASSWORD", "") or None,
        decode_responses=True,
    )

    run_count = 0
    while True:
        _snapshot(root=root, client=client)
        run_count += 1
        if args.max_runs > 0 and run_count >= args.max_runs:
            break
        time.sleep(max(5, args.interval_sec))


if __name__ == "__main__":
    main()
