from __future__ import annotations

import csv
import json
import logging
import os
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import psycopg
except Exception:
    psycopg = None  # type: ignore[assignment]

try:
    import ccxt  # type: ignore
except Exception:
    ccxt = None  # type: ignore[assignment]

from platform_lib.logging.log_namespace import list_instance_log_files
from platform_lib.market_data.market_history_provider_impl import MarketHistoryProviderImpl, market_bars_to_candles
from platform_lib.market_data.market_history_types import MarketBar, MarketBarKey
from services.realtime_ui_api._helpers import (
    RealtimeApiConfig,
    _account_summary_template,
    _build_quote_gate_summary,
    _build_runtime_open_order_placeholders,
    _candle_dicts_to_market_bars,
    _ccxt_exchange_id,
    _ccxt_symbol,
    _ccxt_timeframe,
    _day_bounds_utc,
    _normalize_fill_activity_row,
    _normalize_pair,
    _now_ms,
    _read_paper_exchange_active_orders,
    _resolve_realized_pnl,
    _summarize_fill_activity,
    _to_bool,
    _to_epoch_ms,
    _to_float,
)

logger = logging.getLogger(__name__)


class OpsDbReadModel:
    def __init__(self, cfg: RealtimeApiConfig):
        self._cfg = cfg
        self._enabled = bool(cfg.db_enabled and psycopg is not None)
        self._last_health_check_ms = 0
        self._last_health_ok = False
        self._rest_candle_cache: dict[tuple[str, str, int, int], tuple[int, list[dict[str, Any]]]] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _connect(self):
        if not self._enabled:
            return None
        host = os.getenv("OPS_DB_HOST", "postgres")
        port = int(os.getenv("OPS_DB_PORT", "5432"))
        dbname = os.getenv("OPS_DB_NAME", "hbot_ops")
        user = os.getenv("OPS_DB_USER", "hbot")
        password = os.getenv("OPS_DB_PASSWORD", "hbot_dev_password")
        statement_timeout_ms = max(200, int(self._cfg.db_statement_timeout_ms))
        lock_timeout_ms = max(100, int(self._cfg.db_lock_timeout_ms))
        options = f"-c statement_timeout={statement_timeout_ms} -c lock_timeout={lock_timeout_ms}"
        return psycopg.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            connect_timeout=3,
            options=options,
        )

    def available(self) -> bool:
        if not self._enabled:
            return False
        now = _now_ms()
        if now - self._last_health_check_ms <= 5_000:
            return self._last_health_ok
        ok = False
        try:
            conn = self._connect()
            if conn is not None:
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                        ok = bool(cur.fetchone())
                finally:
                    conn.close()
        except Exception:
            ok = False
        self._last_health_check_ms = now
        self._last_health_ok = ok
        return ok

    def _query(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if not self._enabled:
            return []
        try:
            conn = self._connect()
            if conn is None:
                return []
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall()
                    cols = [desc[0] for desc in cur.description or []]
                out: list[dict[str, Any]] = []
                for row in rows:
                    if isinstance(row, dict):
                        out.append(row)
                    elif isinstance(row, tuple):
                        out.append({cols[idx]: row[idx] for idx in range(min(len(cols), len(row)))})
                return out
            finally:
                conn.close()
        except Exception:
            return []

    def _pair_candidates(self, trading_pair: str) -> list[str]:
        raw = str(trading_pair or "").strip().upper()
        if not raw:
            return []
        norm = _normalize_pair(raw)
        out = {raw, raw.replace("/", "-"), raw.replace("_", "-")}
        if len(norm) >= 6:
            out.add(norm)
            if "-" not in raw and "/" not in raw and "_" not in raw:
                out.add(f"{norm[:-4]}-{norm[-4:]}")
        return sorted(item for item in out if item)

    def _variant_hint(self, controller_id: str) -> str:
        raw = str(controller_id or "").strip()
        if not raw:
            return ""
        parts = [p for p in raw.split("_") if p]
        tail = parts[-1].lower() if parts else ""
        if len(tail) == 1 and tail.isalpha():
            return tail
        return ""

    def get_candles(self, connector_name: str, trading_pair: str, timeframe_s: int, limit: int) -> list[dict[str, Any]]:
        bars = self.get_market_bars(
            MarketBarKey(
                connector_name=str(connector_name or "").strip(),
                trading_pair=str(trading_pair or "").strip(),
                bar_source="quote_mid",
            ),
            bar_interval_s=timeframe_s,
            limit=limit,
        )
        if bars:
            return market_bars_to_candles(bars)
        return self._get_legacy_quote_candles(connector_name, trading_pair, timeframe_s, limit)

    def _get_legacy_quote_candles(
        self,
        connector_name: str,
        trading_pair: str,
        timeframe_s: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not self.available():
            return []
        limit = max(1, int(limit))
        pair_candidates = self._pair_candidates(trading_pair)
        rows = self._query(
            """
            SELECT EXTRACT(EPOCH FROM bucket_minute_utc) * 1000.0 AS bucket_ms,
                   open_price,
                   high_price,
                   low_price,
                   close_price
            FROM market_quote_bar_minute
            WHERE (%(connector_name)s = '' OR connector_name = %(connector_name)s)
              AND (%(pair_count)s = 0 OR trading_pair = ANY(%(pairs)s))
              AND bucket_minute_utc >= NOW() - (%(lookback_hours)s::text || ' hours')::interval
            ORDER BY bucket_minute_utc DESC
            LIMIT %(limit)s
            """,
            {
                "connector_name": str(connector_name or "").strip(),
                "pairs": pair_candidates,
                "pair_count": len(pair_candidates),
                "lookback_hours": max(1, int(self._cfg.db_lookback_hours)),
                "limit": limit,
            },
        )
        out: list[dict[str, Any]] = []
        for row in reversed(rows):
            bucket_ms = _to_epoch_ms(row.get("bucket_ms"))
            open_price = _to_float(row.get("open_price"))
            high_price = _to_float(row.get("high_price"))
            low_price = _to_float(row.get("low_price"))
            close_price = _to_float(row.get("close_price"))
            if None in {bucket_ms, open_price, high_price, low_price, close_price}:
                continue
            out.append(
                {
                    "bucket_ms": int(bucket_ms),
                    "open": float(open_price),
                    "high": float(high_price),
                    "low": float(low_price),
                    "close": float(close_price),
                }
            )
        return out[-limit:]

    def get_market_bars(
        self,
        key: MarketBarKey,
        bar_interval_s: int,
        limit: int,
        end_time_ms: int | None = None,
        require_closed: bool = True,
    ) -> list[MarketBar]:
        if not self.available():
            return []
        limit = max(1, int(limit))
        pair_candidates = self._pair_candidates(key.trading_pair)
        end_ts_utc = (
            datetime.fromtimestamp(int(end_time_ms) / 1000.0, tz=UTC).isoformat()
            if end_time_ms
            else None
        )
        rows = self._query(
            """
            SELECT EXTRACT(EPOCH FROM bucket_minute_utc) * 1000.0 AS bucket_ms,
                   open_price,
                   high_price,
                   low_price,
                   close_price,
                   bar_source
            FROM market_bar_v2
            WHERE (%(connector_name)s = '' OR connector_name = %(connector_name)s)
              AND (%(pair_count)s = 0 OR trading_pair = ANY(%(pairs)s))
              AND bar_source = %(bar_source)s
              AND bar_interval_s = 60
              AND (%(end_ts_utc)s IS NULL OR bucket_minute_utc <= %(end_ts_utc)s::timestamptz)
              AND bucket_minute_utc >= NOW() - (%(lookback_hours)s::text || ' hours')::interval
            ORDER BY bucket_minute_utc DESC
            LIMIT %(limit)s
            """,
            {
                "connector_name": str(key.connector_name or "").strip(),
                "pairs": pair_candidates,
                "pair_count": len(pair_candidates),
                "bar_source": str(key.bar_source or "quote_mid"),
                "end_ts_utc": end_ts_utc,
                "lookback_hours": max(1, int(self._cfg.db_lookback_hours)),
                "limit": max(limit, int(limit * max(1, int(bar_interval_s) // 60))),
            },
        )
        if not rows and str(key.bar_source or "quote_mid") == "quote_mid":
            return _candle_dicts_to_market_bars(
                self._get_legacy_quote_candles(str(key.connector_name or ""), str(key.trading_pair or ""), bar_interval_s, limit),
                bar_interval_s=max(60, int(bar_interval_s)),
                bar_source="quote_mid",
            )
        bars = _candle_dicts_to_market_bars(
            [
                {
                    "bucket_ms": row.get("bucket_ms"),
                    "open": row.get("open_price"),
                    "high": row.get("high_price"),
                    "low": row.get("low_price"),
                    "close": row.get("close_price"),
                }
                for row in reversed(rows)
            ],
            bar_interval_s=60,
            bar_source=str(key.bar_source or "quote_mid"),
        )
        if int(bar_interval_s) <= 60:
            return bars[-limit:]
        provider = MarketHistoryProviderImpl(now_ms_reader=_now_ms)
        rolled = provider._rollup(bars, int(bar_interval_s))
        if require_closed:
            rolled = [bar for bar in rolled if bar.is_closed]
        return rolled[-limit:]

    def get_position(self, instance_name: str, trading_pair: str) -> dict[str, Any]:
        if not self.available() or not instance_name:
            return {}
        pair_candidates = self._pair_candidates(trading_pair)
        rows = self._query(
            """
            SELECT trading_pair, quantity, avg_entry_price, unrealized_pnl_quote, side, source_ts_utc
            FROM bot_position_current
            WHERE instance_name = %(instance_name)s
              AND (%(pair_count)s = 0 OR trading_pair = ANY(%(pairs)s))
            ORDER BY source_ts_utc DESC
            LIMIT 1
            """,
            {
                "instance_name": instance_name,
                "pairs": pair_candidates,
                "pair_count": len(pair_candidates),
            },
        )
        if not rows:
            return {}
        row = rows[0]
        return {
            "trading_pair": str(row.get("trading_pair", "")),
            "quantity": _to_float(row.get("quantity")) or 0.0,
            "avg_entry_price": _to_float(row.get("avg_entry_price")) or 0.0,
            "unrealized_pnl": _to_float(row.get("unrealized_pnl_quote")) or 0.0,
            "side": str(row.get("side", "")),
            "source_ts_ms": _to_epoch_ms(row.get("source_ts_utc")) or 0,
        }

    def get_rest_backfill_candles(
        self,
        connector_name: str,
        trading_pair: str,
        timeframe_s: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        exchange_id = _ccxt_exchange_id(connector_name)
        if ccxt is None or not exchange_id:
            return []
        bounded_limit = max(5, min(int(limit), 500))
        cache_key = (exchange_id, _normalize_pair(trading_pair), int(timeframe_s), bounded_limit)
        now_ms = _now_ms()
        cached = self._rest_candle_cache.get(cache_key)
        if cached is not None and (now_ms - int(cached[0])) <= 30_000:
            return list(cached[1])
        try:
            exchange_cls = getattr(ccxt, exchange_id)
            exchange = exchange_cls({"enableRateLimit": True})
            if "testnet" in str(connector_name or "").lower() and hasattr(exchange, "set_sandbox_mode"):
                exchange.set_sandbox_mode(True)
            rows = exchange.fetch_ohlcv(
                _ccxt_symbol(trading_pair),
                timeframe=_ccxt_timeframe(timeframe_s),
                limit=bounded_limit,
            )
        except Exception:
            return []
        candles: list[dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, (list, tuple)) or len(row) < 5:
                continue
            bucket_ms = _to_epoch_ms(row[0])
            open_price = _to_float(row[1])
            high_price = _to_float(row[2])
            low_price = _to_float(row[3])
            close_price = _to_float(row[4])
            if None in {bucket_ms, open_price, high_price, low_price, close_price}:
                continue
            if any(v <= 0 for v in (open_price, high_price, low_price, close_price)):
                continue
            candles.append(
                {
                    "bucket_ms": int(bucket_ms),
                    "open": float(open_price),
                    "high": float(high_price),
                    "low": float(low_price),
                    "close": float(close_price),
                }
            )
        self._rest_candle_cache[cache_key] = (now_ms, list(candles))
        return candles

    def get_fills(self, instance_name: str, trading_pair: str, limit: int = 120) -> list[dict[str, Any]]:
        if not self.available() or not instance_name:
            return []
        limit = max(1, int(limit))
        pair_candidates = self._pair_candidates(trading_pair)
        rows = self._query(
            """
            SELECT ts_utc, side, price, amount_base, realized_pnl_quote, order_id, is_maker,
                   notional_quote, fee_quote
            FROM fills
            WHERE bot = %(instance_name)s
              AND (%(pair_count)s = 0 OR trading_pair = ANY(%(pairs)s))
              AND ts_utc >= NOW() - (%(lookback_hours)s::text || ' hours')::interval
            ORDER BY ts_utc DESC
            LIMIT %(limit)s
            """,
            {
                "instance_name": instance_name,
                "pairs": pair_candidates,
                "pair_count": len(pair_candidates),
                "lookback_hours": max(1, int(self._cfg.db_lookback_hours)),
                "limit": limit,
            },
        )
        out: list[dict[str, Any]] = []
        for row in reversed(rows):
            ts_raw = row.get("ts_utc")
            ts_ms = _to_epoch_ms(ts_raw)
            price = _to_float(row.get("price")) or 0.0
            amount_base = _to_float(row.get("amount_base")) or 0.0
            out.append(
                {
                    "ts": str(ts_raw),
                    "timestamp_ms": ts_ms or 0,
                    "side": str(row.get("side", "")).upper(),
                    "price": price,
                    "amount_base": amount_base,
                    "notional_quote": _to_float(row.get("notional_quote")) or (price * amount_base),
                    "fee_quote": _to_float(row.get("fee_quote")) or 0.0,
                    "realized_pnl_quote": _to_float(row.get("realized_pnl_quote")) or 0.0,
                    "order_id": str(row.get("order_id", "")),
                    "is_maker": bool(row.get("is_maker")),
                }
            )
        return out

    def get_fills_for_day(self, instance_name: str, trading_pair: str, day_key: str, limit: int = 4000) -> list[dict[str, Any]]:
        if not self.available() or not instance_name:
            return []
        day_key, start_ms, end_ms = _day_bounds_utc(day_key)
        pair_candidates = self._pair_candidates(trading_pair)
        rows = self._query(
            """
            SELECT ts_utc, side, price, amount_base, realized_pnl_quote, order_id, is_maker,
                   notional_quote, fee_quote
            FROM fills
            WHERE bot = %(instance_name)s
              AND (%(pair_count)s = 0 OR trading_pair = ANY(%(pairs)s))
              AND ts_utc >= %(start_ts)s::timestamptz
              AND ts_utc < %(end_ts)s::timestamptz
            ORDER BY ts_utc ASC
            LIMIT %(limit)s
            """,
            {
                "instance_name": instance_name,
                "pairs": pair_candidates,
                "pair_count": len(pair_candidates),
                "start_ts": datetime.fromtimestamp(start_ms / 1000, tz=UTC).isoformat(),
                "end_ts": datetime.fromtimestamp(end_ms / 1000, tz=UTC).isoformat(),
                "limit": max(1, int(limit)),
            },
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            ts_ms = _to_epoch_ms(row.get("ts_utc"))
            if ts_ms is None:
                continue
            price = _to_float(row.get("price"))
            amount_base = _to_float(row.get("amount_base"))
            if price is None:
                continue
            safe_amount = amount_base if amount_base is not None else 0.0
            out.append(
                {
                    "ts": datetime.fromtimestamp(ts_ms / 1000, tz=UTC).isoformat(),
                    "timestamp_ms": ts_ms,
                    "side": str(row.get("side", "")).upper(),
                    "price": price,
                    "amount_base": safe_amount,
                    "notional_quote": _to_float(row.get("notional_quote")) or (price * safe_amount),
                    "fee_quote": _to_float(row.get("fee_quote")) or 0.0,
                    "realized_pnl_quote": _to_float(row.get("realized_pnl_quote")) or 0.0,
                    "order_id": str(row.get("order_id", "")),
                    "is_maker": bool(row.get("is_maker")),
                }
            )
        return out

    def get_fills_range(
        self,
        instance_name: str,
        trading_pair: str,
        start_day: str = "",
        end_day: str = "",
        limit: int = 10000,
    ) -> list[dict[str, Any]]:
        if not self.available() or not instance_name:
            return []
        pair_candidates = self._pair_candidates(trading_pair)
        start_ts = None
        end_ts = None
        if str(start_day or "").strip():
            _, start_ms, _ = _day_bounds_utc(start_day)
            start_ts = datetime.fromtimestamp(start_ms / 1000, tz=UTC).isoformat()
        if str(end_day or "").strip():
            _, _, end_ms = _day_bounds_utc(end_day)
            end_ts = datetime.fromtimestamp(end_ms / 1000, tz=UTC).isoformat()
        rows = self._query(
            """
            SELECT ts_utc, side, price, amount_base, realized_pnl_quote, order_id, is_maker,
                   notional_quote, fee_quote
            FROM fills
            WHERE bot = %(instance_name)s
              AND (%(pair_count)s = 0 OR trading_pair = ANY(%(pairs)s))
              AND (%(start_ts)s IS NULL OR ts_utc >= %(start_ts)s::timestamptz)
              AND (%(end_ts)s IS NULL OR ts_utc < %(end_ts)s::timestamptz)
            ORDER BY ts_utc ASC
            LIMIT %(limit)s
            """,
            {
                "instance_name": instance_name,
                "pairs": pair_candidates,
                "pair_count": len(pair_candidates),
                "start_ts": start_ts,
                "end_ts": end_ts,
                "limit": max(1, int(limit)),
            },
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            ts_ms = _to_epoch_ms(row.get("ts_utc"))
            if ts_ms is None:
                continue
            price = _to_float(row.get("price"))
            amount_base = _to_float(row.get("amount_base"))
            if price is None:
                continue
            safe_amount = amount_base if amount_base is not None else 0.0
            out.append(
                {
                    "ts": datetime.fromtimestamp(ts_ms / 1000, tz=UTC).isoformat(),
                    "timestamp_ms": ts_ms,
                    "side": str(row.get("side", "")).upper(),
                    "price": price,
                    "amount_base": safe_amount,
                    "notional_quote": _to_float(row.get("notional_quote")) or (price * safe_amount),
                    "fee_quote": _to_float(row.get("fee_quote")) or 0.0,
                    "realized_pnl_quote": _to_float(row.get("realized_pnl_quote")) or 0.0,
                    "order_id": str(row.get("order_id", "")),
                    "is_maker": bool(row.get("is_maker")),
                }
            )
        return out

    def get_fill_count(self, instance_name: str, trading_pair: str) -> int:
        if not self.available() or not instance_name:
            return 0
        pair_candidates = self._pair_candidates(trading_pair)
        rows = self._query(
            """
            SELECT COUNT(*) AS fill_count
            FROM fills
            WHERE bot = %(instance_name)s
              AND (%(pair_count)s = 0 OR trading_pair = ANY(%(pairs)s))
              AND ts_utc >= NOW() - (%(lookback_hours)s::text || ' hours')::interval
            """,
            {
                "instance_name": instance_name,
                "pairs": pair_candidates,
                "pair_count": len(pair_candidates),
                "lookback_hours": max(1, int(self._cfg.db_lookback_hours)),
            },
        )
        if not rows:
            return 0
        try:
            return max(0, int(rows[0].get("fill_count") or 0))
        except Exception:
            return 0

    def get_fill_activity(self, instance_name: str, trading_pair: str) -> dict[str, Any]:
        if not self.available() or not instance_name:
            return {**_summarize_fill_activity([], fills_total=0), "realized_pnl_total_quote": 0.0}
        pair_candidates = self._pair_candidates(trading_pair)
        rows = self._query(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes'
                ) AS m15_fill_count,
                COUNT(*) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes' AND LOWER(side) = 'buy'
                ) AS m15_buy_count,
                COUNT(*) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes' AND LOWER(side) = 'sell'
                ) AS m15_sell_count,
                COUNT(*) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes' AND COALESCE(is_maker, FALSE)
                ) AS m15_maker_count,
                COALESCE(SUM(ABS(COALESCE(amount_base, 0))) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes'
                ), 0) AS m15_volume_base,
                COALESCE(SUM(ABS(COALESCE(amount_base, 0) * COALESCE(price, 0))) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes'
                ), 0) AS m15_notional_quote,
                COALESCE(SUM(COALESCE(realized_pnl_quote, 0)) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes'
                ), 0) AS m15_realized_pnl_quote,
                COALESCE(AVG(ABS(COALESCE(amount_base, 0))) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes'
                ), 0) AS m15_avg_fill_size,
                COALESCE(AVG(COALESCE(price, 0)) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes'
                ), 0) AS m15_avg_fill_price,
                COALESCE(SUM(COALESCE(fee_quote, 0)) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes'
                ), 0) AS m15_fees_quote,
                COUNT(*) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour'
                ) AS h1_fill_count,
                COUNT(*) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour' AND LOWER(side) = 'buy'
                ) AS h1_buy_count,
                COUNT(*) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour' AND LOWER(side) = 'sell'
                ) AS h1_sell_count,
                COUNT(*) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour' AND COALESCE(is_maker, FALSE)
                ) AS h1_maker_count,
                COALESCE(SUM(ABS(COALESCE(amount_base, 0))) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour'
                ), 0) AS h1_volume_base,
                COALESCE(SUM(ABS(COALESCE(amount_base, 0) * COALESCE(price, 0))) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour'
                ), 0) AS h1_notional_quote,
                COALESCE(SUM(COALESCE(realized_pnl_quote, 0)) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour'
                ), 0) AS h1_realized_pnl_quote,
                COALESCE(AVG(ABS(COALESCE(amount_base, 0))) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour'
                ), 0) AS h1_avg_fill_size,
                COALESCE(AVG(COALESCE(price, 0)) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour'
                ), 0) AS h1_avg_fill_price,
                COALESCE(SUM(COALESCE(fee_quote, 0)) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour'
                ), 0) AS h1_fees_quote,
                COUNT(*) AS fills_total,
                COALESCE(SUM(COALESCE(realized_pnl_quote, 0)), 0) AS realized_pnl_total_quote,
                EXTRACT(EPOCH FROM MAX(ts_utc)) * 1000.0 AS latest_fill_ts_ms
            FROM fills
            WHERE bot = %(instance_name)s
              AND (%(pair_count)s = 0 OR trading_pair = ANY(%(pairs)s))
              AND ts_utc >= NOW() - ((%(lookback_hours)s::int + 1)::text || ' hours')::interval
            """,
            {
                "instance_name": instance_name,
                "pairs": pair_candidates,
                "pair_count": len(pair_candidates),
                "lookback_hours": max(1, int(self._cfg.db_lookback_hours)),
            },
        )
        if not rows:
            return {**_summarize_fill_activity([], fills_total=0), "realized_pnl_total_quote": 0.0}
        row = rows[0]
        return {
            "fills_total": max(0, int(row.get("fills_total") or 0)),
            "latest_fill_ts_ms": int(_to_epoch_ms(row.get("latest_fill_ts_ms")) or 0),
            "realized_pnl_total_quote": float(_to_float(row.get("realized_pnl_total_quote")) or 0.0),
            "window_15m": _normalize_fill_activity_row(row, "m15"),
            "window_1h": _normalize_fill_activity_row(row, "h1"),
        }

    def get_open_orders(self, instance_name: str, trading_pair: str, limit: int = 40) -> list[dict[str, Any]]:
        if not self.available() or not instance_name:
            return []
        limit = max(1, int(limit))
        pair_candidates = self._pair_candidates(trading_pair)
        rows = self._query(
            """
            SELECT order_id, side, order_type, amount_base, price, state, updated_ts_utc
            FROM paper_exchange_open_order_current
            WHERE instance_name = %(instance_name)s
              AND (%(pair_count)s = 0 OR trading_pair = ANY(%(pairs)s))
            ORDER BY updated_ts_utc DESC
            LIMIT %(limit)s
            """,
            {
                "instance_name": instance_name,
                "pairs": pair_candidates,
                "pair_count": len(pair_candidates),
                "limit": limit,
            },
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "order_id": str(row.get("order_id", "")),
                    "side": str(row.get("side", "")).lower(),
                    "order_type": str(row.get("order_type", "")).lower(),
                    "price": _to_float(row.get("price")) or 0.0,
                    "amount": _to_float(row.get("amount_base")) or 0.0,
                    "quantity": _to_float(row.get("amount_base")) or 0.0,
                    "state": str(row.get("state", "")).lower() or "open",
                    "updated_ts_ms": _to_epoch_ms(row.get("updated_ts_utc")) or 0,
                    "is_estimated": False,
                }
            )
        return out


class DeskSnapshotFallback:
    def __init__(self, reports_root: Path, data_root: Path | None = None):
        self._reports_root = reports_root
        self._data_root = (data_root or Path(os.getenv("HB_DATA_ROOT", "/workspace/hbot/data"))).resolve()
        self._json_cache: dict[str, tuple[int, dict[str, Any]]] = {}
        self._available_instances_cache: tuple[int, list[str]] = (0, [])
        self._order_owner_cache: tuple[int, dict[str, str]] = (0, {})
        self._csv_query_cache: dict[tuple[str, str, tuple[Any, ...]], tuple[int, int, int, Any]] = {}

    def _csv_query_signature(self, path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
            return int(stat.st_mtime_ns), int(stat.st_size)
        except OSError:
            return None

    def _prune_csv_query_cache(self) -> None:
        max_entries = 128
        if len(self._csv_query_cache) <= max_entries:
            return
        oldest_keys = sorted(self._csv_query_cache.items(), key=lambda item: item[1][0])[: len(self._csv_query_cache) - max_entries]
        for key, _value in oldest_keys:
            self._csv_query_cache.pop(key, None)

    def _cached_csv_query(
        self,
        namespace: str,
        path: Path,
        query_key: tuple[Any, ...],
        loader: Any,
        *,
        ttl_ms: int = 30_000,
    ) -> Any:
        signature = self._csv_query_signature(path)
        if signature is None:
            return loader()
        cache_key = (namespace, str(path.resolve()), tuple(query_key))
        now_ms = _now_ms()
        cached = self._csv_query_cache.get(cache_key)
        if cached is not None:
            cached_ts_ms, cached_mtime_ns, cached_size, cached_value = cached
            if (
                (now_ms - int(cached_ts_ms)) <= max(1, int(ttl_ms))
                and int(cached_mtime_ns) == int(signature[0])
                and int(cached_size) == int(signature[1])
            ):
                return cached_value
        value = loader()
        self._csv_query_cache[cache_key] = (now_ms, int(signature[0]), int(signature[1]), value)
        self._prune_csv_query_cache()
        return value

    def _snapshot_path(self, instance_name: str) -> Path:
        return self._reports_root / "desk_snapshot" / instance_name / "latest.json"

    def _read_json(self, path: Path) -> dict[str, Any]:
        cache_key = str(path.resolve())
        now_ms = _now_ms()
        cached_ts_ms, cached_payload = self._json_cache.get(cache_key, (0, {}))
        if cached_ts_ms > 0 and (now_ms - cached_ts_ms) <= 60_000:
            return cached_payload
        if not path.exists():
            self._json_cache[cache_key] = (now_ms, {})
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self._json_cache[cache_key] = (now_ms, {})
            return {}
        normalized = payload if isinstance(payload, dict) else {}
        self._json_cache[cache_key] = (now_ms, normalized)
        return normalized

    def get_snapshot(self, instance_name: str) -> dict[str, Any]:
        return self._read_json(self._snapshot_path(instance_name))

    def _instance_manifest_path(self, instance_name: str) -> Path:
        return self._data_root / instance_name / "conf" / "instance_meta.json"

    def instance_metadata(self, instance_name: str) -> dict[str, Any]:
        if not instance_name:
            return {}
        payload = self._read_json(self._instance_manifest_path(instance_name))
        return payload if isinstance(payload, dict) else {}

    def available_instances(self) -> list[str]:
        now_ms = _now_ms()
        cached_ts_ms, cached_instances = self._available_instances_cache
        if cached_ts_ms > 0 and (now_ms - cached_ts_ms) <= 60_000:
            return list(cached_instances)
        instances: set[str] = set()
        desk_snapshot_root = self._reports_root / "desk_snapshot"
        if desk_snapshot_root.exists():
            try:
                for entry in desk_snapshot_root.iterdir():
                    if not entry.is_dir() or entry.name.startswith("."):
                        continue
                    if (entry / "latest.json").exists():
                        instances.add(entry.name)
            except Exception:
                pass
        if self._data_root.exists():
            try:
                for entry in self._data_root.iterdir():
                    if not entry.is_dir() or entry.name.startswith("."):
                        continue
                    manifest = self.instance_metadata(entry.name)
                    explicit_visible = bool(
                        manifest
                        and (
                            manifest.get("visible_in_supervision") is True
                            or manifest.get("enabled") is True
                            or manifest.get("discover") is True
                        )
                    )
                    marker_visible = (entry / ".supervision_enabled").exists()
                    if explicit_visible or marker_visible:
                        instances.add(entry.name)
                        continue
                    if any((entry / child).exists() for child in ("conf", "logs", "data", "scripts")):
                        instances.add(entry.name)
            except Exception:
                pass
        resolved = sorted(instances, key=lambda value: value.lower())
        self._available_instances_cache = (now_ms, resolved)
        return list(resolved)

    def weekly_strategy_report(self, instance_name: str) -> dict[str, Any]:
        candidates: list[Path] = []
        if str(instance_name or "").strip().lower() == "bot1":
            candidates.append(self._reports_root / "strategy" / "multi_day_summary_latest.json")
        candidates.append(self._reports_root / "strategy" / "multi_day_summary_latest.json")
        for path in candidates:
            payload = self._read_json(path)
            if payload:
                return payload
        return {}

    def account_summary(self, instance_name: str) -> dict[str, Any]:
        snapshot = self.get_snapshot(instance_name)
        if not snapshot:
            return _account_summary_template()
        minute = snapshot.get("minute", {}) if isinstance(snapshot.get("minute"), dict) else {}
        daily_state = snapshot.get("daily_state", {}) if isinstance(snapshot.get("daily_state"), dict) else {}
        snapshot.get("fill_stats", {}) if isinstance(snapshot.get("fill_stats"), dict) else {}
        portfolio = snapshot.get("portfolio", {}) if isinstance(snapshot.get("portfolio"), dict) else {}
        portfolio_inner = portfolio.get("portfolio", {}) if isinstance(portfolio.get("portfolio"), dict) else {}
        gate_summary = _build_quote_gate_summary(minute)
        # Derive reference date from the snapshot's own minute timestamp so
        # that staleness is relative to the bot's active session, not the
        # API server's wall clock. Fall back to timezone.utc today if unreadable.
        _minute_ts_str = str(minute.get("ts") or "").strip()
        try:
            _ref_date = datetime.fromisoformat(_minute_ts_str.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except Exception:
            _ref_date = datetime.now(UTC).strftime("%Y-%m-%d")
        daily_state_current = str(daily_state.get("day_key") or "").startswith(_ref_date)
        return {
            "equity_quote": float(_to_float(snapshot.get("equity_quote") or minute.get("equity_quote")) or 0.0),
            "quote_balance": float(_to_float(snapshot.get("quote_balance") or minute.get("quote_balance")) or 0.0),
            "equity_open_quote": float(
                _to_float(
                    snapshot.get("equity_open")
                    or minute.get("equity_open")
                    or (daily_state.get("equity_open") if daily_state_current else None)
                    or portfolio_inner.get("daily_open_equity")
                )
                or 0.0
            ),
            "equity_peak_quote": float(
                _to_float(
                    snapshot.get("equity_peak")
                    or minute.get("equity_peak")
                    or (daily_state.get("equity_peak") if daily_state_current else None)
                    or portfolio_inner.get("peak_equity")
                )
                or 0.0
            ),
            "realized_pnl_quote": _resolve_realized_pnl(minute, daily_state, daily_state_current),
            "controller_state": str(minute.get("state", "") or ""),
            "regime": str(minute.get("regime", "") or ""),
            "pnl_governor_active": _to_bool(minute.get("pnl_governor_active")),
            "pnl_governor_reason": str(minute.get("pnl_governor_activation_reason", "") or ""),
            "risk_reasons": str(minute.get("risk_reasons", "") or ""),
            "daily_loss_pct": float(_to_float(minute.get("daily_loss_pct")) or 0.0),
            "max_daily_loss_pct_hard": float(_to_float(minute.get("max_daily_loss_pct_hard")) or 0.0),
            "drawdown_pct": float(_to_float(minute.get("drawdown_pct")) or 0.0),
            "max_drawdown_pct_hard": float(_to_float(minute.get("max_drawdown_pct_hard")) or 0.0),
            "order_book_stale": _to_bool(minute.get("order_book_stale")),
            "soft_pause_edge": bool(gate_summary.get("soft_pause_edge")),
            "net_edge_pct": float(gate_summary.get("net_edge_pct") or 0.0),
            "net_edge_gate_pct": float(gate_summary.get("net_edge_gate_pct") or 0.0),
            "adaptive_effective_min_edge_pct": float(gate_summary.get("adaptive_effective_min_edge_pct") or 0.0),
            "spread_pct": float(gate_summary.get("spread_pct") or 0.0),
            "spread_floor_pct": float(gate_summary.get("spread_floor_pct") or 0.0),
            "spread_competitiveness_cap_active": bool(gate_summary.get("spread_competitiveness_cap_active")),
            "orders_active": int(gate_summary.get("orders_active") or 0),
            "quoting_status": str(gate_summary.get("quoting_status") or ""),
            "quoting_reason": str(gate_summary.get("quoting_reason") or ""),
            "quote_gates": list(gate_summary.get("quote_gates") or []),
            "snapshot_ts": str(snapshot.get("source_ts") or minute.get("ts") or ""),
        }

    def _minute_csv_candidates(self, instance_name: str) -> list[Path]:
        return list_instance_log_files(self._data_root, instance_name, "minute.csv")

    def _fills_csv_candidates(self, instance_name: str) -> list[Path]:
        return list_instance_log_files(self._data_root, instance_name, "fills.csv")

    def _paper_exchange_state_snapshot_path(self) -> Path:
        return self._reports_root / "verification" / "paper_exchange_state_snapshot_latest.json"

    def _paper_exchange_command_journal_path(self) -> Path:
        return self._reports_root / "verification" / "paper_exchange_command_journal_latest.json"

    def paper_exchange_position(
        self, instance_name: str, trading_pair: str = ""
    ) -> dict[str, Any]:
        """Read the authoritative position for *instance_name* from the
        centralized paper exchange state snapshot.

        Returns a dashboard-compatible position dict with signed ``quantity``,
        ``side``, and ``avg_entry_price``, or an empty dict when unavailable.
        """
        if not instance_name:
            return {}
        payload = self._read_json(self._paper_exchange_state_snapshot_path())
        positions = payload.get("positions", {})
        if not isinstance(positions, dict):
            return {}
        target_inst = str(instance_name).strip().lower()
        target_pair_norm = _normalize_pair(trading_pair)
        for key, pos in positions.items():
            if not isinstance(pos, dict):
                continue
            rec_inst = str(pos.get("instance_name", "") or "").strip().lower()
            if not rec_inst:
                parts = str(key).split("::")
                rec_inst = parts[0].strip().lower() if parts else ""
            if rec_inst != target_inst:
                continue
            if target_pair_norm:
                rec_pair = _normalize_pair(pos.get("trading_pair", ""))
                if not rec_pair:
                    parts = str(key).split("::")
                    rec_pair = _normalize_pair(parts[2]) if len(parts) > 2 else ""
                if rec_pair and rec_pair != target_pair_norm:
                    continue
            long_base = float(pos.get("long_base", 0) or 0)
            short_base = float(pos.get("short_base", 0) or 0)
            net_qty = long_base - short_base
            if abs(net_qty) < 1e-15 and long_base == 0 and short_base == 0:
                return {}
            if net_qty > 1e-15:
                side = "long"
                entry = float(pos.get("long_avg_entry_price", 0) or 0)
            elif net_qty < -1e-15:
                side = "short"
                entry = float(pos.get("short_avg_entry_price", 0) or 0)
            else:
                side = "flat"
                entry = 0.0
            return {
                "trading_pair": pos.get("trading_pair", trading_pair),
                "quantity": net_qty,
                "side": side,
                "avg_entry_price": entry,
                "long_quantity": long_base,
                "short_quantity": short_base,
                "long_avg_entry_price": float(pos.get("long_avg_entry_price", 0) or 0),
                "short_avg_entry_price": float(pos.get("short_avg_entry_price", 0) or 0),
                "realized_pnl_quote": float(pos.get("realized_pnl_quote", 0) or 0),
                "source": "paper_exchange_authoritative",
            }
        return {}

    def paper_exchange_order_owner_map(self) -> dict[str, str]:
        now_ms = _now_ms()
        cached_ts_ms, cached_owners = self._order_owner_cache
        if cached_ts_ms > 0 and (now_ms - cached_ts_ms) <= 60_000:
            return dict(cached_owners)
        owners: dict[str, str] = {}
        snapshot_payload = self._read_json(self._paper_exchange_state_snapshot_path())
        raw_orders = snapshot_payload.get("orders", {}) if isinstance(snapshot_payload.get("orders"), dict) else {}
        for order_id, record in raw_orders.items():
            if isinstance(record, dict):
                resolved_order_id = str(record.get("order_id", order_id) or "").strip()
                resolved_instance = str(record.get("instance_name", "") or "").strip()
                if resolved_order_id and resolved_instance:
                    owners[resolved_order_id] = resolved_instance
        journal_payload = self._read_json(self._paper_exchange_command_journal_path())
        raw_commands = journal_payload.get("commands", {}) if isinstance(journal_payload.get("commands"), dict) else {}
        for _event_id, record in raw_commands.items():
            if not isinstance(record, dict):
                continue
            resolved_order_id = str(record.get("order_id", "") or "").strip()
            resolved_instance = str(record.get("instance_name", "") or "").strip()
            if resolved_order_id and resolved_instance and resolved_order_id not in owners:
                owners[resolved_order_id] = resolved_instance
        self._order_owner_cache = (now_ms, dict(owners))
        return owners

    def filter_fill_rows_for_instance(self, instance_name: str, fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
        wanted_instance = str(instance_name or "").strip().lower()
        safe_fills = [row for row in fills if isinstance(row, dict)]
        if not wanted_instance or not safe_fills:
            return safe_fills
        owners = self.paper_exchange_order_owner_map()
        if not owners:
            return safe_fills
        filtered: list[dict[str, Any]] = []
        for row in safe_fills:
            order_id = str(row.get("order_id", "") or "").strip()
            if order_id:
                owner = str(owners.get(order_id, "") or "").strip().lower()
                if owner and owner != wanted_instance:
                    continue
            filtered.append(row)
        return filtered

    def _parse_ts_ms(self, value: Any) -> int | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            if raw.isdigit():
                parsed = int(raw)
                return parsed if parsed > 10_000_000_000 else parsed * 1000
        except Exception:
            return None
        try:
            normalized = raw.replace("Z", "+00:00")
            return int(datetime.fromisoformat(normalized).timestamp() * 1000)
        except Exception:
            return None

    def candles_from_minute_log(
        self,
        instance_name: str,
        trading_pair: str = "",
        timeframe_s: int = 60,
        limit: int = 300,
    ) -> list[dict[str, Any]]:
        timeframe_ms = max(1, int(timeframe_s)) * 1000
        limit = max(1, int(limit))
        trading_pair_norm = _normalize_pair(trading_pair)
        minutes_per_bucket = max(1, timeframe_ms // 60_000)
        tail_rows = max(1200, min(50_000, limit * minutes_per_bucket * 8))

        for csv_path in self._minute_csv_candidates(instance_name):
            candles = self._cached_csv_query(
                "candles_from_minute_log",
                csv_path,
                (trading_pair_norm, timeframe_ms, limit, tail_rows),
                lambda: self._load_candles_from_minute_log(csv_path, trading_pair_norm, timeframe_ms, limit, tail_rows),
            )
            if candles:
                return list(candles)
        return []

    def fills_from_csv(
        self,
        instance_name: str,
        trading_pair: str = "",
        limit: int = 120,
    ) -> list[dict[str, Any]]:
        limit = max(1, int(limit))
        trading_pair_norm = _normalize_pair(trading_pair)
        tail_rows = max(400, min(80_000, limit * 40))
        for csv_path in self._fills_csv_candidates(instance_name):
            rows = self._cached_csv_query(
                "fills_from_csv",
                csv_path,
                (trading_pair_norm, limit, tail_rows),
                lambda: self._load_fills_from_csv(csv_path, trading_pair_norm, limit, tail_rows),
            )
            if rows:
                return self.filter_fill_rows_for_instance(instance_name, list(rows)[-limit:])
        return []

    def minute_rows_from_csv(
        self,
        instance_name: str,
        trading_pair: str = "",
        day_key: str = "",
    ) -> list[dict[str, Any]]:
        trading_pair_norm = _normalize_pair(trading_pair)
        _, start_ms, end_ms = _day_bounds_utc(day_key)
        for csv_path in self._minute_csv_candidates(instance_name):
            rows = self._cached_csv_query(
                "minute_rows_from_csv",
                csv_path,
                (trading_pair_norm, start_ms, end_ms),
                lambda: self._load_minute_rows_from_csv(csv_path, trading_pair_norm, start_ms, end_ms),
            )
            if rows:
                return list(rows)
        return []

    def minute_rows_range(
        self,
        instance_name: str,
        trading_pair: str = "",
        start_day: str = "",
        end_day: str = "",
        limit: int = 20000,
    ) -> list[dict[str, Any]]:
        trading_pair_norm = _normalize_pair(trading_pair)
        start_ms = None
        end_ms = None
        if str(start_day or "").strip():
            _, start_ms, _ = _day_bounds_utc(start_day)
        if str(end_day or "").strip():
            _, _, end_ms = _day_bounds_utc(end_day)
        limit = max(1, int(limit))
        for csv_path in self._minute_csv_candidates(instance_name):
            rows = self._cached_csv_query(
                "minute_rows_range",
                csv_path,
                (trading_pair_norm, start_ms, end_ms, limit),
                lambda: self._load_minute_rows_range(csv_path, trading_pair_norm, start_ms, end_ms, limit),
            )
            if rows:
                return self.filter_fill_rows_for_instance(instance_name, rows[-limit:])
        return []

    def fills_from_csv_for_day(
        self,
        instance_name: str,
        trading_pair: str = "",
        day_key: str = "",
        limit: int = 4000,
    ) -> list[dict[str, Any]]:
        trading_pair_norm = _normalize_pair(trading_pair)
        _, start_ms, end_ms = _day_bounds_utc(day_key)
        limit = max(1, int(limit))
        for csv_path in self._fills_csv_candidates(instance_name):
            rows = self._cached_csv_query(
                "fills_from_csv_for_day",
                csv_path,
                (trading_pair_norm, start_ms, end_ms, limit),
                lambda: self._load_fills_for_day(csv_path, trading_pair_norm, start_ms, end_ms, limit),
            )
            if rows:
                return self.filter_fill_rows_for_instance(instance_name, rows[-limit:])
        return []

    def fills_from_csv_range(
        self,
        instance_name: str,
        trading_pair: str = "",
        start_day: str = "",
        end_day: str = "",
        limit: int = 10000,
    ) -> list[dict[str, Any]]:
        trading_pair_norm = _normalize_pair(trading_pair)
        start_ms = None
        end_ms = None
        if str(start_day or "").strip():
            _, start_ms, _ = _day_bounds_utc(start_day)
        if str(end_day or "").strip():
            _, _, end_ms = _day_bounds_utc(end_day)
        limit = max(1, int(limit))
        for csv_path in self._fills_csv_candidates(instance_name):
            rows = self._cached_csv_query(
                "fills_from_csv_range",
                csv_path,
                (trading_pair_norm, start_ms, end_ms, limit),
                lambda: self._load_fills_range(csv_path, trading_pair_norm, start_ms, end_ms, limit),
            )
            if rows:
                return rows[-limit:]
        return []

    def _load_candles_from_minute_log(
        self,
        csv_path: Path,
        trading_pair_norm: str,
        timeframe_ms: int,
        limit: int,
        tail_rows: int,
    ) -> list[dict[str, Any]]:
        points: deque[tuple[int, float]] = deque(maxlen=tail_rows)
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    if not isinstance(row, dict):
                        continue
                    if trading_pair_norm:
                        row_pair = _normalize_pair(row.get("trading_pair"))
                        if row_pair and row_pair != trading_pair_norm:
                            continue
                    ts_ms = self._parse_ts_ms(row.get("ts"))
                    mid = _to_float(row.get("mid"))
                    if ts_ms is None or mid is None or mid <= 0:
                        continue
                    points.append((ts_ms, mid))
        except Exception:
            return []
        if not points:
            return []
        buckets: dict[int, dict[str, Any]] = {}
        last_close: float | None = None
        last_bucket: int | None = None
        for ts_ms, price in points:
            bucket = (ts_ms // timeframe_ms) * timeframe_ms
            row = buckets.get(bucket)
            if row is None:
                open_price = price
                if timeframe_ms <= 60_000 and last_close is not None and last_bucket != bucket:
                    open_price = last_close
                buckets[bucket] = {
                    "bucket_ms": bucket,
                    "open": open_price,
                    "high": max(open_price, price),
                    "low": min(open_price, price),
                    "close": price,
                }
                last_close = price
                last_bucket = bucket
                continue
            row["high"] = max(float(row["high"]), price)
            row["low"] = min(float(row["low"]), price)
            row["close"] = price
            last_close = price
            last_bucket = bucket
        candles = [buckets[k] for k in sorted(buckets.keys())]
        return candles[-limit:] if candles else []

    def _load_fills_from_csv(
        self,
        csv_path: Path,
        trading_pair_norm: str,
        limit: int,
        tail_rows: int,
    ) -> list[dict[str, Any]]:
        rows: deque[dict[str, Any]] = deque(maxlen=tail_rows)
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    if not isinstance(row, dict):
                        continue
                    row_pair_norm = _normalize_pair(row.get("trading_pair"))
                    if trading_pair_norm and row_pair_norm and row_pair_norm != trading_pair_norm:
                        continue
                    ts_ms = self._parse_ts_ms(row.get("ts"))
                    price = _to_float(row.get("price"))
                    amount_base = _to_float(row.get("amount_base"))
                    if ts_ms is None or price is None:
                        continue
                    rows.append(
                        {
                            "ts": str(row.get("ts", "")),
                            "timestamp_ms": ts_ms,
                            "side": str(row.get("side", "")).upper(),
                            "price": price,
                            "amount_base": amount_base if amount_base is not None else 0.0,
                            "notional_quote": _to_float(row.get("notional_quote")) or 0.0,
                            "fee_quote": _to_float(row.get("fee_quote")) or 0.0,
                            "realized_pnl_quote": _to_float(row.get("realized_pnl_quote")) or 0.0,
                            "order_id": str(row.get("order_id", "")),
                            "is_maker": str(row.get("is_maker", "")).strip().lower() in {"1", "true", "yes"},
                        }
                    )
        except Exception:
            return []
        return list(rows)[-limit:] if rows else []

    def _load_minute_rows_from_csv(
        self,
        csv_path: Path,
        trading_pair_norm: str,
        start_ms: int,
        end_ms: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    if not isinstance(row, dict):
                        continue
                    row_pair_norm = _normalize_pair(row.get("trading_pair"))
                    if trading_pair_norm and row_pair_norm and row_pair_norm != trading_pair_norm:
                        continue
                    ts_ms = self._parse_ts_ms(row.get("ts"))
                    if ts_ms is None or ts_ms < start_ms or ts_ms >= end_ms:
                        continue
                    rows.append(
                        {
                            "ts": str(row.get("ts", "")),
                            "timestamp_ms": ts_ms,
                            "mid": _to_float(row.get("mid")) or 0.0,
                            "equity_quote": _to_float(row.get("equity_quote")) or 0.0,
                            "quote_balance": _to_float(row.get("quote_balance")) or 0.0,
                            "realized_pnl_today_quote": _to_float(row.get("realized_pnl_today_quote")) or 0.0,
                            "net_realized_pnl_today_quote": _to_float(row.get("net_realized_pnl_today_quote")) or 0.0,
                            "state": str(row.get("state", "") or ""),
                            "regime": str(row.get("regime", "") or ""),
                            "risk_reasons": str(row.get("risk_reasons", "") or ""),
                            "pnl_governor_active": _to_bool(row.get("pnl_governor_active")),
                            "order_book_stale": _to_bool(row.get("order_book_stale")),
                            "soft_pause_edge": _to_bool(row.get("soft_pause_edge")),
                            "net_edge_pct": _to_float(row.get("net_edge_pct")) or 0.0,
                            "net_edge_gate_pct": _to_float(row.get("net_edge_gate_pct")) or 0.0,
                            "adaptive_effective_min_edge_pct": _to_float(row.get("adaptive_effective_min_edge_pct")) or 0.0,
                            "spread_pct": _to_float(row.get("spread_pct")) or 0.0,
                            "spread_floor_pct": _to_float(row.get("spread_floor_pct")) or 0.0,
                            "spread_competitiveness_cap_active": _to_bool(row.get("spread_competitiveness_cap_active")),
                            "orders_active": int(_to_float(row.get("orders_active")) or 0),
                            "pnl_governor_activation_reason": str(row.get("pnl_governor_activation_reason", "") or ""),
                        }
                    )
        except Exception:
            return []
        return rows

    def _load_minute_rows_range(
        self,
        csv_path: Path,
        trading_pair_norm: str,
        start_ms: int | None,
        end_ms: int | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    if not isinstance(row, dict):
                        continue
                    row_pair_norm = _normalize_pair(row.get("trading_pair"))
                    if trading_pair_norm and row_pair_norm and row_pair_norm != trading_pair_norm:
                        continue
                    ts_ms = self._parse_ts_ms(row.get("ts"))
                    if ts_ms is None:
                        continue
                    if start_ms is not None and ts_ms < start_ms:
                        continue
                    if end_ms is not None and ts_ms >= end_ms:
                        continue
                    rows.append(
                        {
                            "ts": str(row.get("ts", "")),
                            "timestamp_ms": ts_ms,
                            "mid": _to_float(row.get("mid")) or 0.0,
                            "equity_quote": _to_float(row.get("equity_quote")) or 0.0,
                            "quote_balance": _to_float(row.get("quote_balance")) or 0.0,
                            "realized_pnl_today_quote": _to_float(row.get("realized_pnl_today_quote")) or 0.0,
                            "net_realized_pnl_today_quote": _to_float(row.get("net_realized_pnl_today_quote")) or 0.0,
                            "state": str(row.get("state", "") or ""),
                            "regime": str(row.get("regime", "") or ""),
                            "risk_reasons": str(row.get("risk_reasons", "") or ""),
                            "pnl_governor_active": _to_bool(row.get("pnl_governor_active")),
                            "order_book_stale": _to_bool(row.get("order_book_stale")),
                            "soft_pause_edge": _to_bool(row.get("soft_pause_edge")),
                            "net_edge_pct": _to_float(row.get("net_edge_pct")) or 0.0,
                            "net_edge_gate_pct": _to_float(row.get("net_edge_gate_pct")) or 0.0,
                            "adaptive_effective_min_edge_pct": _to_float(row.get("adaptive_effective_min_edge_pct")) or 0.0,
                            "spread_pct": _to_float(row.get("spread_pct")) or 0.0,
                            "spread_floor_pct": _to_float(row.get("spread_floor_pct")) or 0.0,
                            "spread_competitiveness_cap_active": _to_bool(row.get("spread_competitiveness_cap_active")),
                            "orders_active": int(_to_float(row.get("orders_active")) or 0),
                            "pnl_governor_activation_reason": str(row.get("pnl_governor_activation_reason", "") or ""),
                        }
                    )
        except Exception:
            return []
        return rows[-limit:] if rows else []

    def _load_fills_for_day(
        self,
        csv_path: Path,
        trading_pair_norm: str,
        start_ms: int,
        end_ms: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    if not isinstance(row, dict):
                        continue
                    row_pair_norm = _normalize_pair(row.get("trading_pair"))
                    if trading_pair_norm and row_pair_norm and row_pair_norm != trading_pair_norm:
                        continue
                    ts_ms = self._parse_ts_ms(row.get("ts"))
                    price = _to_float(row.get("price"))
                    amount_base = _to_float(row.get("amount_base"))
                    if ts_ms is None or ts_ms < start_ms or ts_ms >= end_ms or price is None:
                        continue
                    rows.append(
                        {
                            "ts": str(row.get("ts", "")),
                            "timestamp_ms": ts_ms,
                            "side": str(row.get("side", "")).upper(),
                            "price": price,
                            "amount_base": amount_base if amount_base is not None else 0.0,
                            "notional_quote": _to_float(row.get("notional_quote")) or 0.0,
                            "fee_quote": _to_float(row.get("fee_quote")) or 0.0,
                            "realized_pnl_quote": _to_float(row.get("realized_pnl_quote")) or 0.0,
                            "order_id": str(row.get("order_id", "")),
                            "is_maker": _to_bool(row.get("is_maker")),
                        }
                    )
        except Exception:
            return []
        return rows[-limit:] if rows else []

    def _load_fills_range(
        self,
        csv_path: Path,
        trading_pair_norm: str,
        start_ms: int | None,
        end_ms: int | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    if not isinstance(row, dict):
                        continue
                    row_pair_norm = _normalize_pair(row.get("trading_pair"))
                    if trading_pair_norm and row_pair_norm and row_pair_norm != trading_pair_norm:
                        continue
                    ts_ms = self._parse_ts_ms(row.get("ts"))
                    price = _to_float(row.get("price"))
                    amount_base = _to_float(row.get("amount_base"))
                    if ts_ms is None or price is None:
                        continue
                    if start_ms is not None and ts_ms < start_ms:
                        continue
                    if end_ms is not None and ts_ms >= end_ms:
                        continue
                    rows.append(
                        {
                            "ts": str(row.get("ts", "")),
                            "timestamp_ms": ts_ms,
                            "side": str(row.get("side", "")).upper(),
                            "price": price,
                            "amount_base": amount_base if amount_base is not None else 0.0,
                            "notional_quote": _to_float(row.get("notional_quote")) or 0.0,
                            "fee_quote": _to_float(row.get("fee_quote")) or 0.0,
                            "realized_pnl_quote": _to_float(row.get("realized_pnl_quote")) or 0.0,
                            "order_id": str(row.get("order_id", "")),
                            "is_maker": _to_bool(row.get("is_maker")),
                        }
                    )
        except Exception:
            return []
        return rows[-limit:] if rows else []

    def open_orders_from_state_snapshot(
        self,
        instance_name: str,
        trading_pair: str = "",
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        path = self._paper_exchange_state_snapshot_path()
        payload = self._read_json(path)
        orders = payload.get("orders", {}) if isinstance(payload.get("orders"), dict) else {}
        if not orders:
            return []
        limit = max(1, int(limit))
        trading_pair_norm = _normalize_pair(trading_pair)
        terminal_states = {"filled", "canceled", "cancelled", "rejected", "expired", "failed", "closed"}
        out: list[dict[str, Any]] = []
        for _, order in orders.items():
            if not isinstance(order, dict):
                continue
            if instance_name and str(order.get("instance_name", "")).strip() != instance_name:
                continue
            row_pair_norm = _normalize_pair(order.get("trading_pair"))
            if trading_pair_norm and row_pair_norm and row_pair_norm != trading_pair_norm:
                continue
            state_value = str(order.get("state", "")).strip().lower()
            if state_value in terminal_states:
                continue
            price = _to_float(order.get("price"))
            if price is None:
                continue
            out.append(
                {
                    "order_id": str(order.get("order_id", "")),
                    "side": str(order.get("side", "")).lower(),
                    "price": price,
                    "amount": _to_float(order.get("amount_base")) or 0.0,
                    "quantity": _to_float(order.get("amount_base")) or 0.0,
                    "state": state_value or "open",
                    "created_ts_ms": int(_to_float(order.get("created_ts_ms")) or 0),
                    "updated_ts_ms": int(_to_float(order.get("updated_ts_ms")) or 0),
                    "is_estimated": False,
                }
            )
        out.sort(key=lambda row: int(row.get("updated_ts_ms", 0) or 0))
        return out[-limit:]

    def state_from_snapshot(
        self,
        instance_name: str,
        trading_pair: str = "",
        max_fills: int = 120,
        max_orders: int = 40,
        include_csv_fills: bool = True,
        include_estimated_orders: bool = True,
    ) -> dict[str, Any]:
        snapshot = self.get_snapshot(instance_name)
        minute = snapshot.get("minute", {}) if isinstance(snapshot.get("minute"), dict) else {}
        portfolio = snapshot.get("portfolio", {}) if isinstance(snapshot.get("portfolio"), dict) else {}
        portfolio_inner = portfolio.get("portfolio", {}) if isinstance(portfolio.get("portfolio"), dict) else {}
        requested_pair_norm = _normalize_pair(trading_pair)
        snapshot_orders = snapshot.get("open_orders", []) if isinstance(snapshot.get("open_orders"), list) else []
        open_orders = []
        for order in snapshot_orders:
            if not isinstance(order, dict):
                continue
            if not requested_pair_norm:
                open_orders.append(order)
                continue
            row_pair_norm = _normalize_pair(order.get("trading_pair"))
            if row_pair_norm and row_pair_norm == requested_pair_norm:
                open_orders.append(order)
        if not open_orders:
            open_orders = self.open_orders_from_state_snapshot(instance_name, trading_pair, limit=max_orders)
        positions = portfolio_inner.get("positions", {}) if isinstance(portfolio_inner.get("positions"), dict) else {}
        resolved_position = {}
        if requested_pair_norm:
            for instrument_id, pos in positions.items():
                if not isinstance(pos, dict):
                    continue
                instrument_pair = str(instrument_id).split(":")[1] if ":" in str(instrument_id) else str(instrument_id)
                if requested_pair_norm == _normalize_pair(instrument_pair):
                    resolved_position = pos
                    break
        if not requested_pair_norm and not resolved_position and positions:
            # Fallback to first non-flat position so UI still shows active exposure when pair filter is stale/mismatched.
            for pos in positions.values():
                if not isinstance(pos, dict):
                    continue
                qty = _to_float(pos.get("quantity"))
                if qty is not None and abs(qty) > 0:
                    resolved_position = pos
                    break
        if not requested_pair_norm and not resolved_position and positions:
            first = next(iter(positions.values()), {})
            resolved_position = first if isinstance(first, dict) else {}

        minute_pair_norm = _normalize_pair(minute.get("trading_pair"))
        allow_runtime_estimated_orders = bool(
            not requested_pair_norm or resolved_position or (minute_pair_norm and minute_pair_norm == requested_pair_norm)
        )
        if include_estimated_orders and not open_orders and allow_runtime_estimated_orders:
            orders_active = int(_to_float(minute.get("orders_active")) or 0)
            if orders_active > 0:
                _resolved_pair = trading_pair or str(minute.get("trading_pair") or "")
                open_orders = _read_paper_exchange_active_orders(
                    self._paper_exchange_state_snapshot_path(), instance_name, _resolved_pair
                )
                if not open_orders:
                    best_bid = _to_float(minute.get("best_bid_price"))
                    best_ask = _to_float(minute.get("best_ask_price"))
                    qty = _to_float(resolved_position.get("quantity"))
                    open_orders = _build_runtime_open_order_placeholders(
                        orders_active=orders_active,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        mid_price=_to_float(minute.get("mid")) or _to_float(minute.get("mid_price")),
                        quantity=qty,
                        trading_pair=_resolved_pair,
                        timestamp_ms=_to_epoch_ms(minute.get("ts")) or _to_epoch_ms(snapshot.get("source_ts")) or _now_ms(),
                        source_label="runtime",
                    )

        fills = self.fills_from_csv(instance_name, trading_pair, limit=max_fills) if include_csv_fills else []
        return {
            "snapshot_ts": str(snapshot.get("source_ts", "")),
            "minute": minute,
            "open_orders": open_orders,
            "fills": fills,
            "position": resolved_position,
            "portfolio": portfolio_inner,
        }
