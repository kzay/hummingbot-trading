from __future__ import annotations

import argparse
import json
import logging
import os
import time
import uuid
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

from services.common.models import RedisSettings, ServiceSettings
from services.contracts.event_identity import validate_event_identity
from services.contracts.stream_names import (
    AUDIT_STREAM,
    BOT_TELEMETRY_STREAM,
    EXECUTION_INTENT_STREAM,
    MARKET_DEPTH_STREAM,
    MARKET_DATA_STREAM,
    MARKET_QUOTE_STREAM,
    MARKET_TRADE_STREAM,
    ML_SIGNAL_STREAM,
    RISK_DECISION_STREAM,
    SIGNAL_STREAM,
    DEFAULT_CONSUMER_GROUP,
    STREAM_RETENTION_MAXLEN,
)
from services.hb_bridge.redis_client import RedisStreamClient

logger = logging.getLogger(__name__)

try:
    import psycopg
except Exception:  # pragma: no cover - optional dependency in some environments.
    psycopg = None  # type: ignore[assignment]


STREAMS: Tuple[str, ...] = (
    MARKET_DATA_STREAM,
    MARKET_QUOTE_STREAM,
    MARKET_TRADE_STREAM,
    MARKET_DEPTH_STREAM,
    SIGNAL_STREAM,
    ML_SIGNAL_STREAM,
    RISK_DECISION_STREAM,
    EXECUTION_INTENT_STREAM,
    AUDIT_STREAM,
    BOT_TELEMETRY_STREAM,   # paper + live fills, minute snapshots
)

STREAM_TO_EVENT_TYPE: Dict[str, str] = {
    MARKET_DATA_STREAM: "market_snapshot",
    MARKET_QUOTE_STREAM: "market_quote",
    MARKET_TRADE_STREAM: "market_trade",
    MARKET_DEPTH_STREAM: "market_depth_snapshot",
    SIGNAL_STREAM: "strategy_signal",
    ML_SIGNAL_STREAM: "ml_signal",
    RISK_DECISION_STREAM: "risk_decision",
    EXECUTION_INTENT_STREAM: "execution_intent",
    AUDIT_STREAM: "audit",
    BOT_TELEMETRY_STREAM: "bot_fill",      # default; per-event type in payload takes precedence
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_ts_utc(value: object) -> str:
    if value in (None, ""):
        return _now_iso()

    def _epoch_like_to_iso(epoch_like: float) -> str:
        # Accept ns/us/ms/s epochs from mixed producers.
        mag = abs(epoch_like)
        seconds = epoch_like
        if mag >= 1e18:      # nanoseconds
            seconds = epoch_like / 1_000_000_000.0
        elif mag >= 1e15:    # microseconds
            seconds = epoch_like / 1_000_000.0
        elif mag >= 1e12:    # milliseconds
            seconds = epoch_like / 1_000.0
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()

    try:
        if isinstance(value, (int, float)):
            return _epoch_like_to_iso(float(value))
        raw = str(value).strip()
        if raw and raw.lstrip("-").isdigit():
            return _epoch_like_to_iso(float(raw))
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        return _now_iso()


def _stream_entry_id_to_iso(entry_id: str) -> Optional[str]:
    raw = str(entry_id or "").strip()
    if not raw:
        return None
    ms_part = raw.split("-", 1)[0].strip()
    if not ms_part or not ms_part.lstrip("-").isdigit():
        return None
    try:
        return datetime.fromtimestamp(int(ms_part) / 1000.0, tz=timezone.utc).isoformat()
    except Exception:
        return None


def _normalize(payload: Dict[str, object], stream: str, entry_id: str, producer: str) -> Dict[str, object]:
    event_id = str(payload.get("event_id") or uuid.uuid4())
    correlation_id = str(payload.get("correlation_id") or event_id)
    event_type = str(payload.get("event_type") or STREAM_TO_EVENT_TYPE.get(stream, "unknown"))
    event_version = str(payload.get("event_version") or "v1")
    schema_validation_status = str(payload.get("schema_validation_status") or "ok")
    ts_hint = payload.get("timestamp_ms") or payload.get("ts_utc") or _stream_entry_id_to_iso(entry_id)
    envelope = {
        "event_id": event_id,
        "event_type": event_type,
        "event_version": event_version,
        "ts_utc": _coerce_ts_utc(ts_hint),
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
        "schema_validation_status": schema_validation_status,
    }
    return envelope


def _accept_envelope(envelope: Dict[str, object]) -> Tuple[bool, str]:
    """Enforce minimum identity contract to prevent cross-bot contamination."""
    return validate_event_identity(envelope, allow_nested_payload=True)


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


def _bootstrap_report_path(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return root / "reports" / "event_store" / f"bootstrap_{stamp}.json"


def _resolve_root() -> Path:
    explicit = str(os.getenv("HB_ROOT", "")).strip()
    if explicit:
        return Path(explicit)
    if Path("/.dockerenv").exists():
        return Path("/workspace/hbot")
    return Path(__file__).resolve().parents[2]


def _append_events(path: Path, events: List[Dict[str, object]]) -> bool:
    if not events:
        return True
    retries = max(1, int(os.getenv("EVENT_STORE_APPEND_RETRIES", "3")))
    for attempt in range(1, retries + 1):
        try:
            with path.open("a", encoding="utf-8") as f:
                for event in events:
                    f.write(json.dumps(event, ensure_ascii=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
            return True
        except OSError as exc:
            if attempt >= retries:
                logger.error(
                    "event_store append failed after %s attempts: %s (path=%s)",
                    retries,
                    exc,
                    path,
                )
                return False
            backoff_s = min(2 ** (attempt - 1), 5)
            logger.warning(
                "event_store append failed attempt %s/%s: %s (retry_in_s=%s)",
                attempt,
                retries,
                exc,
                backoff_s,
            )
            time.sleep(backoff_s)
    return False


def _default_stats_payload() -> Dict[str, object]:
    return {
        "total_events": 0,
        "events_by_stream": {},
        "missing_correlation_count": 0,
        "last_update_utc": "",
        "ts_utc": "",
        "ingest_duration_ms_recent": [],
        "ingest_duration_ms_last": 0.0,
        "last_batch_size": 0,
        "accepted_events_last": 0,
        "dropped_events_last": 0,
        "pending_entries_read_last": 0,
        "claimed_entries_read_last": 0,
        "new_entries_read_last": 0,
        "eligible_ack_entries_last": 0,
        "oldest_event_lag_ms_last": 0.0,
        "latest_event_lag_ms_last": 0.0,
        "oldest_event_lag_ms_recent": [],
        "last_batch_stream_counts": {},
    }


def _read_stats(path: Path) -> Dict[str, object]:
    try:
        if not path.exists():
            return _default_stats_payload()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            defaults = _default_stats_payload()
            for key, value in defaults.items():
                payload.setdefault(key, value)
            if "ts_utc" not in payload and payload.get("last_update_utc"):
                payload["ts_utc"] = payload.get("last_update_utc", "")
            if "last_update_utc" not in payload and payload.get("ts_utc"):
                payload["last_update_utc"] = payload.get("ts_utc", "")
            return payload
        return _default_stats_payload()
    except Exception:
        return _default_stats_payload()


def _write_stats(
    path: Path,
    batch: List[Dict[str, object]],
    batch_duration_ms: float | None = None,
    *,
    cycle_metrics: Optional[Dict[str, object]] = None,
) -> bool:
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
    recent_durations = stats.get("ingest_duration_ms_recent", [])
    if not isinstance(recent_durations, list):
        recent_durations = []
    if batch_duration_ms is not None:
        recent_durations.append(round(max(0.0, float(batch_duration_ms)), 3))
        recent_durations = recent_durations[-50:]
        stats["ingest_duration_ms_last"] = round(max(0.0, float(batch_duration_ms)), 3)
    stats["ingest_duration_ms_recent"] = recent_durations
    stats["last_batch_size"] = int(len(batch))
    metrics = cycle_metrics if isinstance(cycle_metrics, dict) else {}
    stats["accepted_events_last"] = int(metrics.get("accepted_events_last", len(batch)) or 0)
    stats["dropped_events_last"] = int(metrics.get("dropped_events_last", 0) or 0)
    stats["pending_entries_read_last"] = int(metrics.get("pending_entries_read_last", 0) or 0)
    stats["claimed_entries_read_last"] = int(metrics.get("claimed_entries_read_last", 0) or 0)
    stats["new_entries_read_last"] = int(metrics.get("new_entries_read_last", 0) or 0)
    stats["eligible_ack_entries_last"] = int(metrics.get("eligible_ack_entries_last", 0) or 0)
    stats["oldest_event_lag_ms_last"] = round(max(0.0, float(metrics.get("oldest_event_lag_ms_last", 0.0) or 0.0)), 3)
    stats["latest_event_lag_ms_last"] = round(max(0.0, float(metrics.get("latest_event_lag_ms_last", 0.0) or 0.0)), 3)
    lag_recent = stats.get("oldest_event_lag_ms_recent", [])
    if not isinstance(lag_recent, list):
        lag_recent = []
    lag_recent.append(stats["oldest_event_lag_ms_last"])
    stats["oldest_event_lag_ms_recent"] = lag_recent[-50:]
    stream_counts = metrics.get("last_batch_stream_counts", {})
    stats["last_batch_stream_counts"] = dict(stream_counts) if isinstance(stream_counts, dict) else {}
    now_iso = _now_iso()
    stats["last_update_utc"] = now_iso
    stats["ts_utc"] = now_iso
    retries = max(1, int(os.getenv("EVENT_STORE_STATS_RETRIES", "3")))
    for attempt in range(1, retries + 1):
        tmp_path: Path | None = None
        try:
            # Atomic replace reduces corruption risk on shared/bind-mounted volumes.
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(path.parent),
                prefix=f".{path.stem}_",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                json.dump(stats, tmp, indent=2)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = Path(tmp.name)
            os.replace(tmp_path, path)
            return True
        except OSError as exc:
            if attempt >= retries:
                logger.error(
                    "event_store stats write failed after %s attempts: %s (path=%s)",
                    retries,
                    exc,
                    path,
                )
                return False
            backoff_s = min(2 ** (attempt - 1), 5)
            logger.warning(
                "event_store stats write failed attempt %s/%s: %s (retry_in_s=%s)",
                attempt,
                retries,
                exc,
                backoff_s,
            )
            time.sleep(backoff_s)
        finally:
            try:
                if tmp_path is not None and tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
    return False


def _count_entries_by_stream(entries: List[Tuple[str, str]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for stream, _entry_id in entries:
        counts[stream] = int(counts.get(stream, 0)) + 1
    return counts


def _batch_stream_counts(batch: List[Dict[str, object]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for event in batch:
        stream = str(event.get("stream", "unknown") or "unknown")
        counts[stream] = int(counts.get(stream, 0)) + 1
    return counts


def _batch_lag_metrics(batch: List[Dict[str, object]], *, now_utc: Optional[datetime] = None) -> Dict[str, float]:
    reference = now_utc or datetime.now(timezone.utc)
    lags_ms: List[float] = []
    for event in batch:
        raw_ts = str(event.get("ts_utc", "") or "").strip()
        if not raw_ts:
            continue
        try:
            event_dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            continue
        lag_ms = max(0.0, (reference - event_dt).total_seconds() * 1000.0)
        lags_ms.append(lag_ms)
    if not lags_ms:
        return {"oldest_event_lag_ms_last": 0.0, "latest_event_lag_ms_last": 0.0}
    return {
        "oldest_event_lag_ms_last": max(lags_ms),
        "latest_event_lag_ms_last": min(lags_ms),
    }


def _ack_entries(client: RedisStreamClient, group: str, ack_keys: List[Tuple[str, str]]) -> None:
    if not ack_keys:
        return
    ack_many_fn = getattr(client, "ack_many", None)
    ack_fn = getattr(client, "ack", None)
    by_stream: Dict[str, List[str]] = {}
    for stream, entry_id in ack_keys:
        stream_name = str(stream or "").strip()
        entry_name = str(entry_id or "").strip()
        if not stream_name or not entry_name:
            continue
        by_stream.setdefault(stream_name, []).append(entry_name)
    for stream, entry_ids in by_stream.items():
        if callable(ack_many_fn):
            ack_many_fn(stream, group, entry_ids)
            continue
        if callable(ack_fn):
            for entry_id in entry_ids:
                ack_fn(stream, group, entry_id)


def _connect_db() -> Optional["psycopg.Connection"]:
    if psycopg is None:
        return None
    return psycopg.connect(
        host=os.getenv("OPS_DB_HOST", "postgres"),
        port=int(os.getenv("OPS_DB_PORT", "5432")),
        dbname=os.getenv("OPS_DB_NAME", "kzay_capital_ops"),
        user=os.getenv("OPS_DB_USER", "hbot"),
        password=os.getenv("OPS_DB_PASSWORD", "kzay_capital_dev_password"),
    )


def _ensure_db_schema(conn: "psycopg.Connection") -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS event_envelope_raw (
      stream TEXT NOT NULL,
      stream_entry_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      event_type TEXT,
      event_version TEXT,
      ts_utc TIMESTAMPTZ NOT NULL,
      producer TEXT,
      instance_name TEXT,
      controller_id TEXT,
      connector_name TEXT,
      trading_pair TEXT,
      correlation_id TEXT,
      schema_validation_status TEXT,
      payload JSONB NOT NULL,
      ingest_ts_utc TIMESTAMPTZ NOT NULL,
      schema_version INTEGER NOT NULL,
      PRIMARY KEY (stream, stream_entry_id, ts_utc)
    );
    ALTER TABLE event_envelope_raw ADD COLUMN IF NOT EXISTS event_version TEXT;
    ALTER TABLE event_envelope_raw ADD COLUMN IF NOT EXISTS schema_validation_status TEXT;
    DO $$
    DECLARE
      v_pk_name TEXT;
      v_pk_def TEXT;
    BEGIN
      SELECT c.conname, pg_get_constraintdef(c.oid)
      INTO v_pk_name, v_pk_def
      FROM pg_constraint c
      WHERE c.conrelid = 'event_envelope_raw'::regclass
        AND c.contype = 'p'
      LIMIT 1;

      IF v_pk_name IS NULL THEN
        ALTER TABLE event_envelope_raw ADD CONSTRAINT event_envelope_raw_pkey PRIMARY KEY (stream, stream_entry_id, ts_utc);
      ELSIF v_pk_def <> 'PRIMARY KEY (stream, stream_entry_id, ts_utc)' THEN
        EXECUTE format('ALTER TABLE event_envelope_raw DROP CONSTRAINT %I', v_pk_name);
        ALTER TABLE event_envelope_raw ADD CONSTRAINT event_envelope_raw_pkey PRIMARY KEY (stream, stream_entry_id, ts_utc);
      END IF;
    END
    $$;
    CREATE INDEX IF NOT EXISTS idx_event_envelope_raw_ts_utc ON event_envelope_raw (ts_utc DESC);
    CREATE INDEX IF NOT EXISTS idx_event_envelope_raw_stream_ts_utc ON event_envelope_raw (stream, ts_utc DESC);
    CREATE INDEX IF NOT EXISTS idx_event_envelope_raw_type_ts_utc ON event_envelope_raw (event_type, ts_utc DESC);
    CREATE INDEX IF NOT EXISTS idx_event_envelope_raw_instance_pair_ts_utc ON event_envelope_raw (instance_name, trading_pair, ts_utc DESC);
    CREATE INDEX IF NOT EXISTS idx_event_envelope_raw_corr_ts_utc ON event_envelope_raw (correlation_id, ts_utc DESC);
    CREATE INDEX IF NOT EXISTS idx_event_envelope_raw_event_id ON event_envelope_raw (event_id);
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def _append_events_db(conn: "psycopg.Connection", events: List[Dict[str, object]]) -> bool:
    if not events:
        return True
    sql = """
    INSERT INTO event_envelope_raw (
      stream, stream_entry_id, event_id, event_type, event_version, ts_utc, producer, instance_name, controller_id,
      connector_name, trading_pair, correlation_id, schema_validation_status, payload, ingest_ts_utc, schema_version
    )
    VALUES (
      %(stream)s, %(stream_entry_id)s, %(event_id)s, %(event_type)s, %(event_version)s, %(ts_utc)s, %(producer)s, %(instance_name)s, %(controller_id)s,
      %(connector_name)s, %(trading_pair)s, %(correlation_id)s, %(schema_validation_status)s, %(payload)s::jsonb, %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (stream, stream_entry_id, ts_utc) DO NOTHING
    """
    retries = max(1, int(os.getenv("EVENT_STORE_DB_APPEND_RETRIES", "3")))
    for attempt in range(1, retries + 1):
        try:
            with conn.cursor() as cur:
                for event in events:
                    event_id = str(event.get("event_id", ""))
                    stream_entry_id = str(event.get("stream_entry_id", "")).strip()
                    if not stream_entry_id:
                        # Preserve idempotency for non-redis sources that do not carry stream IDs.
                        stream_entry_id = f"event:{event_id or uuid.uuid4()}"
                    ts_hint = event.get("ts_utc") or _stream_entry_id_to_iso(stream_entry_id)
                    row = {
                        "stream": str(event.get("stream", "")),
                        "stream_entry_id": stream_entry_id,
                        "event_id": event_id,
                        "event_type": str(event.get("event_type", "")),
                        "event_version": str(event.get("event_version", "v1")),
                        "ts_utc": _coerce_ts_utc(ts_hint),
                        "producer": str(event.get("producer", "")),
                        "instance_name": str(event.get("instance_name", "")),
                        "controller_id": str(event.get("controller_id", "")),
                        "connector_name": str(event.get("connector_name", "")),
                        "trading_pair": str(event.get("trading_pair", "")),
                        "correlation_id": str(event.get("correlation_id", "")),
                        "schema_validation_status": str(event.get("schema_validation_status", "ok")),
                        "payload": json.dumps(event.get("payload", {}), ensure_ascii=True),
                        "ingest_ts_utc": str(event.get("ingest_ts_utc", _now_iso())),
                        "schema_version": 1,
                    }
                    cur.execute(sql, row)
            conn.commit()
            return True
        except Exception as exc:
            conn.rollback()
            if attempt >= retries:
                logger.error("event_store db append failed after %s attempts: %s", retries, exc)
                return False
            backoff_s = min(2 ** (attempt - 1), 5)
            logger.warning(
                "event_store db append failed attempt %s/%s: %s (retry_in_s=%s)",
                attempt,
                retries,
                exc,
                backoff_s,
            )
            time.sleep(backoff_s)
    return False


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _trim_known_streams(
    client: RedisStreamClient,
    stream_maxlens: Dict[str, int],
) -> Dict[str, int]:
    trim_fn = getattr(client, "xtrim", None)
    summary = {
        "streams_checked": 0,
        "trim_calls": 0,
        "entries_trimmed": 0,
        "errors": 0,
    }
    if not callable(trim_fn):
        return summary

    for stream, maxlen in stream_maxlens.items():
        safe_maxlen = max(1, int(maxlen))
        summary["streams_checked"] += 1
        try:
            trimmed = trim_fn(stream=stream, maxlen=safe_maxlen, approximate=True)
        except Exception as exc:
            logger.warning("event_store trim failed stream=%s maxlen=%s: %s", stream, safe_maxlen, exc)
            trimmed = None
        if trimmed is None:
            summary["errors"] += 1
            continue
        summary["trim_calls"] += 1
        summary["entries_trimmed"] += int(trimmed)
    return summary


def _bootstrap_stream_coverage(
    client: RedisStreamClient,
    root: Path,
    event_path: Path,
    stats_path: Path,
    producer_name: str,
) -> Dict[str, Any]:
    """Seed one latest event per missing stream to preserve coverage visibility."""
    stats = _read_stats(stats_path)
    events_by_stream = stats.get("events_by_stream", {})
    if not isinstance(events_by_stream, dict):
        events_by_stream = {}

    seed_batch: List[Dict[str, object]] = []
    seeded_streams: List[str] = []
    missing_streams: List[str] = []
    for stream in STREAMS:
        existing = int(events_by_stream.get(stream, 0) or 0)
        if existing > 0:
            continue
        latest = client.read_latest(stream)
        if not latest:
            missing_streams.append(stream)
            continue
        entry_id, payload = latest
        envelope = _normalize(payload=payload, stream=stream, entry_id=entry_id, producer=producer_name)
        envelope["bootstrap_snapshot"] = True
        seed_batch.append(envelope)
        seeded_streams.append(stream)

    if seed_batch:
        _append_events(event_path, seed_batch)
        _write_stats(stats_path, seed_batch)

    report_payload: Dict[str, Any] = {
        "ts_utc": _now_iso(),
        "status": "pass",
        "seeded_count": len(seed_batch),
        "seeded_streams": seeded_streams,
        "missing_streams_without_latest_event": missing_streams,
    }
    report_path = _bootstrap_report_path(root)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    (root / "reports" / "event_store" / "bootstrap_latest.json").write_text(
        json.dumps(report_payload, indent=2),
        encoding="utf-8",
    )
    return report_payload


def run(once: bool = False) -> None:
    redis_cfg = RedisSettings()
    svc_cfg = ServiceSettings()
    root = _resolve_root()
    event_path = _store_path(root)
    stats_path = _stats_path(root)
    db_mirror_enabled = _env_bool("EVENT_STORE_DB_MIRROR_ENABLED", False)
    db_mirror_required = _env_bool("EVENT_STORE_DB_MIRROR_REQUIRED", False)
    db_conn: Optional["psycopg.Connection"] = None

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
    read_pending_fn = getattr(client, "read_pending", None)
    claim_pending_fn = getattr(client, "claim_pending", None)
    pending_min_idle_ms = max(1, int(os.getenv("EVENT_STORE_PENDING_MIN_IDLE_MS", "30000")))
    pending_claim_count = max(1, int(os.getenv("EVENT_STORE_PENDING_CLAIM_COUNT", "200")))
    read_batch_count = max(1, int(os.getenv("EVENT_STORE_READ_BATCH_COUNT", "500")))
    idle_sleep_ms = max(0, int(os.getenv("EVENT_STORE_IDLE_SLEEP_MS", "100")))
    trim_streams_enabled = _env_bool("EVENT_STORE_TRIM_STREAMS_ENABLED", True)
    trim_interval_sec = max(5, int(os.getenv("EVENT_STORE_TRIM_INTERVAL_SEC", "30")))
    trim_targets = {
        str(stream): max(1, int(maxlen))
        for stream, maxlen in STREAM_RETENTION_MAXLEN.items()
        if int(maxlen) > 0
    }
    last_trim_at = 0.0
    group_start_id = os.getenv("EVENT_STORE_GROUP_START_ID", "0").strip() or "0"
    for stream in STREAMS:
        client.create_group(stream, group, start_id=group_start_id)

    if db_mirror_enabled:
        try:
            db_conn = _connect_db()
            if db_conn is None:
                raise RuntimeError("psycopg_not_available")
            _ensure_db_schema(db_conn)
            logger.info("event_store db mirror enabled")
        except Exception as exc:
            if db_mirror_required:
                raise RuntimeError(f"event_store db mirror required but unavailable: {exc}") from exc
            logger.warning("event_store db mirror disabled: %s", exc)
            db_mirror_enabled = False
            db_conn = None

    if _env_bool("EVENT_STORE_BOOTSTRAP_SNAPSHOT_ENABLED", True):
        _bootstrap_stream_coverage(
            client=client,
            root=root,
            event_path=event_path,
            stats_path=stats_path,
            producer_name=svc_cfg.producer_name,
        )

    while True:
        now_monotonic = time.monotonic()
        if trim_streams_enabled and (now_monotonic - last_trim_at) >= trim_interval_sec:
            trim_summary = _trim_known_streams(client, trim_targets)
            if trim_summary["entries_trimmed"] > 0 or trim_summary["errors"] > 0:
                logger.info(
                    "event_store stream trim checked=%s calls=%s trimmed=%s errors=%s",
                    trim_summary["streams_checked"],
                    trim_summary["trim_calls"],
                    trim_summary["entries_trimmed"],
                    trim_summary["errors"],
                )
            last_trim_at = now_monotonic

        batch: List[Dict[str, object]] = []
        batch_ack_keys: List[Tuple[str, str]] = []
        dropped_ack_keys: List[Tuple[str, str]] = []
        dropped_reasons: Dict[str, int] = {}
        pending_entries_read = 0
        claimed_entries_read = 0
        new_entries_read = 0
        for stream in STREAMS:
            if callable(read_pending_fn):
                pending = read_pending_fn(
                    stream=stream,
                    group=group,
                    consumer=consumer,
                    count=pending_claim_count,
                    block_ms=1,
                )
                pending_entries_read += len(pending)
                for entry_id, payload in pending:
                    normalized = _normalize(payload=payload, stream=stream, entry_id=entry_id, producer=svc_cfg.producer_name)
                    accepted, reject_reason = _accept_envelope(normalized)
                    if accepted:
                        batch.append(normalized)
                        batch_ack_keys.append((stream, entry_id))
                    else:
                        dropped_ack_keys.append((stream, entry_id))
                        dropped_reasons[reject_reason] = int(dropped_reasons.get(reject_reason, 0)) + 1
            if callable(claim_pending_fn):
                claimed = claim_pending_fn(
                    stream=stream,
                    group=group,
                    consumer=consumer,
                    min_idle_ms=pending_min_idle_ms,
                    count=pending_claim_count,
                    start_id="0-0",
                )
                claimed_entries_read += len(claimed)
                for entry_id, payload in claimed:
                    normalized = _normalize(payload=payload, stream=stream, entry_id=entry_id, producer=svc_cfg.producer_name)
                    accepted, reject_reason = _accept_envelope(normalized)
                    if accepted:
                        batch.append(normalized)
                        batch_ack_keys.append((stream, entry_id))
                    else:
                        dropped_ack_keys.append((stream, entry_id))
                        dropped_reasons[reject_reason] = int(dropped_reasons.get(reject_reason, 0)) + 1
        entries = client.read_group_multi(
            streams=STREAMS,
            group=group,
            consumer=consumer,
            count=read_batch_count,
            block_ms=svc_cfg.poll_ms,
        )
        new_entries_read += len(entries)
        for stream, entry_id, payload in entries:
            normalized = _normalize(payload=payload, stream=stream, entry_id=entry_id, producer=svc_cfg.producer_name)
            accepted, reject_reason = _accept_envelope(normalized)
            if accepted:
                batch.append(normalized)
                batch_ack_keys.append((stream, entry_id))
            else:
                dropped_ack_keys.append((stream, entry_id))
                dropped_reasons[reject_reason] = int(dropped_reasons.get(reject_reason, 0)) + 1

        if dropped_ack_keys:
            _ack_entries(client, group, dropped_ack_keys)
            logger.warning(
                "event_store dropped %s envelopes violating identity contract: %s",
                len(dropped_ack_keys),
                dropped_reasons,
            )

        ingest_started = time.perf_counter()
        persisted_file = _append_events(event_path, batch)
        db_ok = _append_events_db(db_conn, batch) if (db_mirror_enabled and db_conn is not None) else True
        ingest_duration_ms = (time.perf_counter() - ingest_started) * 1000.0
        cycle_metrics = {
            "accepted_events_last": len(batch),
            "dropped_events_last": len(dropped_ack_keys),
            "pending_entries_read_last": pending_entries_read,
            "claimed_entries_read_last": claimed_entries_read,
            "new_entries_read_last": new_entries_read,
            "eligible_ack_entries_last": len(batch_ack_keys),
            "last_batch_stream_counts": _batch_stream_counts(batch),
            **_batch_lag_metrics(batch),
        }
        stats_ok = (
            _write_stats(
                stats_path,
                batch,
                batch_duration_ms=ingest_duration_ms,
                cycle_metrics=cycle_metrics,
            )
            if persisted_file
            else False
        )
        if persisted_file and stats_ok and db_ok:
            _ack_entries(client, group, batch_ack_keys)
            if batch_ack_keys:
                logger.info(
                    "event_store acked accepted=%s streams=%s pending=%s claimed=%s new=%s oldest_lag_ms=%.3f",
                    len(batch_ack_keys),
                    _count_entries_by_stream(batch_ack_keys),
                    pending_entries_read,
                    claimed_entries_read,
                    new_entries_read,
                    float(cycle_metrics["oldest_event_lag_ms_last"]),
                )
        elif batch:
            logger.error(
                "event_store persistence failed (file=%s stats=%s db=%s); leaving %s entries unacked for replay",
                persisted_file,
                stats_ok,
                db_ok,
                len(batch_ack_keys),
            )
        if once:
            break
        if pending_entries_read == 0 and claimed_entries_read == 0 and new_entries_read == 0 and not dropped_ack_keys:
            time.sleep(idle_sleep_ms / 1000.0)
    if db_conn is not None:
        db_conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run one ingestion cycle and exit.")
    args = parser.parse_args()
    run(once=args.once)
