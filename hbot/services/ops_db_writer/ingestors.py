from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    import psycopg
except Exception:  # pragma: no cover - optional in lightweight test environments.
    psycopg = None  # type: ignore[assignment]

from platform_lib.core.utils import (
    read_json as _read_json,
)
from platform_lib.core.utils import (
    safe_float as _safe_float,
)
from platform_lib.contracts.stream_names import MARKET_DEPTH_STREAM, MARKET_QUOTE_STREAM
from platform_lib.logging.log_namespace import iter_bot_log_files

from .parsers import (
    SCHEMA_VERSION,
    _EPOCH_TS_UTC,
    _canonical_ts_utc,
    _depth_metrics,
    _env_int,
    _epoch_ms_to_ts_utc,
    _fill_key,
    _floor_minute_utc,
    _iter_jsonl_rows,
    _next_minute_utc,
    _normalize_depth_levels,
    _parse_ts,
    _read_csv_rows,
    _safe_bool,
    _source_abs,
    _stream_entry_id_to_ts_utc,
)

logger = logging.getLogger(__name__)


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
        for minute_file in iter_bot_log_files(data_root, "minute.csv"):
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
        for daily_file in iter_bot_log_files(data_root, "daily.csv"):
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
        for fills_file in iter_bot_log_files(data_root, "fills.csv"):
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
                        f"{source_path}|{line_idx}|{stream}".encode()
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
                        f"{stream}|{stream_entry_id}|{ts_utc}".encode()
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


def _ingest_market_depth_layers(conn: psycopg.Connection, reports_root: Path, ingest_ts_utc: str) -> dict[str, object]:
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
    touched_rollup_keys: set[tuple[str, str, str, str, str]] = set()
    pair_state: dict[tuple[str, str, str, str], dict[str, int]] = defaultdict(
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
      event_count = EXCLUDED.event_count,
      avg_spread_bps = EXCLUDED.avg_spread_bps,
      avg_mid_price = EXCLUDED.avg_mid_price,
      avg_bid_depth_total = EXCLUDED.avg_bid_depth_total,
      avg_ask_depth_total = EXCLUDED.avg_ask_depth_total,
      avg_depth_imbalance = EXCLUDED.avg_depth_imbalance,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    select_rollup_rows_sql = """
    SELECT spread_bps, mid_price, bid_depth_total, ask_depth_total, depth_imbalance, source_path
    FROM market_depth_sampled
    WHERE ts_utc >= %(bucket_start_utc)s
      AND ts_utc < %(bucket_end_utc)s
      AND COALESCE(instance_name, '') = %(instance_name)s
      AND COALESCE(controller_id, '') = %(controller_id)s
      AND COALESCE(connector_name, '') = %(connector_name)s
      AND COALESCE(trading_pair, '') = %(trading_pair)s
    ORDER BY ts_utc ASC, stream_entry_id ASC
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
                        f"{source_path}|{line_idx}|{MARKET_DEPTH_STREAM}".encode()
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
                        f"{stream_entry_id}|{ts_utc}|market_depth_snapshot".encode()
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

                touched_rollup_keys.add(
                    (
                    _floor_minute_utc(ts_utc),
                    str(sampled_row.get("instance_name") or ""),
                    str(sampled_row.get("controller_id") or ""),
                    str(sampled_row.get("connector_name") or ""),
                    str(sampled_row.get("trading_pair") or ""),
                    )
                )

        for rollup_key in sorted(touched_rollup_keys):
            bucket_minute_utc, instance_name, controller_id, connector_name, trading_pair = rollup_key
            cur.execute(
                select_rollup_rows_sql,
                {
                    "bucket_start_utc": bucket_minute_utc,
                    "bucket_end_utc": _next_minute_utc(bucket_minute_utc),
                    "instance_name": instance_name,
                    "controller_id": controller_id,
                    "connector_name": connector_name,
                    "trading_pair": trading_pair,
                },
            )
            fetchall = getattr(cur, "fetchall", None)
            rollup_rows = list(fetchall() or []) if callable(fetchall) else []
            event_count = len(rollup_rows)
            if event_count <= 0:
                continue
            last_source_path = str(rollup_rows[-1][5] or latest_seen_path or checkpoint_source_path)
            cur.execute(
                upsert_rollup_sql,
                {
                    "bucket_minute_utc": bucket_minute_utc,
                    "instance_name": instance_name,
                    "controller_id": controller_id,
                    "connector_name": connector_name,
                    "trading_pair": trading_pair,
                    "event_count": event_count,
                    "avg_spread_bps": sum(float(row[0] or 0.0) for row in rollup_rows) / event_count,
                    "avg_mid_price": sum(float(row[1] or 0.0) for row in rollup_rows) / event_count,
                    "avg_bid_depth_total": sum(float(row[2] or 0.0) for row in rollup_rows) / event_count,
                    "avg_ask_depth_total": sum(float(row[3] or 0.0) for row in rollup_rows) / event_count,
                    "avg_depth_imbalance": sum(float(row[4] or 0.0) for row in rollup_rows) / event_count,
                    "source_path": last_source_path,
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
        "rollup_upserts": len(touched_rollup_keys),
        "depth_events_scanned": scanned_depth_events,
        "checkpoint_source_path": checkpoint_source_path,
        "checkpoint_source_line": checkpoint_source_line,
        "sample_every_n": sample_every_n,
        "sample_min_interval_ms": sample_min_interval_ms,
        "sample_levels": sample_levels,
    }


def _ingest_market_quote_layers(conn: psycopg.Connection, reports_root: Path, ingest_ts_utc: str) -> dict[str, object]:
    checkpoint_id = "event_store_market_quote_v1"
    raw_inserted = 0
    scanned_quote_events = 0
    checkpoint_source_path = ""
    checkpoint_source_line = 0
    event_store_root = reports_root / "event_store"
    touched_rollup_keys: set[tuple[str, str, str]] = set()

    def _prune_market_bar_v2(cur, touched_keys: list[tuple[str, str, str, int]]) -> int:
        max_bars = max(1000, _env_int("OPS_DB_MARKET_BAR_V2_RETENTION_MAX_BARS", 100_000))
        pruned = 0
        seen_keys = set()
        delete_sql = """
        WITH ranked AS (
            SELECT bucket_minute_utc
            FROM market_bar_v2
            WHERE connector_name = %(connector_name)s
              AND trading_pair = %(trading_pair)s
              AND bar_source = %(bar_source)s
              AND bar_interval_s = %(bar_interval_s)s
            ORDER BY bucket_minute_utc DESC
            OFFSET %(max_bars)s
        )
        DELETE FROM market_bar_v2
        WHERE connector_name = %(connector_name)s
          AND trading_pair = %(trading_pair)s
          AND bar_source = %(bar_source)s
          AND bar_interval_s = %(bar_interval_s)s
          AND bucket_minute_utc IN (SELECT bucket_minute_utc FROM ranked)
        """
        for key in touched_keys:
            if key in seen_keys:
                continue
            seen_keys.add(key)
            connector_name, trading_pair, bar_source, bar_interval_s = key
            cur.execute(
                delete_sql,
                {
                    "connector_name": connector_name,
                    "trading_pair": trading_pair,
                    "bar_source": bar_source,
                    "bar_interval_s": int(bar_interval_s),
                    "max_bars": int(max_bars),
                },
            )
            pruned += int(getattr(cur, "rowcount", 0) or 0)
        return pruned

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
      event_count = EXCLUDED.event_count,
      first_ts_utc = EXCLUDED.first_ts_utc,
      last_ts_utc = EXCLUDED.last_ts_utc,
      open_price = EXCLUDED.open_price,
      high_price = EXCLUDED.high_price,
      low_price = EXCLUDED.low_price,
      close_price = EXCLUDED.close_price,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    upsert_market_bar_v2_sql = """
    INSERT INTO market_bar_v2 (
      bucket_minute_utc, connector_name, trading_pair, bar_source, bar_interval_s, open_price, high_price, low_price,
      close_price, volume_base, volume_quote, event_count, first_ts_utc, last_ts_utc, ingest_ts_utc, schema_version, quality_flags
    )
    VALUES (
      %(bucket_minute_utc)s, %(connector_name)s, %(trading_pair)s, %(bar_source)s, %(bar_interval_s)s, %(open_price)s,
      %(high_price)s, %(low_price)s, %(close_price)s, %(volume_base)s, %(volume_quote)s, %(event_count)s, %(first_ts_utc)s,
      %(last_ts_utc)s, %(ingest_ts_utc)s, %(schema_version)s, %(quality_flags)s::jsonb
    )
    ON CONFLICT (bucket_minute_utc, connector_name, trading_pair, bar_source, bar_interval_s) DO UPDATE SET
      event_count = EXCLUDED.event_count,
      first_ts_utc = EXCLUDED.first_ts_utc,
      last_ts_utc = EXCLUDED.last_ts_utc,
      open_price = EXCLUDED.open_price,
      high_price = EXCLUDED.high_price,
      low_price = EXCLUDED.low_price,
      close_price = EXCLUDED.close_price,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version,
      quality_flags = EXCLUDED.quality_flags
    """
    select_rollup_rows_sql = """
    SELECT ts_utc, mid_price, source_path
    FROM market_quote_raw
    WHERE ts_utc >= %(bucket_start_utc)s
      AND ts_utc < %(bucket_end_utc)s
      AND connector_name = %(connector_name)s
      AND trading_pair = %(trading_pair)s
    ORDER BY ts_utc ASC, stream_entry_id ASC
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
                        f"{source_path}|{line_idx}|{MARKET_QUOTE_STREAM}".encode()
                    ).hexdigest()
                ts_hint = _stream_entry_id_to_ts_utc(stream_entry_id) or _canonical_ts_utc(row.get("ingest_ts_utc"), ingest_ts_utc)
                ts_utc = _canonical_ts_utc(row.get("ts_utc"), ts_hint)
                connector_name = str(row.get("connector_name") or payload_obj.get("connector_name") or "").strip()
                trading_pair = str(row.get("trading_pair") or payload_obj.get("trading_pair") or "").strip()
                event_id = str(row.get("event_id") or payload_obj.get("event_id") or "").strip()
                if not event_id:
                    event_id = hashlib.sha256(f"{stream_entry_id}|{ts_utc}|market_quote".encode()).hexdigest()
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

                touched_rollup_keys.add((_floor_minute_utc(ts_utc), connector_name, trading_pair))

        touched_market_bar_keys: list[tuple[str, str, str, int]] = []
        for bucket_minute_utc, connector_name, trading_pair in sorted(touched_rollup_keys):
            cur.execute(
                select_rollup_rows_sql,
                {
                    "bucket_start_utc": bucket_minute_utc,
                    "bucket_end_utc": _next_minute_utc(bucket_minute_utc),
                    "connector_name": connector_name,
                    "trading_pair": trading_pair,
                },
            )
            fetchall = getattr(cur, "fetchall", None)
            rollup_rows = list(fetchall() or []) if callable(fetchall) else []
            if not rollup_rows:
                continue
            event_count = len(rollup_rows)
            first_ts_utc = str(rollup_rows[0][0] or bucket_minute_utc)
            last_ts_utc = str(rollup_rows[-1][0] or first_ts_utc)
            open_price = float(rollup_rows[0][1] or 0.0)
            close_price = float(rollup_rows[-1][1] or open_price)
            high_price = max(float(row[1] or 0.0) for row in rollup_rows)
            low_price = min(float(row[1] or 0.0) for row in rollup_rows)
            source_path = str(rollup_rows[-1][2] or latest_seen_path or checkpoint_source_path)
            cur.execute(
                upsert_bar_sql,
                {
                    "bucket_minute_utc": bucket_minute_utc,
                    "connector_name": connector_name,
                    "trading_pair": trading_pair,
                    "event_count": event_count,
                    "first_ts_utc": first_ts_utc,
                    "last_ts_utc": last_ts_utc,
                    "open_price": open_price,
                    "high_price": high_price,
                    "low_price": low_price,
                    "close_price": close_price,
                    "source_path": source_path,
                    "ingest_ts_utc": ingest_ts_utc,
                    "schema_version": SCHEMA_VERSION,
                },
            )
            cur.execute(
                upsert_market_bar_v2_sql,
                {
                    "bucket_minute_utc": bucket_minute_utc,
                    "connector_name": connector_name,
                    "trading_pair": trading_pair,
                    "bar_source": "quote_mid",
                    "bar_interval_s": 60,
                    "open_price": open_price,
                    "high_price": high_price,
                    "low_price": low_price,
                    "close_price": close_price,
                    "volume_base": None,
                    "volume_quote": None,
                    "event_count": event_count,
                    "first_ts_utc": first_ts_utc,
                    "last_ts_utc": last_ts_utc,
                    "ingest_ts_utc": ingest_ts_utc,
                    "schema_version": max(2, SCHEMA_VERSION),
                    "quality_flags": json.dumps({}, ensure_ascii=True),
                },
            )
            touched_market_bar_keys.append((connector_name, trading_pair, "quote_mid", 60))

        pruned_market_bar_v2 = _prune_market_bar_v2(cur, touched_market_bar_keys)

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
        "bar_upserts": len(touched_rollup_keys),
        "market_bar_v2_upserts": len(touched_rollup_keys),
        "market_bar_v2_pruned": pruned_market_bar_v2,
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
    mapped_fields: dict[str, str],
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
