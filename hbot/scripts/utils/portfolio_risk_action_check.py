from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    import redis  # type: ignore
except Exception as exc:  # pragma: no cover
    raise RuntimeError("redis package is required. Install with `python -m pip install redis`.") from exc


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_payload(entry: Dict[str, Any]) -> Dict[str, Any]:
    payload_raw = entry.get("payload")
    if not isinstance(payload_raw, str):
        return {}
    try:
        parsed = json.loads(payload_raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _simplify_intent(entry_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    details_text = ""
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        details_text = str(metadata.get("details", ""))
    return {
        "entry_id": entry_id,
        "timestamp_ms": payload.get("timestamp_ms"),
        "event_id": payload.get("event_id"),
        "instance_name": payload.get("instance_name"),
        "action": payload.get("action"),
        "producer": payload.get("producer"),
        "reason": payload.get("metadata", {}).get("reason") if isinstance(payload.get("metadata"), dict) else "",
        "details_excerpt": details_text[:200],
    }


def _simplify_audit(entry_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "entry_id": entry_id,
        "timestamp_ms": payload.get("timestamp_ms"),
        "event_id": payload.get("event_id"),
        "instance_name": payload.get("instance_name"),
        "severity": payload.get("severity"),
        "category": payload.get("category"),
        "message": payload.get("message"),
        "producer": payload.get("producer"),
    }


def _entry_ts_ms(entry_id: str, payload: Dict[str, Any]) -> int:
    payload_ts = payload.get("timestamp_ms")
    try:
        if payload_ts is not None:
            return int(payload_ts)
    except Exception:
        pass
    try:
        return int(str(entry_id).split("-", maxsplit=1)[0])
    except Exception:
        return 0


def _sanitize_filename_component(value: str, default: str = "action_check") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or default


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=int(os.getenv("PORTFOLIO_RISK_ACTION_CHECK_COUNT", "500")))
    parser.add_argument(
        "--producer",
        type=str,
        default=os.getenv("PORTFOLIO_RISK_ACTION_CHECK_PRODUCER", "portfolio_risk_service"),
        help="Filter events by payload producer field.",
    )
    parser.add_argument(
        "--since-minutes",
        type=float,
        default=float(os.getenv("PORTFOLIO_RISK_ACTION_CHECK_SINCE_MINUTES", "0")),
        help="Only include events newer than now - since_minutes.",
    )
    parser.add_argument(
        "--output-prefix",
        type=str,
        default=os.getenv("PORTFOLIO_RISK_ACTION_CHECK_OUTPUT_PREFIX", "action_check"),
        help="Prefix for output filename, e.g. action_check_portfolio_risk.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    out_dir = root / "reports" / "portfolio_risk"
    out_dir.mkdir(parents=True, exist_ok=True)

    client = redis.Redis(
        host=os.getenv("REDIS_HOST", "127.0.0.1"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=int(os.getenv("REDIS_DB", "0")),
        password=(os.getenv("REDIS_PASSWORD", "") or None),
        decode_responses=True,
    )

    intent_stream = "hb.execution_intent.v1"
    audit_stream = "hb.audit.v1"
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    min_ts_ms = 0
    if args.since_minutes > 0:
        min_ts_ms = max(0, now_ms - int(args.since_minutes * 60 * 1000))

    intents_raw = client.xrevrange(intent_stream, count=max(1, args.count))
    audits_raw = client.xrevrange(audit_stream, count=max(1, args.count))

    producer_filter = str(args.producer).strip()

    matched_intents: List[Dict[str, Any]] = []
    for entry_id, data in intents_raw:
        payload = _parse_payload(data if isinstance(data, dict) else {})
        if producer_filter and str(payload.get("producer", "")) != producer_filter:
            continue
        if _entry_ts_ms(str(entry_id), payload) < min_ts_ms:
            continue
        matched_intents.append(_simplify_intent(str(entry_id), payload))

    matched_audits: List[Dict[str, Any]] = []
    for entry_id, data in audits_raw:
        payload = _parse_payload(data if isinstance(data, dict) else {})
        if producer_filter and str(payload.get("producer", "")) != producer_filter:
            continue
        if _entry_ts_ms(str(entry_id), payload) < min_ts_ms:
            continue
        matched_audits.append(_simplify_audit(str(entry_id), payload))

    payload = {
        "ts_utc": _utc_now_iso(),
        "redis_host": os.getenv("REDIS_HOST", "127.0.0.1"),
        "scan_count": max(1, args.count),
        "producer_filter": producer_filter,
        "since_minutes": float(args.since_minutes),
        "since_threshold_ts_ms": min_ts_ms,
        "intent_stream_len": int(client.xlen(intent_stream)),
        "audit_stream_len": int(client.xlen(audit_stream)),
        "matched_intent_count": len(matched_intents),
        "matched_audit_count": len(matched_audits),
        "matched_intents": matched_intents,
        "matched_audits": matched_audits,
        # Backward-compatible aliases for existing docs/scripts that still
        # reference the old portfolio-specific field names.
        "portfolio_risk_intent_count": len(matched_intents),
        "portfolio_risk_audit_count": len(matched_audits),
        "portfolio_risk_intents": matched_intents,
        "portfolio_risk_audits": matched_audits,
    }

    file_prefix = _sanitize_filename_component(str(args.output_prefix), default="action_check")
    producer_label = _sanitize_filename_component(producer_filter or "all_producers", default="all_producers")
    out_path = out_dir / f"{file_prefix}_{_today_stamp()}.json"
    latest_path = out_dir / "action_check_latest.json"
    latest_producer_path = out_dir / f"action_check_latest_{producer_label}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    latest_producer_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()
