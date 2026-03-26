"""CCXT REST OHLCV reader for MarketHistoryProviderImpl (history seed / fallback).

Fetches **1-minute** closed candles from the public exchange API so they can be
fed into PriceBuffer, which always stores 1m bars and resamples to
``indicator_resolution`` (e.g. 15m) internally.

Only ``bar_interval_s == 60`` is supported here; the kernel's
``seed_price_buffer`` path uses 1m bars exclusively.
"""
from __future__ import annotations

import logging
import os
import time
from decimal import Decimal
from typing import Any

from platform_lib.market_data.market_history_types import MarketBar, MarketBarKey

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


def _env_ccxt_enabled() -> bool:
    raw = str(os.getenv("HB_HISTORY_CCXT_ENABLED", "true")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _pair_to_ccxt_symbol(trading_pair: str, *, swap: bool) -> str:
    """Convert Hummingbot-style ``BTC-USDT`` to a ccxt unified symbol."""
    raw = trading_pair.replace("/", "-").replace("_", "-")
    parts = [p for p in raw.split("-") if p]
    if len(parts) >= 2:
        base, quote = parts[0], parts[1]
        if swap:
            return f"{base}/{quote}:{quote}"
        return f"{base}/{quote}"
    return trading_pair


def _symbol_for_exchange(ex: Any, trading_pair: str, *, swap: bool) -> str:
    override = str(os.getenv("HB_HISTORY_CCXT_SYMBOL_OVERRIDE", "") or "").strip()
    if override:
        return override
    candidate = _pair_to_ccxt_symbol(trading_pair, swap=swap)
    try:
        ex.load_markets()
        if candidate in ex.markets:
            return candidate
        raw = trading_pair.replace("/", "-").replace("_", "-")
        parts = [p for p in raw.split("-") if p]
        if len(parts) >= 2:
            spot = f"{parts[0]}/{parts[1]}"
            if spot in ex.markets:
                return spot
    except Exception as exc:
        logger.debug("ccxt load_markets failed: %s", exc)
    return candidate


def ccxt_rest_bar_reader(
    key: MarketBarKey,
    bar_interval_s: int,
    limit: int,
    end_time_ms: int | None,
    require_closed: bool,
) -> list[MarketBar]:
    """BarReader compatible with MarketHistoryProviderImpl (1m OHLCV only)."""
    if not _env_ccxt_enabled():
        return []
    src = str(key.bar_source or "").strip().lower()
    if src not in {"quote_mid", "exchange_ohlcv"}:
        return []
    if int(bar_interval_s) != 60:
        return []

    connector = str(key.connector_name or "").strip()
    pair = str(key.trading_pair or "").strip()
    if not connector or not pair:
        return []

    n = connector.lower()
    swap = "perp" in n or "perpetual" in n or "swap" in n or "future" in n

    try:
        import ccxt  # type: ignore[import-untyped]
    except Exception:
        return []

    ex_id: str | None = None
    opts: dict[str, Any] = {"enableRateLimit": True}
    if "bitget" in n:
        ex_id = "bitget"
        opts["options"] = {"defaultType": "swap" if swap else "spot"}
    elif "binance" in n:
        ex_id = "binance"
        opts["options"] = {"defaultType": "future" if swap else "spot"}
    elif "okx" in n or "okex" in n:
        ex_id = "okx"
        opts["options"] = {"defaultType": "swap" if swap else "spot"}
    elif "bybit" in n:
        ex_id = "bybit"
        opts["options"] = {"defaultType": "linear" if swap else "spot"}

    override_id = str(os.getenv("HB_HISTORY_CCXT_EXCHANGE_ID", "") or "").strip()
    if override_id:
        ex_id = override_id
    if not ex_id:
        logger.info(
            "HB_HISTORY CCXT: unknown connector %s; set HB_HISTORY_CCXT_EXCHANGE_ID (+ optional HB_HISTORY_CCXT_SYMBOL_OVERRIDE)",
            connector,
        )
        return []

    exchange_cls = getattr(ccxt, str(ex_id), None)
    if exchange_cls is None:
        return []

    ex = exchange_cls(opts)
    symbol = _symbol_for_exchange(ex, pair, swap=swap)

    eff_end = int(end_time_ms or int(time.time() * 1000))
    need = max(1, min(int(limit), 1500))
    by_ts: dict[int, MarketBar] = {}
    until_ms = eff_end
    guard = 0
    while len(by_ts) < need and guard < 40:
        guard += 1
        batch_want = min(200, max(need - len(by_ts), 50))
        since_ms = max(0, until_ms - batch_want * 60_000)
        try:
            batch = ex.fetch_ohlcv(symbol, "1m", since=since_ms, limit=batch_want)
        except Exception as exc:
            logger.warning(
                "ccxt fetch_ohlcv failed connector=%s symbol=%s: %s",
                connector,
                symbol,
                exc,
            )
            break
        if not batch:
            break
        for row in batch:
            ts = int(row[0])
            if require_closed and ts + 60_000 > eff_end:
                continue
            if ts >= eff_end:
                continue
            o, h, lo, c = (Decimal(str(x)) for x in row[1:5])
            if min(o, h, lo, c) <= _ZERO:
                continue
            by_ts[ts] = MarketBar(
                bucket_start_ms=ts,
                bar_interval_s=60,
                open=o,
                high=h,
                low=lo,
                close=c,
                volume_base=Decimal(str(row[5])) if len(row) > 5 else None,
                is_closed=True,
                bar_source="exchange_ohlcv",
            )
        first_ts = int(batch[0][0])
        until_ms = first_ts - 1
        if len(batch) < batch_want:
            break

    ordered = sorted(by_ts.values(), key=lambda b: b.bucket_start_ms)
    if len(ordered) > need:
        ordered = ordered[-need:]
    if ordered:
        logger.info(
            "HB_HISTORY CCXT seeded %d x 1m bars for %s %s (symbol=%s)",
            len(ordered),
            connector,
            pair,
            symbol,
        )
    return ordered


__all__ = ["ccxt_rest_bar_reader"]
