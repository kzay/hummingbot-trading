from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from services.common.models import RedisSettings, ServiceSettings
from services.contracts.stream_names import (
    AUDIT_STREAM,
    EXECUTION_INTENT_STREAM,
    MARKET_DATA_STREAM,
    ML_SIGNAL_STREAM,
    RISK_DECISION_STREAM,
    SIGNAL_STREAM,
    DEFAULT_CONSUMER_GROUP,
)
from services.hb_bridge.redis_client import RedisStreamClient


STREAMS: Tuple[str, ...] = (
    MARKET_DATA_STREAM,
    SIGNAL_STREAM,
    ML_SIGNAL_STREAM,
    RISK_DECISION_STREAM,
    EXECUTION_INTENT_STREAM,
    AUDIT_STREAM,
)

STREAM_TO_EVENT_TYPE: Dict[str, str] = {
    MARKET_DATA_STREAM: "market_snapshot",
    SIGNAL_STREAM: "strategy_signal",
    ML_SIGNAL_STREAM: "ml_signal",
    RISK_DECISION_STREAM: "risk_decision",
    EXECUTION_INTENT_STREAM: "execution_intent",
    AUDIT_STREAM: "audit",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(payload: Dict[str, object], stream: str, entry_id: str, producer: str) -> Dict[str, object]:
    event_id = str(payload.get("event_id") or uuid.uuid4())
    correlation_id = str(payload.get("correlation_id") or event_id)
    event_type = str(payload.get("event_type") or STREAM_TO_EVENT_TYPE.get(stream, "unknown"))
    envelope = {
        "event_id": event_id,
        "event_type": event_type,
        "event_version": "v1",
        "ts_utc": str(payload.get("timestamp_ms") or _now_iso()),
        "producer": str(payload.get("producer") or producer),
        "instance_name": str(payload.get("instance_name") or ""),
        "controller_id": str(payload.get("controller_id") or ""),
        "connector_name": str(payload.get("connector_name") or ""),
        "trading_pair": str(payload.get("trading_pair") or ""),
        "correlation_id": correlation_id,
        "stream": stream,
        "stream_entry_id": entry_id,
        "payload": payload,
        "ingest_ts_utc": _now_iso(),
        "schema_validation_status": "ok",
    }
    return envelope


def _store_path(root: Path) -> Path:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = root / "reports" / "event_store" / f"events_{today}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _stats_path(root: Path) -> Path:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = root / "reports" / "event_store" / f"integrity_{today}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _append_events(path: Path, events: List[Dict[str, object]]) -> None:
    if not events:
        return
    with path.open("a", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=True) + "\n")


def _read_stats(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"total_events": 0, "events_by_stream": {}, "missing_correlation_count": 0, "last_update_utc": ""}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"total_events": 0, "events_by_stream": {}, "missing_correlation_count": 0, "last_update_utc": ""}


def _write_stats(path: Path, batch: List[Dict[str, object]]) -> None:
    stats = _read_stats(path)
    events_by_stream = dict(stats.get("events_by_stream", {}))
    total_events = int(stats.get("total_events", 0))
    missing_corr = int(stats.get("missing_correlation_count", 0))
    for event in batch:
        stream = str(event.get("stream", "unknown"))
        events_by_stream[stream] = int(events_by_stream.get(stream, 0)) + 1
        total_events += 1
        if not str(event.get("correlation_id", "")).strip():
            missing_corr += 1
    stats["events_by_stream"] = events_by_stream
    stats["total_events"] = total_events
    stats["missing_correlation_count"] = missing_corr
    stats["last_update_utc"] = _now_iso()
    path.write_text(json.dumps(stats, indent=2), encoding="utf-8")


def run(once: bool = False) -> None:
    redis_cfg = RedisSettings()
    svc_cfg = ServiceSettings()
    root = Path("/workspace/hbot")
    event_path = _store_path(root)
    stats_path = _stats_path(root)

    client = RedisStreamClient(
        host=redis_cfg.host,
        port=redis_cfg.port,
        db=redis_cfg.db,
        password=redis_cfg.password or None,
        enabled=redis_cfg.enabled,
    )
    if not client.enabled:
        raise RuntimeError("Redis stream client is disabled. Set EXT_SIGNAL_RISK_ENABLED=true and redis profile.")

    group = os.getenv("EVENT_STORE_CONSUMER_GROUP", "hb_event_store_v1").strip() or "hb_event_store_v1"
    consumer = f"event-store-{svc_cfg.instance_name}"
    for stream in STREAMS:
        client.create_group(stream, group)

    while True:
        batch: List[Dict[str, object]] = []
        for stream in STREAMS:
            entries = client.read_group(stream=stream, group=group, consumer=consumer, count=200, block_ms=svc_cfg.poll_ms)
            for entry_id, payload in entries:
                normalized = _normalize(payload=payload, stream=stream, entry_id=entry_id, producer=svc_cfg.producer_name)
                batch.append(normalized)
                client.ack(stream, group, entry_id)
        _append_events(event_path, batch)
        _write_stats(stats_path, batch)
        if once:
            break
        time.sleep(0.1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run one ingestion cycle and exit.")
    args = parser.parse_args()
    run(once=args.once)
