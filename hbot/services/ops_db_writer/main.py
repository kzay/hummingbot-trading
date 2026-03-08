from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

try:
    import psycopg
except Exception:  # pragma: no cover - optional in lightweight test environments.
    psycopg = None  # type: ignore[assignment]


SCHEMA_VERSION = 1
_EPOCH_TS_UTC = "1970-01-01T00:00:00+00:00"


from services.common.utils import (
    read_json as _read_json,
    safe_float as _safe_float,
    utc_now as _utc_now,
)
from services.contracts.stream_names import MARKET_DEPTH_STREAM, MARKET_QUOTE_STREAM


def _read_csv_rows(path: Path) -> Iterator[Dict[str, str]]:
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as fp:
            for row in csv.DictReader(fp):
                yield row
    except Exception:
        return


def _parse_ts(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _stream_entry_id_to_ts_utc(stream_entry_id: str) -> Optional[str]:
    raw = str(stream_entry_id or "").strip()
    if not raw:
        return None
    ms_part = raw.split("-", 1)[0].strip()
    if not ms_part or not ms_part.lstrip("-").isdigit():
        return None
    try:
        return datetime.fromtimestamp(int(ms_part) / 1000.0, tz=timezone.utc).isoformat()
    except Exception:
        return None


def _canonical_ts_utc(value: Any, default: str = _EPOCH_TS_UTC) -> str:
    parsed = _parse_ts(str(value or "").strip())
    if parsed is not None:
        return parsed.astimezone(timezone.utc).isoformat()
    return default


def _floor_minute_utc(ts_utc: str) -> str:
    parsed = _parse_ts(ts_utc)
    if parsed is None:
        parsed = datetime.fromtimestamp(0, tz=timezone.utc)
    floored = parsed.astimezone(timezone.utc).replace(second=0, microsecond=0)
    return floored.isoformat()


def _epoch_ms_to_ts_utc(value: Any, default: str = _EPOCH_TS_UTC) -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    try:
        ms = int(float(raw))
    except Exception:
        return default
    if ms <= 0:
        return default
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()
    except Exception:
        return default


def _normalize_depth_levels(raw_levels: Any, max_levels: int) -> List[Dict[str, float]]:
    if not isinstance(raw_levels, list):
        return []
    out: List[Dict[str, float]] = []
    for entry in raw_levels:
        price = None
        size = None
        if isinstance(entry, dict):
            price = _safe_float(entry.get("price"))
            size = _safe_float(entry.get("size", entry.get("amount", entry.get("quantity"))))
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            price = _safe_float(entry[0])
            size = _safe_float(entry[1])
        if price is None or size is None:
            continue
        if price <= 0 or size <= 0:
            continue
        out.append({"price": float(price), "size": float(size)})
        if len(out) >= max_levels:
            break
    return out


def _depth_metrics(bids: List[Dict[str, float]], asks: List[Dict[str, float]]) -> Dict[str, Optional[float]]:
    best_bid = bids[0]["price"] if bids else None
    best_ask = asks[0]["price"] if asks else None
    mid_price = None
    spread_bps = None
    if best_bid is not None and best_ask is not None and best_ask >= best_bid:
        mid_price = (best_bid + best_ask) / 2.0
        if mid_price > 0:
            spread_bps = ((best_ask - best_bid) / mid_price) * 10_000.0
    bid_depth_total = float(sum(level["size"] for level in bids))
    ask_depth_total = float(sum(level["size"] for level in asks))
    denom = bid_depth_total + ask_depth_total
    imbalance = ((bid_depth_total - ask_depth_total) / denom) if denom > 0 else 0.0
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid_price": mid_price,
        "spread_bps": spread_bps,
        "bid_depth_total": bid_depth_total,
        "ask_depth_total": ask_depth_total,
        "depth_imbalance": imbalance,
    }


def _read_jsonl_rows(path: Path) -> Iterator[Dict[str, Any]]:
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fp:
            for raw in fp:
                line = raw.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    yield payload
    except Exception:
        return


def _iter_jsonl_rows(path: Path, *, start_line: int = 1) -> Iterator[Tuple[int, Dict[str, Any]]]:
    if not path.exists():
        return
    start = max(1, int(start_line))
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fp:
            for line_idx, raw in enumerate(fp, start=1):
                if line_idx < start:
                    continue
                line = raw.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    yield line_idx, payload
    except Exception:
        return


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _normalize_pair(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "").replace("-", "").replace("_", "")


def _extract_position_from_desk_snapshot(snapshot: Dict[str, Any], trading_pair: str) -> Dict[str, Any]:
    pair_norm = _normalize_pair(trading_pair)
    portfolio = snapshot.get("portfolio")
    if isinstance(portfolio, dict):
        portfolio = portfolio.get("portfolio", portfolio)
    positions = portfolio.get("positions", {}) if isinstance(portfolio, dict) else {}
    if not isinstance(positions, dict):
        positions = {}
    for raw_key, raw_pos in positions.items():
        raw_pos = raw_pos if isinstance(raw_pos, dict) else {}
        key_norm = _normalize_pair(str(raw_key))
        pos_pair_norm = _normalize_pair(raw_pos.get("trading_pair", ""))
        if pair_norm and pair_norm not in {key_norm, pos_pair_norm}:
            continue
        return raw_pos
    return {}


def _source_abs(path: Path) -> str:
    return str(path.resolve())


def _fill_key(source_path: str, line_idx: int, row: Dict[str, str]) -> str:
    raw = "|".join(
        [
            source_path,
            str(line_idx),
            str(row.get("ts", "")),
            str(row.get("order_id", "")),
            str(row.get("trade_id", "")),
            str(row.get("side", "")),
            str(row.get("price", "")),
            # Keep key derivation stable across writer versions for idempotent re-runs.
            str(row.get("amount", "")),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _connect() -> psycopg.Connection:
    if psycopg is None:
        raise RuntimeError("psycopg_not_installed")
    host = os.getenv("OPS_DB_HOST", "postgres")
    port = int(os.getenv("OPS_DB_PORT", "5432"))
    dbname = os.getenv("OPS_DB_NAME", "kzay_capital_ops")
    user = os.getenv("OPS_DB_USER", "hbot")
    password = os.getenv("OPS_DB_PASSWORD", "kzay_capital_dev_password")
    return psycopg.connect(host=host, port=port, dbname=dbname, user=user, password=password)


def _apply_schema(conn: psycopg.Connection, root: Path) -> None:
    schema_path = root / "services" / "ops_db_writer" / "schema_v1.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except Exception:
        return default


def _apply_timescale(conn: psycopg.Connection) -> Dict[str, object]:
    enabled = _env_bool("OPS_DB_TIMESCALE_ENABLED", True)
    required = _env_bool("OPS_DB_TIMESCALE_REQUIRED", False)
    compression_enabled = _env_bool("OPS_DB_TIMESCALE_ENABLE_COMPRESSION", False)
    meta: Dict[str, Any] = {
        "enabled": enabled,
        "required": required,
        "extension_available": False,
        "hypertables": [],
        "hypertable_attempts": [],
        "retention_policies": [],
        "compression_policies": [],
        "warnings": [],
    }
    if not enabled:
        return meta

    table_specs = [
        {
            "name": "bot_snapshot_minute",
            "time_col": "ts_utc",
            "retention_env": "OPS_DB_TS_RETENTION_MINUTE_DAYS",
            "retention_default": 90,
            "compression_env": "OPS_DB_TS_COMPRESS_AFTER_MINUTE_DAYS",
            "compression_default": 3,
            "segment_by": "bot,variant",
        },
        {
            "name": "fills",
            "time_col": "ts_utc",
            "retention_env": "OPS_DB_TS_RETENTION_FILLS_DAYS",
            "retention_default": 365,
            "compression_env": "OPS_DB_TS_COMPRESS_AFTER_FILLS_DAYS",
            "compression_default": 7,
            "segment_by": "bot,variant,exchange,trading_pair",
        },
        {
            "name": "event_envelope_raw",
            "time_col": "ts_utc",
            "retention_env": "OPS_DB_TS_RETENTION_EVENTS_DAYS",
            "retention_default": 30,
            "compression_env": "OPS_DB_TS_COMPRESS_AFTER_EVENTS_DAYS",
            "compression_default": 2,
            "segment_by": "stream,event_type,instance_name",
        },
        {
            "name": "market_depth_raw",
            "time_col": "ts_utc",
            "retention_env": "OPS_DB_TS_RETENTION_DEPTH_RAW_DAYS",
            "retention_default": 7,
            "compression_env": "OPS_DB_TS_COMPRESS_AFTER_DEPTH_RAW_DAYS",
            "compression_default": 1,
            "segment_by": "connector_name,trading_pair,instance_name",
        },
        {
            "name": "market_depth_sampled",
            "time_col": "ts_utc",
            "retention_env": "OPS_DB_TS_RETENTION_DEPTH_SAMPLED_DAYS",
            "retention_default": 30,
            "compression_env": "OPS_DB_TS_COMPRESS_AFTER_DEPTH_SAMPLED_DAYS",
            "compression_default": 3,
            "segment_by": "connector_name,trading_pair,instance_name",
        },
        {
            "name": "market_depth_rollup_minute",
            "time_col": "bucket_minute_utc",
            "retention_env": "OPS_DB_TS_RETENTION_DEPTH_ROLLUP_DAYS",
            "retention_default": 365,
            "compression_env": "OPS_DB_TS_COMPRESS_AFTER_DEPTH_ROLLUP_DAYS",
            "compression_default": 7,
            "segment_by": "connector_name,trading_pair,instance_name",
        },
        {
            "name": "market_quote_raw",
            "time_col": "ts_utc",
            "retention_env": "OPS_DB_TS_RETENTION_QUOTE_RAW_DAYS",
            "retention_default": 14,
            "compression_env": "OPS_DB_TS_COMPRESS_AFTER_QUOTE_RAW_DAYS",
            "compression_default": 2,
            "segment_by": "connector_name,trading_pair",
        },
        {
            "name": "market_quote_bar_minute",
            "time_col": "bucket_minute_utc",
            "retention_env": "OPS_DB_TS_RETENTION_QUOTE_BAR_DAYS",
            "retention_default": 365,
            "compression_env": "OPS_DB_TS_COMPRESS_AFTER_QUOTE_BAR_DAYS",
            "compression_default": 7,
            "segment_by": "connector_name,trading_pair",
        },
    ]

    def _exec(sql: str, params: Optional[tuple] = None, fetchone: bool = False) -> Optional[tuple]:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone() if fetchone else None

    def _fetchall(sql: str, params: Optional[tuple] = None) -> list[tuple]:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall() or [])

    def _incompatible_unique_constraints(table_name: str, time_col: str) -> list[str]:
        rows = _fetchall(
            """
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = current_schema()
              AND t.relname = %s
              AND c.contype IN ('p', 'u')
              AND NOT EXISTS (
                SELECT 1
                FROM unnest(c.conkey) AS key(attnum)
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = key.attnum
                WHERE a.attname = %s
              )
            ORDER BY c.conname
            """,
            (table_name, time_col),
        )
        return [str(r[0]) for r in rows if r and r[0]]

    try:
        _exec("CREATE EXTENSION IF NOT EXISTS timescaledb")
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        if required:
            raise RuntimeError(f"timescaledb_required_but_unavailable: {exc}") from exc
        meta["warnings"].append(f"timescaledb_extension_unavailable: {exc}")
        return meta

    try:
        exists_row = _exec("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb')", fetchone=True)
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        if required:
            raise RuntimeError(f"timescaledb_extension_probe_failed: {exc}") from exc
        meta["warnings"].append(f"timescaledb_extension_probe_failed: {exc}")
        return meta

    extension_available = bool(exists_row and exists_row[0])
    meta["extension_available"] = extension_available
    if not extension_available:
        if required:
            raise RuntimeError("timescaledb_required_but_not_installed")
        meta["warnings"].append("timescaledb_not_installed_plain_postgres_mode")
        return meta

    created_hypertables = set()
    for spec in table_specs:
        table_name = str(spec["name"])
        time_col = str(spec["time_col"])
        try:
            incompatible_constraints = _incompatible_unique_constraints(table_name, time_col)
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            if required:
                raise RuntimeError(
                    f"timescale_constraint_probe_failed:{table_name}:{time_col}: {exc}"
                ) from exc
            meta["warnings"].append(f"timescale_constraint_probe_failed:{table_name}:{time_col}: {exc}")
            meta["hypertable_attempts"].append(
                {"table": table_name, "status": "failed", "error": f"constraint_probe_failed:{exc}"}
            )
            continue

        if incompatible_constraints:
            reason = (
                "incompatible_unique_constraints_missing_time_column:"
                + ",".join(incompatible_constraints)
            )
            if required:
                raise RuntimeError(f"create_hypertable_blocked:{table_name}:{reason}")
            meta["warnings"].append(f"create_hypertable_blocked:{table_name}:{reason}")
            meta["hypertable_attempts"].append(
                {"table": table_name, "status": "skipped", "reason": reason}
            )
            continue

        try:
            _exec(
                f"SELECT create_hypertable('{table_name}', '{time_col}', if_not_exists => TRUE, migrate_data => TRUE)"
            )
            conn.commit()
            created_hypertables.add(table_name)
            meta["hypertables"].append(table_name)
            meta["hypertable_attempts"].append(
                {"table": table_name, "status": "created", "time_column": time_col}
            )
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            if required:
                raise RuntimeError(f"create_hypertable_failed:{table_name}: {exc}") from exc
            meta["warnings"].append(f"create_hypertable_failed:{table_name}: {exc}")
            meta["hypertable_attempts"].append(
                {"table": table_name, "status": "failed", "error": str(exc)}
            )

    for spec in table_specs:
        table_name = str(spec["name"])
        if table_name not in created_hypertables:
            continue
        days = _env_int(str(spec["retention_env"]), int(spec["retention_default"]))
        if days <= 0:
            continue
        try:
            _exec(
                f"SELECT add_retention_policy('{table_name}', INTERVAL '{days} days', if_not_exists => TRUE)"
            )
            conn.commit()
            meta["retention_policies"].append({"table": table_name, "days": days})
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            if required:
                raise RuntimeError(f"add_retention_policy_failed:{table_name}: {exc}") from exc
            meta["warnings"].append(f"add_retention_policy_failed:{table_name}: {exc}")

    if compression_enabled:
        for spec in table_specs:
            table_name = str(spec["name"])
            if table_name not in created_hypertables:
                continue
            after_days = _env_int(str(spec["compression_env"]), int(spec["compression_default"]))
            if after_days <= 0:
                continue
            try:
                seg = str(spec.get("segment_by", "")).strip()
                if seg:
                    _exec(
                        f"ALTER TABLE {table_name} SET (timescaledb.compress = true, timescaledb.compress_segmentby = '{seg}')"
                    )
                else:
                    _exec(f"ALTER TABLE {table_name} SET (timescaledb.compress = true)")
                _exec(
                    f"SELECT add_compression_policy('{table_name}', INTERVAL '{after_days} days', if_not_exists => TRUE)"
                )
                conn.commit()
                meta["compression_policies"].append({"table": table_name, "days": after_days})
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                if required:
                    raise RuntimeError(f"add_compression_policy_failed:{table_name}: {exc}") from exc
                meta["warnings"].append(f"add_compression_policy_failed:{table_name}: {exc}")

    return meta


def _ingest_minutes(conn: psycopg.Connection, data_root: Path, ingest_ts_utc: str) -> int:
    inserted = 0
    sql = """
    INSERT INTO bot_snapshot_minute (
      bot, variant, ts_utc, exchange, trading_pair, state, regime, equity_quote, base_pct,
      target_base_pct, daily_loss_pct, drawdown_pct, cancel_per_min, orders_active, fills_count_today,
      fees_paid_today_quote, risk_reasons, bot_mode, accounting_source, mid, spread_pct, net_edge_pct,
      turnover_today_x, raw_payload, source_path, ingest_ts_utc, schema_version
    )
    VALUES (
      %(bot)s, %(variant)s, %(ts_utc)s, %(exchange)s, %(trading_pair)s, %(state)s, %(regime)s, %(equity_quote)s,
      %(base_pct)s, %(target_base_pct)s, %(daily_loss_pct)s, %(drawdown_pct)s, %(cancel_per_min)s, %(orders_active)s,
      %(fills_count_today)s, %(fees_paid_today_quote)s, %(risk_reasons)s, %(bot_mode)s, %(accounting_source)s,
      %(mid)s, %(spread_pct)s, %(net_edge_pct)s, %(turnover_today_x)s, %(raw_payload)s::jsonb, %(source_path)s,
      %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (bot, variant, ts_utc) DO UPDATE SET
      exchange = EXCLUDED.exchange,
      trading_pair = EXCLUDED.trading_pair,
      state = EXCLUDED.state,
      regime = EXCLUDED.regime,
      equity_quote = EXCLUDED.equity_quote,
      base_pct = EXCLUDED.base_pct,
      target_base_pct = EXCLUDED.target_base_pct,
      daily_loss_pct = EXCLUDED.daily_loss_pct,
      drawdown_pct = EXCLUDED.drawdown_pct,
      cancel_per_min = EXCLUDED.cancel_per_min,
      orders_active = EXCLUDED.orders_active,
      fills_count_today = EXCLUDED.fills_count_today,
      fees_paid_today_quote = EXCLUDED.fees_paid_today_quote,
      risk_reasons = EXCLUDED.risk_reasons,
      bot_mode = EXCLUDED.bot_mode,
      accounting_source = EXCLUDED.accounting_source,
      mid = EXCLUDED.mid,
      spread_pct = EXCLUDED.spread_pct,
      net_edge_pct = EXCLUDED.net_edge_pct,
      turnover_today_x = EXCLUDED.turnover_today_x,
      raw_payload = EXCLUDED.raw_payload,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    with conn.cursor() as cur:
        for minute_file in data_root.glob("*/logs/epp_v24/*/minute.csv"):
            try:
                bot = minute_file.parts[-5]
                variant = minute_file.parts[-2]
            except Exception:
                continue
            source_path = _source_abs(minute_file)
            for row in _read_csv_rows(minute_file):
                ts = str(row.get("ts", "")).strip()
                if not ts:
                    continue
                payload = {
                    "bot": bot,
                    "variant": variant,
                    "ts_utc": ts,
                    "exchange": str(row.get("exchange", "")),
                    "trading_pair": str(row.get("trading_pair", "")),
                    "state": str(row.get("state", "")),
                    "regime": str(row.get("regime", "")),
                    "equity_quote": _safe_float(row.get("equity_quote")),
                    "base_pct": _safe_float(row.get("base_pct")),
                    "target_base_pct": _safe_float(row.get("target_base_pct")),
                    "daily_loss_pct": _safe_float(row.get("daily_loss_pct")),
                    "drawdown_pct": _safe_float(row.get("drawdown_pct")),
                    "cancel_per_min": _safe_float(row.get("cancel_per_min")),
                    "orders_active": _safe_float(row.get("orders_active")),
                    "fills_count_today": _safe_float(row.get("fills_count_today")),
                    "fees_paid_today_quote": _safe_float(row.get("fees_paid_today_quote")),
                    "risk_reasons": str(row.get("risk_reasons", "")),
                    "bot_mode": str(row.get("bot_mode", "")),
                    "accounting_source": str(row.get("accounting_source", "")),
                    "mid": _safe_float(row.get("mid")),
                    "spread_pct": _safe_float(row.get("spread_pct")),
                    "net_edge_pct": _safe_float(row.get("net_edge_pct")),
                    "turnover_today_x": _safe_float(row.get("turnover_today_x") or row.get("turnover_x")),
                    "raw_payload": json.dumps(row, ensure_ascii=True),
                    "source_path": source_path,
                    "ingest_ts_utc": ingest_ts_utc,
                    "schema_version": SCHEMA_VERSION,
                }
                cur.execute(sql, payload)
                inserted += 1
    return inserted


def _ingest_daily(conn: psycopg.Connection, data_root: Path, ingest_ts_utc: str) -> int:
    inserted = 0
    sql = """
    INSERT INTO bot_daily (
      bot, variant, day_utc, ts_utc, exchange, trading_pair, state, equity_open_quote, equity_now_quote,
      pnl_quote, pnl_pct, turnover_x, fills_count, ops_events, source_path, ingest_ts_utc, schema_version
    )
    VALUES (
      %(bot)s, %(variant)s, %(day_utc)s, %(ts_utc)s, %(exchange)s, %(trading_pair)s, %(state)s, %(equity_open_quote)s,
      %(equity_now_quote)s, %(pnl_quote)s, %(pnl_pct)s, %(turnover_x)s, %(fills_count)s, %(ops_events)s, %(source_path)s,
      %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (bot, variant, day_utc) DO UPDATE SET
      ts_utc = EXCLUDED.ts_utc,
      exchange = EXCLUDED.exchange,
      trading_pair = EXCLUDED.trading_pair,
      state = EXCLUDED.state,
      equity_open_quote = EXCLUDED.equity_open_quote,
      equity_now_quote = EXCLUDED.equity_now_quote,
      pnl_quote = EXCLUDED.pnl_quote,
      pnl_pct = EXCLUDED.pnl_pct,
      turnover_x = EXCLUDED.turnover_x,
      fills_count = EXCLUDED.fills_count,
      ops_events = EXCLUDED.ops_events,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    with conn.cursor() as cur:
        for daily_file in data_root.glob("*/logs/epp_v24/*/daily.csv"):
            try:
                bot = daily_file.parts[-5]
                variant = daily_file.parts[-2]
            except Exception:
                continue
            source_path = _source_abs(daily_file)
            for row in _read_csv_rows(daily_file):
                ts = str(row.get("ts", "")).strip()
                dt = _parse_ts(ts)
                if dt is None:
                    continue
                payload = {
                    "bot": bot,
                    "variant": variant,
                    "day_utc": dt.date().isoformat(),
                    "ts_utc": ts,
                    "exchange": str(row.get("exchange", "")),
                    "trading_pair": str(row.get("trading_pair", "")),
                    "state": str(row.get("state", "")),
                    "equity_open_quote": _safe_float(row.get("equity_open_quote")),
                    "equity_now_quote": _safe_float(row.get("equity_now_quote")),
                    "pnl_quote": _safe_float(row.get("pnl_quote")),
                    "pnl_pct": _safe_float(row.get("pnl_pct")),
                    "turnover_x": _safe_float(row.get("turnover_x")),
                    "fills_count": _safe_float(row.get("fills_count")),
                    "ops_events": str(row.get("ops_events", "")),
                    "source_path": source_path,
                    "ingest_ts_utc": ingest_ts_utc,
                    "schema_version": SCHEMA_VERSION,
                }
                cur.execute(sql, payload)
                inserted += 1
    return inserted


def _ingest_fills(conn: psycopg.Connection, data_root: Path, ingest_ts_utc: str) -> int:
    inserted = 0
    sql = """
    INSERT INTO fills (
      fill_key, bot, variant, ts_utc, trade_id, order_id, side, exchange, trading_pair, state, price,
      amount, amount_base, notional_quote, fee_paid_quote, fee_quote, mid_ref, expected_spread_pct,
      adverse_drift_30s, fee_source, is_maker, realized_pnl_quote, raw_payload, source_path, ingest_ts_utc, schema_version
    )
    VALUES (
      %(fill_key)s, %(bot)s, %(variant)s, %(ts_utc)s, %(trade_id)s, %(order_id)s, %(side)s, %(exchange)s, %(trading_pair)s, %(state)s,
      %(price)s, %(amount)s, %(amount_base)s, %(notional_quote)s, %(fee_paid_quote)s, %(fee_quote)s, %(mid_ref)s,
      %(expected_spread_pct)s, %(adverse_drift_30s)s, %(fee_source)s, %(is_maker)s, %(realized_pnl_quote)s,
      %(raw_payload)s::jsonb, %(source_path)s, %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (fill_key, ts_utc) DO UPDATE SET
      ts_utc = EXCLUDED.ts_utc,
      trade_id = EXCLUDED.trade_id,
      order_id = EXCLUDED.order_id,
      side = EXCLUDED.side,
      exchange = EXCLUDED.exchange,
      trading_pair = EXCLUDED.trading_pair,
      state = EXCLUDED.state,
      price = EXCLUDED.price,
      amount = EXCLUDED.amount,
      amount_base = EXCLUDED.amount_base,
      notional_quote = EXCLUDED.notional_quote,
      fee_paid_quote = EXCLUDED.fee_paid_quote,
      fee_quote = EXCLUDED.fee_quote,
      mid_ref = EXCLUDED.mid_ref,
      expected_spread_pct = EXCLUDED.expected_spread_pct,
      adverse_drift_30s = EXCLUDED.adverse_drift_30s,
      fee_source = EXCLUDED.fee_source,
      is_maker = EXCLUDED.is_maker,
      realized_pnl_quote = EXCLUDED.realized_pnl_quote,
      raw_payload = EXCLUDED.raw_payload,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    with conn.cursor() as cur:
        for fills_file in data_root.glob("*/logs/epp_v24/*/fills.csv"):
            try:
                bot = fills_file.parts[-5]
                variant = fills_file.parts[-2]
            except Exception:
                continue
            source_path = _source_abs(fills_file)
            for idx, row in enumerate(_read_csv_rows(fills_file), start=2):
                amount_base = _safe_float(row.get("amount_base"), _safe_float(row.get("amount"), 0.0))
                fee_quote = _safe_float(row.get("fee_quote"), _safe_float(row.get("fee_paid_quote"), 0.0))
                payload = {
                    "fill_key": _fill_key(source_path, idx, row),
                    "bot": bot,
                    "variant": variant,
                    "ts_utc": _canonical_ts_utc(row.get("ts"), _EPOCH_TS_UTC),
                    "trade_id": str(row.get("trade_id", "")).strip() or None,
                    "order_id": str(row.get("order_id", "")).strip() or None,
                    "side": str(row.get("side", "")).strip() or None,
                    "exchange": str(row.get("exchange", "")).strip() or None,
                    "trading_pair": str(row.get("trading_pair", "")).strip() or None,
                    "state": str(row.get("state", "")).strip() or None,
                    "price": _safe_float(row.get("price"), 0.0),
                    # Keep legacy amount/fee_paid_quote populated for existing dashboards/queries.
                    "amount": amount_base,
                    "amount_base": amount_base,
                    "notional_quote": _safe_float(row.get("notional_quote"), 0.0),
                    "fee_paid_quote": fee_quote,
                    "fee_quote": fee_quote,
                    "mid_ref": _safe_float(row.get("mid_ref")),
                    "expected_spread_pct": _safe_float(row.get("expected_spread_pct")),
                    "adverse_drift_30s": _safe_float(row.get("adverse_drift_30s")),
                    "fee_source": str(row.get("fee_source", "")).strip() or None,
                    "is_maker": _safe_bool(row.get("is_maker"), False),
                    "realized_pnl_quote": _safe_float(row.get("realized_pnl_quote"), 0.0),
                    "raw_payload": json.dumps(row, ensure_ascii=True),
                    "source_path": source_path,
                    "ingest_ts_utc": ingest_ts_utc,
                    "schema_version": SCHEMA_VERSION,
                }
                cur.execute(sql, payload)
                inserted += 1
    return inserted


def _ingest_event_envelope_raw(conn: psycopg.Connection, reports_root: Path, ingest_ts_utc: str) -> int:
    inserted = 0
    checkpoint_id = "event_store_event_envelope_raw_v1"
    sql = """
    INSERT INTO event_envelope_raw (
      stream, stream_entry_id, event_id, event_type, event_version, ts_utc, producer, instance_name,
      controller_id, connector_name, trading_pair, correlation_id, schema_validation_status, payload,
      ingest_ts_utc, schema_version
    )
    VALUES (
      %(stream)s, %(stream_entry_id)s, %(event_id)s, %(event_type)s, %(event_version)s, %(ts_utc)s, %(producer)s, %(instance_name)s,
      %(controller_id)s, %(connector_name)s, %(trading_pair)s, %(correlation_id)s, %(schema_validation_status)s, %(payload)s::jsonb,
      %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (stream, stream_entry_id, ts_utc) DO UPDATE SET
      event_id = EXCLUDED.event_id,
      event_type = EXCLUDED.event_type,
      event_version = EXCLUDED.event_version,
      producer = EXCLUDED.producer,
      instance_name = EXCLUDED.instance_name,
      controller_id = EXCLUDED.controller_id,
      connector_name = EXCLUDED.connector_name,
      trading_pair = EXCLUDED.trading_pair,
      correlation_id = EXCLUDED.correlation_id,
      schema_validation_status = EXCLUDED.schema_validation_status,
      payload = EXCLUDED.payload,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    select_checkpoint_sql = """
    SELECT source_path, source_line
    FROM event_envelope_ingest_checkpoint
    WHERE checkpoint_id = %(checkpoint_id)s
    """
    upsert_checkpoint_sql = """
    INSERT INTO event_envelope_ingest_checkpoint (checkpoint_id, source_path, source_line, updated_ts_utc)
    VALUES (%(checkpoint_id)s, %(source_path)s, %(source_line)s, %(updated_ts_utc)s)
    ON CONFLICT (checkpoint_id) DO UPDATE SET
      source_path = EXCLUDED.source_path,
      source_line = EXCLUDED.source_line,
      updated_ts_utc = EXCLUDED.updated_ts_utc
    """
    event_store_root = reports_root / "event_store"
    checkpoint_source_path = ""
    checkpoint_source_line = 0
    with conn.cursor() as cur:
        cur.execute(select_checkpoint_sql, {"checkpoint_id": checkpoint_id})
        checkpoint_row = None
        fetchone = getattr(cur, "fetchone", None)
        if callable(fetchone):
            checkpoint_row = fetchone()
        if isinstance(checkpoint_row, (list, tuple)) and len(checkpoint_row) >= 2:
            checkpoint_source_path = str(checkpoint_row[0] or "")
            checkpoint_source_line = int(checkpoint_row[1] or 0)

        event_files = sorted(event_store_root.glob("events_*.jsonl"))
        latest_seen_path = checkpoint_source_path
        latest_seen_line = checkpoint_source_line

        for jsonl_path in event_files:
            source_path = _source_abs(jsonl_path)
            if checkpoint_source_path and source_path < checkpoint_source_path:
                continue
            start_line = checkpoint_source_line + 1 if source_path == checkpoint_source_path else 1
            for line_idx, row in _iter_jsonl_rows(jsonl_path, start_line=start_line):
                latest_seen_path = source_path
                latest_seen_line = line_idx
                stream = str(row.get("stream", "")).strip() or "unknown"
                stream_entry_id = str(row.get("stream_entry_id", "")).strip()
                if not stream_entry_id:
                    fallback_key = hashlib.sha256(
                        f"{source_path}|{line_idx}|{stream}".encode("utf-8")
                    ).hexdigest()
                    stream_entry_id = f"event:{fallback_key}"

                ts_hint = _stream_entry_id_to_ts_utc(stream_entry_id) or _canonical_ts_utc(
                    row.get("ingest_ts_utc"),
                    ingest_ts_utc,
                )
                ts_utc = _canonical_ts_utc(row.get("ts_utc"), ts_hint)

                payload_obj = row.get("payload", {})
                if not isinstance(payload_obj, dict):
                    payload_obj = {"value": payload_obj}
                event_id = str(row.get("event_id") or payload_obj.get("event_id") or "").strip()
                if not event_id:
                    event_id = hashlib.sha256(
                        f"{stream}|{stream_entry_id}|{ts_utc}".encode("utf-8")
                    ).hexdigest()

                payload = {
                    "stream": stream,
                    "stream_entry_id": stream_entry_id,
                    "event_id": event_id,
                    "event_type": str(row.get("event_type", "")).strip() or None,
                    "event_version": str(row.get("event_version", "v1")).strip() or "v1",
                    "ts_utc": ts_utc,
                    "producer": str(row.get("producer", "")).strip() or None,
                    "instance_name": str(row.get("instance_name", "")).strip() or None,
                    "controller_id": str(row.get("controller_id", "")).strip() or None,
                    "connector_name": str(row.get("connector_name", "")).strip() or None,
                    "trading_pair": str(row.get("trading_pair", "")).strip() or None,
                    "correlation_id": str(row.get("correlation_id", "")).strip() or None,
                    "schema_validation_status": str(row.get("schema_validation_status", "ok")).strip() or "ok",
                    "payload": json.dumps(payload_obj, ensure_ascii=True),
                    "ingest_ts_utc": _canonical_ts_utc(row.get("ingest_ts_utc"), ingest_ts_utc),
                    "schema_version": SCHEMA_VERSION,
                }
                cur.execute(sql, payload)
                inserted += 1

        if latest_seen_path:
            cur.execute(
                upsert_checkpoint_sql,
                {
                    "checkpoint_id": checkpoint_id,
                    "source_path": latest_seen_path,
                    "source_line": int(latest_seen_line),
                    "updated_ts_utc": ingest_ts_utc,
                },
            )
    return inserted


def _ingest_market_depth_layers(conn: psycopg.Connection, reports_root: Path, ingest_ts_utc: str) -> Dict[str, object]:
    checkpoint_id = "event_store_market_depth_v1"
    sample_every_n = max(1, _env_int("OPS_DB_L2_SAMPLE_EVERY_N", 10))
    sample_min_interval_ms = max(0, _env_int("OPS_DB_L2_SAMPLE_MIN_INTERVAL_MS", 1000))
    sample_levels = max(1, _env_int("OPS_DB_L2_SAMPLE_LEVELS", 20))
    raw_inserted = 0
    sampled_inserted = 0
    scanned_depth_events = 0
    checkpoint_source_path = ""
    checkpoint_source_line = 0

    event_store_root = reports_root / "event_store"
    rollup_accumulator: Dict[
        Tuple[str, str, str, str, str],
        Dict[str, float],
    ] = defaultdict(
        lambda: {
            "event_count": 0.0,
            "sum_spread_bps": 0.0,
            "sum_mid_price": 0.0,
            "sum_bid_depth_total": 0.0,
            "sum_ask_depth_total": 0.0,
            "sum_depth_imbalance": 0.0,
        }
    )
    pair_state: Dict[Tuple[str, str, str, str], Dict[str, int]] = defaultdict(
        lambda: {"counter": 0, "last_sample_ts_ms": -1}
    )

    select_checkpoint_sql = """
    SELECT source_path, source_line
    FROM market_depth_ingest_checkpoint
    WHERE checkpoint_id = %(checkpoint_id)s
    """
    upsert_checkpoint_sql = """
    INSERT INTO market_depth_ingest_checkpoint (checkpoint_id, source_path, source_line, updated_ts_utc)
    VALUES (%(checkpoint_id)s, %(source_path)s, %(source_line)s, %(updated_ts_utc)s)
    ON CONFLICT (checkpoint_id) DO UPDATE SET
      source_path = EXCLUDED.source_path,
      source_line = EXCLUDED.source_line,
      updated_ts_utc = EXCLUDED.updated_ts_utc
    """
    insert_raw_sql = """
    INSERT INTO market_depth_raw (
      stream_entry_id, event_id, ts_utc, instance_name, controller_id, connector_name, trading_pair,
      market_sequence, payload, source_path, source_line, ingest_ts_utc, schema_version
    )
    VALUES (
      %(stream_entry_id)s, %(event_id)s, %(ts_utc)s, %(instance_name)s, %(controller_id)s, %(connector_name)s,
      %(trading_pair)s, %(market_sequence)s, %(payload)s::jsonb, %(source_path)s, %(source_line)s, %(ingest_ts_utc)s,
      %(schema_version)s
    )
    ON CONFLICT (stream_entry_id, ts_utc) DO UPDATE SET
      event_id = EXCLUDED.event_id,
      instance_name = EXCLUDED.instance_name,
      controller_id = EXCLUDED.controller_id,
      connector_name = EXCLUDED.connector_name,
      trading_pair = EXCLUDED.trading_pair,
      market_sequence = EXCLUDED.market_sequence,
      payload = EXCLUDED.payload,
      source_path = EXCLUDED.source_path,
      source_line = EXCLUDED.source_line,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    insert_sampled_sql = """
    INSERT INTO market_depth_sampled (
      stream_entry_id, event_id, ts_utc, instance_name, controller_id, connector_name, trading_pair, depth_levels,
      best_bid, best_ask, spread_bps, mid_price, bid_depth_total, ask_depth_total, depth_imbalance, top_levels,
      source_path, source_line, ingest_ts_utc, schema_version
    )
    VALUES (
      %(stream_entry_id)s, %(event_id)s, %(ts_utc)s, %(instance_name)s, %(controller_id)s, %(connector_name)s, %(trading_pair)s,
      %(depth_levels)s, %(best_bid)s, %(best_ask)s, %(spread_bps)s, %(mid_price)s, %(bid_depth_total)s, %(ask_depth_total)s,
      %(depth_imbalance)s, %(top_levels)s::jsonb, %(source_path)s, %(source_line)s, %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (stream_entry_id, ts_utc) DO UPDATE SET
      event_id = EXCLUDED.event_id,
      instance_name = EXCLUDED.instance_name,
      controller_id = EXCLUDED.controller_id,
      connector_name = EXCLUDED.connector_name,
      trading_pair = EXCLUDED.trading_pair,
      depth_levels = EXCLUDED.depth_levels,
      best_bid = EXCLUDED.best_bid,
      best_ask = EXCLUDED.best_ask,
      spread_bps = EXCLUDED.spread_bps,
      mid_price = EXCLUDED.mid_price,
      bid_depth_total = EXCLUDED.bid_depth_total,
      ask_depth_total = EXCLUDED.ask_depth_total,
      depth_imbalance = EXCLUDED.depth_imbalance,
      top_levels = EXCLUDED.top_levels,
      source_path = EXCLUDED.source_path,
      source_line = EXCLUDED.source_line,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    upsert_rollup_sql = """
    INSERT INTO market_depth_rollup_minute (
      bucket_minute_utc, instance_name, controller_id, connector_name, trading_pair, event_count, avg_spread_bps,
      avg_mid_price, avg_bid_depth_total, avg_ask_depth_total, avg_depth_imbalance, source_path, ingest_ts_utc, schema_version
    )
    VALUES (
      %(bucket_minute_utc)s, %(instance_name)s, %(controller_id)s, %(connector_name)s, %(trading_pair)s, %(event_count)s,
      %(avg_spread_bps)s, %(avg_mid_price)s, %(avg_bid_depth_total)s, %(avg_ask_depth_total)s, %(avg_depth_imbalance)s,
      %(source_path)s, %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (bucket_minute_utc, instance_name, controller_id, connector_name, trading_pair) DO UPDATE SET
      event_count = market_depth_rollup_minute.event_count + EXCLUDED.event_count,
      avg_spread_bps = CASE
        WHEN (market_depth_rollup_minute.event_count + EXCLUDED.event_count) = 0 THEN NULL
        ELSE (
          (COALESCE(market_depth_rollup_minute.avg_spread_bps, 0.0) * market_depth_rollup_minute.event_count)
          + (COALESCE(EXCLUDED.avg_spread_bps, 0.0) * EXCLUDED.event_count)
        ) / (market_depth_rollup_minute.event_count + EXCLUDED.event_count)
      END,
      avg_mid_price = CASE
        WHEN (market_depth_rollup_minute.event_count + EXCLUDED.event_count) = 0 THEN NULL
        ELSE (
          (COALESCE(market_depth_rollup_minute.avg_mid_price, 0.0) * market_depth_rollup_minute.event_count)
          + (COALESCE(EXCLUDED.avg_mid_price, 0.0) * EXCLUDED.event_count)
        ) / (market_depth_rollup_minute.event_count + EXCLUDED.event_count)
      END,
      avg_bid_depth_total = CASE
        WHEN (market_depth_rollup_minute.event_count + EXCLUDED.event_count) = 0 THEN NULL
        ELSE (
          (COALESCE(market_depth_rollup_minute.avg_bid_depth_total, 0.0) * market_depth_rollup_minute.event_count)
          + (COALESCE(EXCLUDED.avg_bid_depth_total, 0.0) * EXCLUDED.event_count)
        ) / (market_depth_rollup_minute.event_count + EXCLUDED.event_count)
      END,
      avg_ask_depth_total = CASE
        WHEN (market_depth_rollup_minute.event_count + EXCLUDED.event_count) = 0 THEN NULL
        ELSE (
          (COALESCE(market_depth_rollup_minute.avg_ask_depth_total, 0.0) * market_depth_rollup_minute.event_count)
          + (COALESCE(EXCLUDED.avg_ask_depth_total, 0.0) * EXCLUDED.event_count)
        ) / (market_depth_rollup_minute.event_count + EXCLUDED.event_count)
      END,
      avg_depth_imbalance = CASE
        WHEN (market_depth_rollup_minute.event_count + EXCLUDED.event_count) = 0 THEN NULL
        ELSE (
          (COALESCE(market_depth_rollup_minute.avg_depth_imbalance, 0.0) * market_depth_rollup_minute.event_count)
          + (COALESCE(EXCLUDED.avg_depth_imbalance, 0.0) * EXCLUDED.event_count)
        ) / (market_depth_rollup_minute.event_count + EXCLUDED.event_count)
      END,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """

    with conn.cursor() as cur:
        cur.execute(select_checkpoint_sql, {"checkpoint_id": checkpoint_id})
        checkpoint_row = None
        fetchone = getattr(cur, "fetchone", None)
        if callable(fetchone):
            checkpoint_row = fetchone()
        if isinstance(checkpoint_row, (list, tuple)) and len(checkpoint_row) >= 2:
            checkpoint_source_path = str(checkpoint_row[0] or "")
            checkpoint_source_line = int(checkpoint_row[1] or 0)

        event_files = sorted(event_store_root.glob("events_*.jsonl"))
        latest_seen_path = checkpoint_source_path
        latest_seen_line = checkpoint_source_line

        for jsonl_path in event_files:
            source_path = _source_abs(jsonl_path)
            if checkpoint_source_path and source_path < checkpoint_source_path:
                continue
            start_line = checkpoint_source_line + 1 if source_path == checkpoint_source_path else 1
            for line_idx, row in _iter_jsonl_rows(jsonl_path, start_line=start_line):
                latest_seen_path = source_path
                latest_seen_line = line_idx

                stream = str(row.get("stream", "")).strip()
                event_type = str(row.get("event_type", "")).strip()
                if stream != MARKET_DEPTH_STREAM and event_type != "market_depth_snapshot":
                    continue
                payload_obj = row.get("payload", {})
                if not isinstance(payload_obj, dict):
                    continue

                scanned_depth_events += 1
                stream_entry_id = str(row.get("stream_entry_id", "")).strip()
                if not stream_entry_id:
                    stream_entry_id = "event:" + hashlib.sha256(
                        f"{source_path}|{line_idx}|{MARKET_DEPTH_STREAM}".encode("utf-8")
                    ).hexdigest()
                ts_hint = _stream_entry_id_to_ts_utc(stream_entry_id) or _canonical_ts_utc(
                    row.get("ingest_ts_utc"), ingest_ts_utc
                )
                ts_utc = _canonical_ts_utc(row.get("ts_utc"), ts_hint)

                bids = _normalize_depth_levels(payload_obj.get("bids"), sample_levels)
                asks = _normalize_depth_levels(payload_obj.get("asks"), sample_levels)
                metrics = _depth_metrics(bids, asks)
                best_bid = _safe_float(payload_obj.get("best_bid"), metrics.get("best_bid"))
                best_ask = _safe_float(payload_obj.get("best_ask"), metrics.get("best_ask"))
                spread_bps = metrics.get("spread_bps")
                mid_price = metrics.get("mid_price")
                bid_depth_total = metrics.get("bid_depth_total")
                ask_depth_total = metrics.get("ask_depth_total")
                depth_imbalance = metrics.get("depth_imbalance")

                event_id = str(row.get("event_id") or payload_obj.get("event_id") or "").strip()
                if not event_id:
                    event_id = hashlib.sha256(
                        f"{stream_entry_id}|{ts_utc}|market_depth_snapshot".encode("utf-8")
                    ).hexdigest()

                market_sequence = _safe_float(payload_obj.get("market_sequence"))
                raw_row = {
                    "stream_entry_id": stream_entry_id,
                    "event_id": event_id,
                    "ts_utc": ts_utc,
                    "instance_name": str(row.get("instance_name") or payload_obj.get("instance_name") or "").strip() or None,
                    "controller_id": str(row.get("controller_id") or payload_obj.get("controller_id") or "").strip() or None,
                    "connector_name": str(row.get("connector_name") or payload_obj.get("connector_name") or "").strip() or None,
                    "trading_pair": str(row.get("trading_pair") or payload_obj.get("trading_pair") or "").strip() or None,
                    "market_sequence": int(market_sequence) if market_sequence is not None else None,
                    "payload": json.dumps(payload_obj, ensure_ascii=True),
                    "source_path": source_path,
                    "source_line": int(line_idx),
                    "ingest_ts_utc": ingest_ts_utc,
                    "schema_version": SCHEMA_VERSION,
                }
                cur.execute(insert_raw_sql, raw_row)
                raw_inserted += 1

                pair_key = (
                    str(raw_row.get("instance_name") or ""),
                    str(raw_row.get("controller_id") or ""),
                    str(raw_row.get("connector_name") or ""),
                    str(raw_row.get("trading_pair") or ""),
                )
                state = pair_state[pair_key]
                state["counter"] += 1
                stream_ms = _safe_float(stream_entry_id.split("-", 1)[0], -1.0) or -1.0
                should_sample = (state["counter"] % sample_every_n == 0)
                if sample_min_interval_ms > 0 and stream_ms > 0:
                    last_sample_ms = int(state["last_sample_ts_ms"])
                    if last_sample_ms < 0 or (int(stream_ms) - last_sample_ms) >= sample_min_interval_ms:
                        should_sample = True
                if not should_sample:
                    continue
                if stream_ms > 0:
                    state["last_sample_ts_ms"] = int(stream_ms)

                top_levels = {"bids": bids, "asks": asks}
                sampled_row = {
                    "stream_entry_id": stream_entry_id,
                    "event_id": event_id,
                    "ts_utc": ts_utc,
                    "instance_name": raw_row["instance_name"],
                    "controller_id": raw_row["controller_id"],
                    "connector_name": raw_row["connector_name"],
                    "trading_pair": raw_row["trading_pair"],
                    "depth_levels": int(payload_obj.get("depth_levels") or sample_levels),
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "spread_bps": spread_bps,
                    "mid_price": mid_price,
                    "bid_depth_total": bid_depth_total,
                    "ask_depth_total": ask_depth_total,
                    "depth_imbalance": depth_imbalance,
                    "top_levels": json.dumps(top_levels, ensure_ascii=True),
                    "source_path": source_path,
                    "source_line": int(line_idx),
                    "ingest_ts_utc": ingest_ts_utc,
                    "schema_version": SCHEMA_VERSION,
                }
                cur.execute(insert_sampled_sql, sampled_row)
                sampled_inserted += 1

                rollup_key = (
                    _floor_minute_utc(ts_utc),
                    str(sampled_row.get("instance_name") or ""),
                    str(sampled_row.get("controller_id") or ""),
                    str(sampled_row.get("connector_name") or ""),
                    str(sampled_row.get("trading_pair") or ""),
                )
                acc = rollup_accumulator[rollup_key]
                acc["event_count"] += 1.0
                acc["sum_spread_bps"] += float(spread_bps or 0.0)
                acc["sum_mid_price"] += float(mid_price or 0.0)
                acc["sum_bid_depth_total"] += float(bid_depth_total or 0.0)
                acc["sum_ask_depth_total"] += float(ask_depth_total or 0.0)
                acc["sum_depth_imbalance"] += float(depth_imbalance or 0.0)

        for rollup_key, acc in rollup_accumulator.items():
            bucket_minute_utc, instance_name, controller_id, connector_name, trading_pair = rollup_key
            event_count = int(acc["event_count"])
            if event_count <= 0:
                continue
            cur.execute(
                upsert_rollup_sql,
                {
                    "bucket_minute_utc": bucket_minute_utc,
                    "instance_name": instance_name,
                    "controller_id": controller_id,
                    "connector_name": connector_name,
                    "trading_pair": trading_pair,
                    "event_count": event_count,
                    "avg_spread_bps": acc["sum_spread_bps"] / event_count,
                    "avg_mid_price": acc["sum_mid_price"] / event_count,
                    "avg_bid_depth_total": acc["sum_bid_depth_total"] / event_count,
                    "avg_ask_depth_total": acc["sum_ask_depth_total"] / event_count,
                    "avg_depth_imbalance": acc["sum_depth_imbalance"] / event_count,
                    "source_path": latest_seen_path or checkpoint_source_path,
                    "ingest_ts_utc": ingest_ts_utc,
                    "schema_version": SCHEMA_VERSION,
                },
            )

        if latest_seen_path:
            cur.execute(
                upsert_checkpoint_sql,
                {
                    "checkpoint_id": checkpoint_id,
                    "source_path": latest_seen_path,
                    "source_line": int(latest_seen_line),
                    "updated_ts_utc": ingest_ts_utc,
                },
            )
            checkpoint_source_path = latest_seen_path
            checkpoint_source_line = int(latest_seen_line)

    return {
        "raw_inserted": raw_inserted,
        "sampled_inserted": sampled_inserted,
        "rollup_upserts": len(rollup_accumulator),
        "depth_events_scanned": scanned_depth_events,
        "checkpoint_source_path": checkpoint_source_path,
        "checkpoint_source_line": checkpoint_source_line,
        "sample_every_n": sample_every_n,
        "sample_min_interval_ms": sample_min_interval_ms,
        "sample_levels": sample_levels,
    }


def _ingest_market_quote_layers(conn: psycopg.Connection, reports_root: Path, ingest_ts_utc: str) -> Dict[str, object]:
    checkpoint_id = "event_store_market_quote_v1"
    raw_inserted = 0
    scanned_quote_events = 0
    checkpoint_source_path = ""
    checkpoint_source_line = 0
    event_store_root = reports_root / "event_store"
    rollup_accumulator: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    select_checkpoint_sql = """
    SELECT source_path, source_line
    FROM market_quote_ingest_checkpoint
    WHERE checkpoint_id = %(checkpoint_id)s
    """
    upsert_checkpoint_sql = """
    INSERT INTO market_quote_ingest_checkpoint (checkpoint_id, source_path, source_line, updated_ts_utc)
    VALUES (%(checkpoint_id)s, %(source_path)s, %(source_line)s, %(updated_ts_utc)s)
    ON CONFLICT (checkpoint_id) DO UPDATE SET
      source_path = EXCLUDED.source_path,
      source_line = EXCLUDED.source_line,
      updated_ts_utc = EXCLUDED.updated_ts_utc
    """
    insert_raw_sql = """
    INSERT INTO market_quote_raw (
      stream_entry_id, event_id, ts_utc, connector_name, trading_pair, best_bid, best_ask, best_bid_size, best_ask_size,
      mid_price, last_trade_price, market_sequence, payload, source_path, source_line, ingest_ts_utc, schema_version
    )
    VALUES (
      %(stream_entry_id)s, %(event_id)s, %(ts_utc)s, %(connector_name)s, %(trading_pair)s, %(best_bid)s, %(best_ask)s,
      %(best_bid_size)s, %(best_ask_size)s, %(mid_price)s, %(last_trade_price)s, %(market_sequence)s, %(payload)s::jsonb,
      %(source_path)s, %(source_line)s, %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (stream_entry_id, ts_utc) DO UPDATE SET
      event_id = EXCLUDED.event_id,
      connector_name = EXCLUDED.connector_name,
      trading_pair = EXCLUDED.trading_pair,
      best_bid = EXCLUDED.best_bid,
      best_ask = EXCLUDED.best_ask,
      best_bid_size = EXCLUDED.best_bid_size,
      best_ask_size = EXCLUDED.best_ask_size,
      mid_price = EXCLUDED.mid_price,
      last_trade_price = EXCLUDED.last_trade_price,
      market_sequence = EXCLUDED.market_sequence,
      payload = EXCLUDED.payload,
      source_path = EXCLUDED.source_path,
      source_line = EXCLUDED.source_line,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    upsert_bar_sql = """
    INSERT INTO market_quote_bar_minute (
      bucket_minute_utc, connector_name, trading_pair, event_count, first_ts_utc, last_ts_utc,
      open_price, high_price, low_price, close_price, source_path, ingest_ts_utc, schema_version
    )
    VALUES (
      %(bucket_minute_utc)s, %(connector_name)s, %(trading_pair)s, %(event_count)s, %(first_ts_utc)s, %(last_ts_utc)s,
      %(open_price)s, %(high_price)s, %(low_price)s, %(close_price)s, %(source_path)s, %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (bucket_minute_utc, connector_name, trading_pair) DO UPDATE SET
      event_count = market_quote_bar_minute.event_count + EXCLUDED.event_count,
      first_ts_utc = LEAST(market_quote_bar_minute.first_ts_utc, EXCLUDED.first_ts_utc),
      last_ts_utc = GREATEST(market_quote_bar_minute.last_ts_utc, EXCLUDED.last_ts_utc),
      open_price = CASE
        WHEN EXCLUDED.first_ts_utc < market_quote_bar_minute.first_ts_utc THEN EXCLUDED.open_price
        ELSE market_quote_bar_minute.open_price
      END,
      high_price = GREATEST(market_quote_bar_minute.high_price, EXCLUDED.high_price),
      low_price = LEAST(market_quote_bar_minute.low_price, EXCLUDED.low_price),
      close_price = CASE
        WHEN EXCLUDED.last_ts_utc >= market_quote_bar_minute.last_ts_utc THEN EXCLUDED.close_price
        ELSE market_quote_bar_minute.close_price
      END,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """

    with conn.cursor() as cur:
        cur.execute(select_checkpoint_sql, {"checkpoint_id": checkpoint_id})
        checkpoint_row = None
        fetchone = getattr(cur, "fetchone", None)
        if callable(fetchone):
            checkpoint_row = fetchone()
        if isinstance(checkpoint_row, (list, tuple)) and len(checkpoint_row) >= 2:
            checkpoint_source_path = str(checkpoint_row[0] or "")
            checkpoint_source_line = int(checkpoint_row[1] or 0)

        event_files = sorted(event_store_root.glob("events_*.jsonl"))
        latest_seen_path = checkpoint_source_path
        latest_seen_line = checkpoint_source_line

        for jsonl_path in event_files:
            source_path = _source_abs(jsonl_path)
            if checkpoint_source_path and source_path < checkpoint_source_path:
                continue
            start_line = checkpoint_source_line + 1 if source_path == checkpoint_source_path else 1
            for line_idx, row in _iter_jsonl_rows(jsonl_path, start_line=start_line):
                latest_seen_path = source_path
                latest_seen_line = line_idx

                stream = str(row.get("stream", "")).strip()
                event_type = str(row.get("event_type", "")).strip()
                if stream != MARKET_QUOTE_STREAM and event_type != "market_quote":
                    continue
                payload_obj = row.get("payload", {})
                if not isinstance(payload_obj, dict):
                    continue

                best_bid = _safe_float(payload_obj.get("best_bid"))
                best_ask = _safe_float(payload_obj.get("best_ask"))
                mid_price = _safe_float(payload_obj.get("mid_price"))
                if mid_price is None and best_bid is not None and best_ask is not None and best_ask >= best_bid:
                    mid_price = (best_bid + best_ask) / 2.0
                if mid_price is None:
                    mid_price = _safe_float(payload_obj.get("last_trade_price"))
                if mid_price is None or mid_price <= 0:
                    continue

                scanned_quote_events += 1
                stream_entry_id = str(row.get("stream_entry_id", "")).strip()
                if not stream_entry_id:
                    stream_entry_id = "event:" + hashlib.sha256(
                        f"{source_path}|{line_idx}|{MARKET_QUOTE_STREAM}".encode("utf-8")
                    ).hexdigest()
                ts_hint = _stream_entry_id_to_ts_utc(stream_entry_id) or _canonical_ts_utc(row.get("ingest_ts_utc"), ingest_ts_utc)
                ts_utc = _canonical_ts_utc(row.get("ts_utc"), ts_hint)
                connector_name = str(row.get("connector_name") or payload_obj.get("connector_name") or "").strip()
                trading_pair = str(row.get("trading_pair") or payload_obj.get("trading_pair") or "").strip()
                event_id = str(row.get("event_id") or payload_obj.get("event_id") or "").strip()
                if not event_id:
                    event_id = hashlib.sha256(f"{stream_entry_id}|{ts_utc}|market_quote".encode("utf-8")).hexdigest()
                market_sequence = _safe_float(payload_obj.get("market_sequence"))

                raw_row = {
                    "stream_entry_id": stream_entry_id,
                    "event_id": event_id,
                    "ts_utc": ts_utc,
                    "connector_name": connector_name,
                    "trading_pair": trading_pair,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "best_bid_size": _safe_float(payload_obj.get("best_bid_size")),
                    "best_ask_size": _safe_float(payload_obj.get("best_ask_size")),
                    "mid_price": mid_price,
                    "last_trade_price": _safe_float(payload_obj.get("last_trade_price")),
                    "market_sequence": int(market_sequence) if market_sequence is not None else None,
                    "payload": json.dumps(payload_obj, ensure_ascii=True),
                    "source_path": source_path,
                    "source_line": int(line_idx),
                    "ingest_ts_utc": ingest_ts_utc,
                    "schema_version": SCHEMA_VERSION,
                }
                cur.execute(insert_raw_sql, raw_row)
                raw_inserted += 1

                rollup_key = (_floor_minute_utc(ts_utc), connector_name, trading_pair)
                acc = rollup_accumulator.get(rollup_key)
                if acc is None:
                    rollup_accumulator[rollup_key] = {
                        "event_count": 1,
                        "first_ts_utc": ts_utc,
                        "last_ts_utc": ts_utc,
                        "open_price": mid_price,
                        "high_price": mid_price,
                        "low_price": mid_price,
                        "close_price": mid_price,
                        "source_path": source_path,
                    }
                else:
                    acc["event_count"] = int(acc["event_count"]) + 1
                    if ts_utc < str(acc["first_ts_utc"]):
                        acc["first_ts_utc"] = ts_utc
                        acc["open_price"] = mid_price
                    if ts_utc >= str(acc["last_ts_utc"]):
                        acc["last_ts_utc"] = ts_utc
                        acc["close_price"] = mid_price
                    acc["high_price"] = max(float(acc["high_price"]), mid_price)
                    acc["low_price"] = min(float(acc["low_price"]), mid_price)
                    acc["source_path"] = source_path

        for (bucket_minute_utc, connector_name, trading_pair), acc in rollup_accumulator.items():
            cur.execute(
                upsert_bar_sql,
                {
                    "bucket_minute_utc": bucket_minute_utc,
                    "connector_name": connector_name,
                    "trading_pair": trading_pair,
                    "event_count": int(acc["event_count"]),
                    "first_ts_utc": acc["first_ts_utc"],
                    "last_ts_utc": acc["last_ts_utc"],
                    "open_price": acc["open_price"],
                    "high_price": acc["high_price"],
                    "low_price": acc["low_price"],
                    "close_price": acc["close_price"],
                    "source_path": acc["source_path"],
                    "ingest_ts_utc": ingest_ts_utc,
                    "schema_version": SCHEMA_VERSION,
                },
            )

        if latest_seen_path:
            cur.execute(
                upsert_checkpoint_sql,
                {
                    "checkpoint_id": checkpoint_id,
                    "source_path": latest_seen_path,
                    "source_line": int(latest_seen_line),
                    "updated_ts_utc": ingest_ts_utc,
                },
            )
            checkpoint_source_path = latest_seen_path
            checkpoint_source_line = int(latest_seen_line)

    return {
        "raw_inserted": raw_inserted,
        "bar_upserts": len(rollup_accumulator),
        "quote_events_scanned": scanned_quote_events,
        "checkpoint_source_path": checkpoint_source_path,
        "checkpoint_source_line": checkpoint_source_line,
    }


def _ingest_exchange_snapshot(conn: psycopg.Connection, reports_root: Path, ingest_ts_utc: str) -> int:
    path = reports_root / "exchange_snapshots" / "latest.json"
    payload = _read_json(path)
    ts = str(payload.get("ts_utc", "")).strip()
    bots = payload.get("bots", {})
    if not ts or not isinstance(bots, dict):
        return 0
    sql = """
    INSERT INTO exchange_snapshot (
      bot, ts_utc, exchange, trading_pair, source, equity_quote, base_pct, account_probe_status,
      payload, source_path, ingest_ts_utc, schema_version
    )
    VALUES (
      %(bot)s, %(ts_utc)s, %(exchange)s, %(trading_pair)s, %(source)s, %(equity_quote)s, %(base_pct)s, %(account_probe_status)s,
      %(payload)s::jsonb, %(source_path)s, %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (bot, ts_utc) DO UPDATE SET
      exchange = EXCLUDED.exchange,
      trading_pair = EXCLUDED.trading_pair,
      source = EXCLUDED.source,
      equity_quote = EXCLUDED.equity_quote,
      base_pct = EXCLUDED.base_pct,
      account_probe_status = EXCLUDED.account_probe_status,
      payload = EXCLUDED.payload,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    count = 0
    with conn.cursor() as cur:
        for bot, bot_data in bots.items():
            if not isinstance(bot_data, dict):
                continue
            row = {
                "bot": str(bot),
                "ts_utc": ts,
                "exchange": str(bot_data.get("exchange", "")),
                "trading_pair": str(bot_data.get("trading_pair", "")),
                "source": str(bot_data.get("source", "")),
                "equity_quote": _safe_float(bot_data.get("equity_quote"), 0.0),
                "base_pct": _safe_float(bot_data.get("base_pct"), 0.0),
                "account_probe_status": str(bot_data.get("account_probe_status", "unknown")),
                "payload": json.dumps(bot_data),
                "source_path": _source_abs(path),
                "ingest_ts_utc": ingest_ts_utc,
                "schema_version": SCHEMA_VERSION,
            }
            cur.execute(sql, row)
            count += 1
    return count


def _ingest_single_report(
    conn: psycopg.Connection,
    report_path: Path,
    table: str,
    mapped_fields: Dict[str, str],
    ingest_ts_utc: str,
) -> int:
    payload = _read_json(report_path)
    ts = str(payload.get("ts_utc", "")).strip()
    if not ts:
        return 0

    cols = ["ts_utc"] + list(mapped_fields.keys()) + ["payload", "source_path", "ingest_ts_utc", "schema_version"]
    values = {col: None for col in cols}
    values["ts_utc"] = ts
    for col, key in mapped_fields.items():
        values[col] = payload.get(key)
    values["payload"] = json.dumps(payload)
    values["source_path"] = _source_abs(report_path)
    values["ingest_ts_utc"] = ingest_ts_utc
    values["schema_version"] = SCHEMA_VERSION

    set_cols = [c for c in cols if c != "ts_utc"]
    sql = f"""
    INSERT INTO {table} ({", ".join(cols)})
    VALUES ({", ".join([f"%({c})s::jsonb" if c == "payload" else f"%({c})s" for c in cols])})
    ON CONFLICT (ts_utc) DO UPDATE SET
      {", ".join([f"{c}=EXCLUDED.{c}" for c in set_cols])}
    """
    with conn.cursor() as cur:
        cur.execute(sql, values)
    return 1


def _ingest_accounting_snapshots(conn: psycopg.Connection, reports_root: Path, ingest_ts_utc: str) -> int:
    recon_path = reports_root / "reconciliation" / "latest.json"
    recon = _read_json(recon_path)
    ts = str(recon.get("ts_utc", "")).strip()
    snapshots = recon.get("accounting_snapshots", [])
    if not ts or not isinstance(snapshots, list):
        return 0

    sql = """
    INSERT INTO accounting_snapshot (
      bot, ts_utc, exchange, trading_pair, mid, equity_quote, base_balance, quote_balance, fees_paid_today_quote,
      funding_paid_today_quote, daily_loss_pct, drawdown_pct, fee_source, payload, source_path, ingest_ts_utc, schema_version
    )
    VALUES (
      %(bot)s, %(ts_utc)s, %(exchange)s, %(trading_pair)s, %(mid)s, %(equity_quote)s, %(base_balance)s, %(quote_balance)s, %(fees_paid_today_quote)s,
      %(funding_paid_today_quote)s, %(daily_loss_pct)s, %(drawdown_pct)s, %(fee_source)s, %(payload)s::jsonb, %(source_path)s, %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (bot, ts_utc) DO UPDATE SET
      exchange = EXCLUDED.exchange,
      trading_pair = EXCLUDED.trading_pair,
      mid = EXCLUDED.mid,
      equity_quote = EXCLUDED.equity_quote,
      base_balance = EXCLUDED.base_balance,
      quote_balance = EXCLUDED.quote_balance,
      fees_paid_today_quote = EXCLUDED.fees_paid_today_quote,
      funding_paid_today_quote = EXCLUDED.funding_paid_today_quote,
      daily_loss_pct = EXCLUDED.daily_loss_pct,
      drawdown_pct = EXCLUDED.drawdown_pct,
      fee_source = EXCLUDED.fee_source,
      payload = EXCLUDED.payload,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    count = 0
    with conn.cursor() as cur:
        for row in snapshots:
            if not isinstance(row, dict):
                continue
            payload = {
                "bot": str(row.get("bot", "")).strip(),
                "ts_utc": ts,
                "exchange": str(row.get("exchange", "")).strip(),
                "trading_pair": str(row.get("trading_pair", "")).strip(),
                "mid": _safe_float(row.get("mid"), 0.0),
                "equity_quote": _safe_float(row.get("equity_quote"), 0.0),
                "base_balance": _safe_float(row.get("base_balance"), 0.0),
                "quote_balance": _safe_float(row.get("quote_balance"), 0.0),
                "fees_paid_today_quote": _safe_float(row.get("fees_paid_today_quote"), 0.0),
                "funding_paid_today_quote": _safe_float(row.get("funding_paid_today_quote"), 0.0),
                "daily_loss_pct": _safe_float(row.get("daily_loss_pct"), 0.0),
                "drawdown_pct": _safe_float(row.get("drawdown_pct"), 0.0),
                "fee_source": str(row.get("fee_source", "")).strip(),
                "payload": json.dumps(row),
                "source_path": _source_abs(recon_path),
                "ingest_ts_utc": ingest_ts_utc,
                "schema_version": SCHEMA_VERSION,
            }
            if not payload["bot"]:
                continue
            cur.execute(sql, payload)
            count += 1
    return count


def _ingest_promotion_gates(conn: psycopg.Connection, reports_root: Path, ingest_ts_utc: str) -> int:
    sql = """
    INSERT INTO promotion_gate_run (
      run_id, ts_utc, status, critical_failures, payload, source_path, ingest_ts_utc, schema_version
    )
    VALUES (
      %(run_id)s, %(ts_utc)s, %(status)s, %(critical_failures)s::jsonb, %(payload)s::jsonb, %(source_path)s, %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (run_id) DO UPDATE SET
      ts_utc = EXCLUDED.ts_utc,
      status = EXCLUDED.status,
      critical_failures = EXCLUDED.critical_failures,
      payload = EXCLUDED.payload,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    count = 0
    with conn.cursor() as cur:
        for gate_file in sorted((reports_root / "promotion_gates").glob("promotion_gates_*.json")):
            payload = _read_json(gate_file)
            run_id = gate_file.stem
            row = {
                "run_id": run_id,
                "ts_utc": str(payload.get("ts_utc", "")).strip() or None,
                "status": str(payload.get("status", "")).strip() or None,
                "critical_failures": json.dumps(payload.get("critical_failures", [])),
                "payload": json.dumps(payload),
                "source_path": _source_abs(gate_file),
                "ingest_ts_utc": ingest_ts_utc,
                "schema_version": SCHEMA_VERSION,
            }
            cur.execute(sql, row)
            count += 1
    return count


def _ingest_paper_exchange_open_orders(conn: psycopg.Connection, reports_root: Path, ingest_ts_utc: str) -> int:
    snapshot_path = reports_root / "verification" / "paper_exchange_state_snapshot_latest.json"
    payload = _read_json(snapshot_path)
    if not isinstance(payload, dict):
        return 0
    orders = payload.get("orders", {})
    if not isinstance(orders, dict):
        orders = {}
    source_ts_utc = _canonical_ts_utc(payload.get("ts_utc"), default=ingest_ts_utc)
    terminal_states = {"filled", "canceled", "cancelled", "rejected", "expired", "failed", "closed"}
    sql_delete = "DELETE FROM paper_exchange_open_order_current"
    sql_insert = """
    INSERT INTO paper_exchange_open_order_current (
      instance_name, connector_name, trading_pair, order_id, side, order_type, amount_base, price, state,
      created_ts_utc, updated_ts_utc, source_ts_utc, payload, source_path, ingest_ts_utc, schema_version
    )
    VALUES (
      %(instance_name)s, %(connector_name)s, %(trading_pair)s, %(order_id)s, %(side)s, %(order_type)s, %(amount_base)s, %(price)s, %(state)s,
      %(created_ts_utc)s, %(updated_ts_utc)s, %(source_ts_utc)s, %(payload)s::jsonb, %(source_path)s, %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (instance_name, connector_name, trading_pair, order_id) DO UPDATE SET
      side = EXCLUDED.side,
      order_type = EXCLUDED.order_type,
      amount_base = EXCLUDED.amount_base,
      price = EXCLUDED.price,
      state = EXCLUDED.state,
      created_ts_utc = EXCLUDED.created_ts_utc,
      updated_ts_utc = EXCLUDED.updated_ts_utc,
      source_ts_utc = EXCLUDED.source_ts_utc,
      payload = EXCLUDED.payload,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    inserted = 0
    with conn.cursor() as cur:
        cur.execute(sql_delete)
        for order in orders.values():
            if not isinstance(order, dict):
                continue
            state_value = str(order.get("state", "")).strip().lower()
            if state_value in terminal_states:
                continue
            instance_name = str(order.get("instance_name", "")).strip()
            connector_name = str(order.get("connector_name", "")).strip()
            trading_pair = str(order.get("trading_pair", "")).strip()
            order_id = str(order.get("order_id", "")).strip()
            if not instance_name or not connector_name or not trading_pair or not order_id:
                continue
            row = {
                "instance_name": instance_name,
                "connector_name": connector_name,
                "trading_pair": trading_pair,
                "order_id": order_id,
                "side": str(order.get("side", "")).strip().lower() or None,
                "order_type": str(order.get("order_type", "")).strip().lower() or None,
                "amount_base": _safe_float(order.get("amount_base")),
                "price": _safe_float(order.get("price")),
                "state": state_value or "open",
                "created_ts_utc": _epoch_ms_to_ts_utc(order.get("created_ts_ms")),
                "updated_ts_utc": _epoch_ms_to_ts_utc(order.get("updated_ts_ms"), default=source_ts_utc),
                "source_ts_utc": source_ts_utc,
                "payload": json.dumps(order),
                "source_path": _source_abs(snapshot_path),
                "ingest_ts_utc": ingest_ts_utc,
                "schema_version": SCHEMA_VERSION,
            }
            cur.execute(sql_insert, row)
            inserted += 1
    return inserted


def _ingest_bot_position_current(conn: psycopg.Connection, reports_root: Path, ingest_ts_utc: str) -> int:
    sql = """
    INSERT INTO bot_position_current (
      instance_name, trading_pair, quantity, avg_entry_price, unrealized_pnl_quote, side, source_ts_utc,
      payload, source_path, ingest_ts_utc, schema_version
    )
    VALUES (
      %(instance_name)s, %(trading_pair)s, %(quantity)s, %(avg_entry_price)s, %(unrealized_pnl_quote)s, %(side)s, %(source_ts_utc)s,
      %(payload)s::jsonb, %(source_path)s, %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (instance_name, trading_pair) DO UPDATE SET
      quantity = EXCLUDED.quantity,
      avg_entry_price = EXCLUDED.avg_entry_price,
      unrealized_pnl_quote = EXCLUDED.unrealized_pnl_quote,
      side = EXCLUDED.side,
      source_ts_utc = EXCLUDED.source_ts_utc,
      payload = EXCLUDED.payload,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    inserted = 0
    desk_snapshot_root = reports_root / "desk_snapshot"
    with conn.cursor() as cur:
        for latest_path in sorted(desk_snapshot_root.glob("*/latest.json")):
            instance_name = str(latest_path.parent.name or "").strip()
            if not instance_name:
                continue
            payload = _read_json(latest_path)
            if not isinstance(payload, dict):
                continue
            positions_obj = payload.get("portfolio")
            if isinstance(positions_obj, dict):
                positions_obj = positions_obj.get("portfolio", positions_obj)
            positions = positions_obj.get("positions", {}) if isinstance(positions_obj, dict) else {}
            if not isinstance(positions, dict):
                continue
            source_ts_utc = _canonical_ts_utc(payload.get("source_ts"), ingest_ts_utc)
            seen_pairs: set[str] = set()
            for raw_key, raw_pos in positions.items():
                position = raw_pos if isinstance(raw_pos, dict) else {}
                trading_pair = str(position.get("trading_pair") or "").strip()
                if not trading_pair:
                    parts = str(raw_key or "").split(":")
                    if len(parts) >= 2:
                        trading_pair = str(parts[1]).strip()
                if not trading_pair:
                    continue
                seen_pairs.add(trading_pair)
                quantity = _safe_float(
                    position.get("quantity", position.get("amount", position.get("size")))
                )
                side = str(position.get("side") or "").strip().lower()
                if not side and quantity is not None:
                    side = "long" if quantity > 0 else ("short" if quantity < 0 else "flat")
                row = {
                    "instance_name": instance_name,
                    "trading_pair": trading_pair,
                    "quantity": quantity,
                    "avg_entry_price": _safe_float(
                        position.get("avg_entry_price", position.get("entry_price", position.get("avgPrice")))
                    ),
                    "unrealized_pnl_quote": _safe_float(
                        position.get("unrealized_pnl_quote", position.get("unrealized_pnl", position.get("pnl")))
                    ),
                    "side": side or None,
                    "source_ts_utc": source_ts_utc,
                    "payload": json.dumps(position, ensure_ascii=True),
                    "source_path": _source_abs(latest_path),
                    "ingest_ts_utc": ingest_ts_utc,
                    "schema_version": SCHEMA_VERSION,
                }
                cur.execute(sql, row)
                inserted += 1
    return inserted


def run_once(root: Path, data_root: Path, reports_root: Path, *, apply_schema: bool = True) -> Dict[str, object]:
    ingest_ts_utc = _utc_now()
    result = {
        "ts_utc": ingest_ts_utc,
        "status": "pass",
        "counts": {},
        "errors": [],
    }
    conn = _connect()
    try:
        if apply_schema:
            _apply_schema(conn, root)
            result["timescale"] = _apply_timescale(conn)
            conn.commit()
        else:
            result["timescale"] = {
                "enabled": _env_bool("OPS_DB_TIMESCALE_ENABLED", True),
                "required": _env_bool("OPS_DB_TIMESCALE_REQUIRED", False),
                "schema_apply_skipped": True,
            }
        counts = {}
        counts["bot_snapshot_minute"] = _ingest_minutes(conn, data_root, ingest_ts_utc)
        counts["bot_daily"] = _ingest_daily(conn, data_root, ingest_ts_utc)
        counts["fills"] = _ingest_fills(conn, data_root, ingest_ts_utc)
        counts["event_envelope_raw"] = _ingest_event_envelope_raw(conn, reports_root, ingest_ts_utc)
        counts["market_depth"] = _ingest_market_depth_layers(conn, reports_root, ingest_ts_utc)
        counts["market_quote"] = _ingest_market_quote_layers(conn, reports_root, ingest_ts_utc)
        counts["exchange_snapshot"] = _ingest_exchange_snapshot(conn, reports_root, ingest_ts_utc)
        counts["reconciliation_report"] = _ingest_single_report(
            conn,
            reports_root / "reconciliation" / "latest.json",
            "reconciliation_report",
            {"status": "status", "critical_count": "critical_count", "warning_count": "warning_count"},
            ingest_ts_utc,
        )
        counts["accounting_snapshot"] = _ingest_accounting_snapshots(conn, reports_root, ingest_ts_utc)
        counts["parity_report"] = _ingest_single_report(
            conn,
            reports_root / "parity" / "latest.json",
            "parity_report",
            {"status": "status", "failed_bots": "failed_bots", "checked_bots": "checked_bots"},
            ingest_ts_utc,
        )
        counts["portfolio_risk_report"] = _ingest_single_report(
            conn,
            reports_root / "portfolio_risk" / "latest.json",
            "portfolio_risk_report",
            {
                "status": "status",
                "critical_count": "critical_count",
                "warning_count": "warning_count",
                "portfolio_action": "portfolio_action",
            },
            ingest_ts_utc,
        )
        counts["promotion_gate_run"] = _ingest_promotion_gates(conn, reports_root, ingest_ts_utc)
        counts["paper_exchange_open_order_current"] = _ingest_paper_exchange_open_orders(conn, reports_root, ingest_ts_utc)
        counts["bot_position_current"] = _ingest_bot_position_current(conn, reports_root, ingest_ts_utc)
        conn.commit()
        result["counts"] = counts
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        result["status"] = "fail"
        result["errors"] = [str(exc)]
    finally:
        conn.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest CSV/JSON ops artifacts into Postgres.")
    parser.add_argument("--once", action="store_true", help="Run one ingestion cycle and exit.")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    data_root = Path(os.getenv("HB_DATA_ROOT", str(root / "data")))
    reports_root = Path(os.getenv("HB_REPORTS_ROOT", str(root / "reports")))
    interval_sec = int(os.getenv("OPS_DB_WRITER_INTERVAL_SEC", "300"))
    apply_schema_each_run = _env_bool("OPS_DB_APPLY_SCHEMA_EACH_RUN", False)
    reports_out = reports_root / "ops_db_writer"
    reports_out.mkdir(parents=True, exist_ok=True)

    def _persist(result: Dict[str, object]) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_file = reports_out / f"ops_db_writer_{stamp}.json"
        out_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        (reports_out / "latest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"[ops-db-writer] status={result.get('status')}")
        print(f"[ops-db-writer] counts={result.get('counts')}")
        print(f"[ops-db-writer] evidence={out_file}")

    if args.once:
        _persist(run_once(root, data_root, reports_root, apply_schema=True))
        return

    schema_ready = False
    while True:
        apply_schema_now = apply_schema_each_run or (not schema_ready)
        result = run_once(root, data_root, reports_root, apply_schema=apply_schema_now)
        if result.get("status") == "pass" and apply_schema_now:
            schema_ready = True
        _persist(result)
        time.sleep(max(30, interval_sec))


if __name__ == "__main__":
    main()
