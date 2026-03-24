"""CCXT-backed downloader for OHLCV candles and raw trades.

Refactored from ``scripts/analysis/fetch_historical_ohlcv.py``.  The
original script-level ``_fetch_ohlcv_ccxt`` function has been promoted to a
proper class that:

* Uses structured logging instead of ``print``.
* Applies exponential back-off on rate-limit / gateway errors with a
  configurable retry cap.
* Accepts an optional ``progress_cb`` callable for UI / tqdm integration.
* Supports resume via ``resume_from_ms`` to skip already-downloaded ranges.
* Provides a ``download_trades`` path for tick-level data.
* Keeps ``import ccxt`` lazy so the module can be imported without ccxt.
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from controllers.backtesting.data_catalog import DataCatalog
from controllers.backtesting.data_store import (
    load_funding_rates,
    load_long_short_ratio,
    load_trades,
    resolve_data_path,
    save_candles,
    save_funding_rates,
    save_long_short_ratio,
    save_trades,
    validate_candles,
)
from controllers.backtesting.types import CandleRow, FundingRow, LongShortRatioRow, TradeRow

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry constants
# ---------------------------------------------------------------------------

_RETRY_INITIAL_S: float = 2.0
_RETRY_MAX_S: float = 60.0
_RETRY_MAX_ATTEMPTS: int = 5

# Patterns that indicate a transient server-side / rate-limit error.
_TRANSIENT_ERROR_PATTERNS = (
    "429",
    "503",
    "502",
    "504",
    "timeout",
    "rate limit",
    "ratelimit",
    "too many requests",
    "ddos",
)


def _is_transient(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(p in msg for p in _TRANSIENT_ERROR_PATTERNS)


def _catalog_pair_key(symbol: str) -> str:
    safe_pair = symbol.replace("/", "-").replace(":", "-").split("-")
    return f"{safe_pair[0]}-{safe_pair[1]}" if len(safe_pair) >= 2 else symbol


# ---------------------------------------------------------------------------
# DataDownloader
# ---------------------------------------------------------------------------

class DataDownloader:
    """Download historical OHLCV candles or raw trades via ccxt.

    Parameters
    ----------
    exchange_id:
        A valid ccxt exchange identifier, e.g. ``"bitget"`` or ``"binance"``.
    delay_s:
        Polite sleep between successful batch requests (seconds).

    Example
    -------
    ::

        dl = DataDownloader("bitget")
        candles = dl.download_candles(
            "BTC/USDT:USDT", "1m", since_ms=..., until_ms=...
        )
    """

    def __init__(self, exchange_id: str, delay_s: float = 0.3) -> None:
        self._exchange_id = exchange_id
        self._delay_s = delay_s
        self._exchange: Any = None  # Lazily initialised ccxt exchange instance

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_exchange(self) -> Any:
        """Return the ccxt exchange instance, creating it on first call."""
        if self._exchange is not None:
            return self._exchange
        try:
            import ccxt  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "ccxt is required for downloading market data: pip install ccxt"
            ) from exc

        exchange_cls = getattr(ccxt, self._exchange_id, None)
        if exchange_cls is None:
            raise ValueError(f"Unknown ccxt exchange id: {self._exchange_id!r}")

        self._exchange = exchange_cls({
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        })
        self._ohlcv_max_limit: int = self._detect_ohlcv_limit()
        logger.debug("Initialised ccxt exchange: %s (ohlcv_max_limit=%d)", self._exchange_id, self._ohlcv_max_limit)
        return self._exchange

    def _detect_ohlcv_limit(self) -> int:
        """Return the safe per-request OHLCV limit for this exchange.

        Bitget uses a different endpoint when limit > 200, which returns
        non-contiguous data.  Default conservatively for unknown exchanges.
        """
        _EXCHANGE_LIMITS = {"bitget": 200, "binance": 1000, "bybit": 200, "okx": 300}
        return _EXCHANGE_LIMITS.get(self._exchange_id, 200)

    def _call_with_backoff(
        self,
        fn: Callable[[], Any],
        context: str,
    ) -> Any:
        """Call *fn* and retry on transient errors with exponential back-off.

        Parameters
        ----------
        fn:
            Zero-argument callable that executes the ccxt request.
        context:
            Human-readable description for log messages.

        Raises
        ------
        Exception
            Re-raises the last exception once ``_RETRY_MAX_ATTEMPTS`` is
            exhausted, or immediately for non-transient errors.
        """
        retry_delay = _RETRY_INITIAL_S
        for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
            try:
                return fn()
            except Exception as exc:
                if not _is_transient(exc):
                    raise
                if attempt == _RETRY_MAX_ATTEMPTS:
                    logger.error(
                        "%s — transient error after %d attempts, giving up: %s",
                        context, attempt, exc,
                    )
                    raise
                logger.warning(
                    "%s — transient error (attempt %d/%d), retrying in %.0fs: %s",
                    context, attempt, _RETRY_MAX_ATTEMPTS, retry_delay, exc,
                )
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, _RETRY_MAX_S)
        # Unreachable, but satisfies type checkers.
        raise RuntimeError(f"{context}: exhausted retries")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def download_candles(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
        until_ms: int,
        limit: int = 1000,
        resume_from_ms: int | None = None,
        progress_cb: Callable[[int, int, int], None] | None = None,
    ) -> list[CandleRow]:
        """Download OHLCV bars for *symbol* between *since_ms* and *until_ms*.

        Parameters
        ----------
        symbol:
            ccxt symbol string, e.g. ``"BTC/USDT:USDT"``.
        timeframe:
            ccxt timeframe string, e.g. ``"1m"``, ``"5m"``, ``"1h"``.
        since_ms:
            Start of the range (Unix milliseconds, inclusive).
        until_ms:
            End of the range (Unix milliseconds, exclusive).
        limit:
            Maximum number of bars per API request.
        resume_from_ms:
            If provided, skip downloading data before this timestamp.  Use
            this to continue an interrupted download.
        progress_cb:
            Optional callback invoked after each successful batch with
            ``(bars_so_far, current_timestamp_ms, until_ms)``.

        Returns
        -------
        list[CandleRow]
            De-duplicated, sorted candle rows clipped to ``[since_ms, until_ms)``.
        """
        exchange = self._ensure_exchange()
        limit = min(limit, self._ohlcv_max_limit)
        effective_since = max(since_ms, resume_from_ms) if resume_from_ms else since_ms
        current_since = effective_since

        if resume_from_ms and resume_from_ms > since_ms:
            logger.info(
                "Resuming %s %s download from %d (skipping %d ms)",
                symbol, timeframe, resume_from_ms, resume_from_ms - since_ms,
            )

        logger.info(
            "Downloading %s %s [%d, %d) from %s (limit=%d) ...",
            symbol, timeframe, effective_since, until_ms, self._exchange_id, limit,
        )

        raw_bars: list[list] = []
        while current_since < until_ms:
            def _fetch(
                _since: int = current_since,
            ) -> list:
                return exchange.fetch_ohlcv(
                    symbol,
                    timeframe=timeframe,
                    since=_since,
                    limit=limit,
                )

            batch = self._call_with_backoff(
                _fetch,
                context=f"{self._exchange_id} fetch_ohlcv {symbol}@{timeframe}",
            )

            if not batch:
                break

            # Clip to requested range.
            batch = [b for b in batch if b[0] < until_ms]
            if not batch:
                break

            raw_bars.extend(batch)

            last_ts: int = batch[-1][0]
            if last_ts <= current_since:
                logger.warning(
                    "No progress from exchange: last_ts=%d <= current_since=%d; "
                    "stopping pagination for %s %s",
                    last_ts, current_since, symbol, timeframe,
                )
                break

            current_since = last_ts + 1

            if progress_cb is not None:
                progress_cb(len(raw_bars), last_ts, until_ms)

            logger.debug(
                "Fetched %d bars so far (last ts=%d) for %s %s",
                len(raw_bars), last_ts, symbol, timeframe,
            )
            time.sleep(self._delay_s)

        candles = self._raw_bars_to_candle_rows(raw_bars)
        logger.info(
            "Downloaded %d candles for %s %s", len(candles), symbol, timeframe,
        )
        return candles

    def download_trades(
        self,
        symbol: str,
        since_ms: int,
        until_ms: int,
        limit: int = 1000,
        resume_from_ms: int | None = None,
        progress_cb: Callable[[int, int, int], None] | None = None,
    ) -> list[TradeRow]:
        """Download raw trades for *symbol* between *since_ms* and *until_ms*.

        Parameters
        ----------
        symbol:
            ccxt symbol string, e.g. ``"BTC/USDT:USDT"``.
        since_ms:
            Start of the range (Unix milliseconds, inclusive).
        until_ms:
            End of the range (Unix milliseconds, exclusive).
        limit:
            Maximum number of trades per API request.
        resume_from_ms:
            If provided, skip downloading data before this timestamp.
        progress_cb:
            Optional callback invoked after each batch with
            ``(trades_so_far, current_timestamp_ms, until_ms)``.

        Returns
        -------
        list[TradeRow]
            De-duplicated (by ``trade_id`` when available), sorted trade rows
            clipped to ``[since_ms, until_ms)``.

        Raises
        ------
        NotImplementedError
            If the exchange does not support ``fetch_trades`` for *symbol*.
        """
        exchange = self._ensure_exchange()

        if not self.supports_trades(symbol):
            raise NotImplementedError(
                f"Exchange {self._exchange_id!r} does not support fetch_trades "
                f"for {symbol!r}.  Use download_candles() instead, or choose a "
                "different data source."
            )

        effective_since = max(since_ms, resume_from_ms) if resume_from_ms else since_ms
        current_since = effective_since

        if resume_from_ms and resume_from_ms > since_ms:
            logger.info(
                "Resuming %s trades download from %d (skipping %d ms)",
                symbol, resume_from_ms, resume_from_ms - since_ms,
            )

        logger.info(
            "Downloading trades %s [%d, %d) from %s ...",
            symbol, effective_since, until_ms, self._exchange_id,
        )

        raw_trades: list[dict] = []
        seen_ids: set[str] = set()

        while current_since < until_ms:
            def _fetch(
                _since: int = current_since,
            ) -> list:
                return exchange.fetch_trades(
                    symbol,
                    since=_since,
                    limit=limit,
                )

            batch = self._call_with_backoff(
                _fetch,
                context=f"{self._exchange_id} fetch_trades {symbol}",
            )

            if not batch:
                break

            # Clip to requested range.
            batch = [t for t in batch if t["timestamp"] < until_ms]
            if not batch:
                break

            last_ts: int = batch[-1]["timestamp"]

            for trade in batch:
                tid = str(trade.get("id") or "")
                # De-duplicate by trade_id when the exchange provides one.
                if tid and tid in seen_ids:
                    continue
                if tid:
                    seen_ids.add(tid)
                raw_trades.append(trade)

            if last_ts <= current_since:
                logger.warning(
                    "No progress from exchange: last_ts=%d <= current_since=%d; "
                    "stopping pagination for %s trades",
                    last_ts, current_since, symbol,
                )
                break

            current_since = last_ts + 1

            if progress_cb is not None:
                progress_cb(len(raw_trades), last_ts, until_ms)

            logger.debug(
                "Fetched %d trades so far (last ts=%d) for %s",
                len(raw_trades), last_ts, symbol,
            )
            time.sleep(self._delay_s)

        trades = self._raw_trades_to_trade_rows(raw_trades)
        logger.info("Downloaded %d trades for %s", len(trades), symbol)
        return trades

    def supports_trades(self, symbol: str) -> bool:
        """Return ``True`` if this exchange advertises ``fetch_trades`` support.

        The check is based on the ccxt ``has`` capability dict and does not
        make a network call.
        """
        exchange = self._ensure_exchange()
        has_attr = exchange.has.get("fetchTrades", False)
        if not has_attr:
            return False
        # Some exchanges report the capability but only for spot, not swap.
        # We do a best-effort market check when markets are already loaded.
        markets: dict = exchange.markets or {}
        if markets and symbol in markets:
            market = markets[symbol]
            # ccxt market dicts include an "info" sub-dict; absence of explicit
            # "false" is taken as supported.
            return market.get("active", True)
        return bool(has_attr)

    def download_funding_rates(
        self,
        symbol: str,
        since_ms: int,
        until_ms: int,
        limit: int = 200,
        resume_from_ms: int | None = None,
        progress_cb: Callable[[int, int, int], None] | None = None,
    ) -> list[FundingRow]:
        """Download funding-rate history for *symbol* between *since_ms* and *until_ms*."""
        exchange = self._ensure_exchange()
        has_attr = bool(exchange.has.get("fetchFundingRateHistory", False))
        if not has_attr or not hasattr(exchange, "fetch_funding_rate_history"):
            raise NotImplementedError(
                f"Exchange {self._exchange_id!r} does not support fetch_funding_rate_history "
                f"for {symbol!r}."
            )

        effective_since = max(since_ms, resume_from_ms) if resume_from_ms else since_ms
        current_since = effective_since
        raw_rates: list[dict] = []

        while current_since < until_ms:
            def _fetch(_since: int = current_since) -> list:
                return exchange.fetch_funding_rate_history(
                    symbol,
                    since=_since,
                    limit=limit,
                )

            batch = self._call_with_backoff(
                _fetch,
                context=f"{self._exchange_id} fetch_funding_rate_history {symbol}",
            )
            if not batch:
                break

            batch = [row for row in batch if int(row.get("timestamp", 0) or 0) < until_ms]
            if not batch:
                break

            raw_rates.extend(batch)
            last_ts = int(batch[-1]["timestamp"])
            if last_ts <= current_since:
                logger.warning(
                    "No progress from exchange: last_ts=%d <= current_since=%d; stopping pagination for %s funding",
                    last_ts,
                    current_since,
                    symbol,
                )
                break

            current_since = last_ts + 1
            if progress_cb is not None:
                progress_cb(len(raw_rates), last_ts, until_ms)
            time.sleep(self._delay_s)

        rates = self._raw_funding_to_rows(raw_rates)
        logger.info("Downloaded %d funding rows for %s", len(rates), symbol)
        return rates

    def download_and_register_candles(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
        until_ms: int,
        *,
        base_dir: str | Path,
        pair: str,
        resume: bool = True,
        progress_cb: Callable[[int, int, int], None] | None = None,
    ) -> list[CandleRow]:
        """Download OHLCV candles, persist to parquet, and register in catalog.

        Uses the same resume-aware merge pattern as the mark/index/funding
        equivalents: checks the catalog for an existing end timestamp and
        resumes from there, then merges old + new data before saving.
        """
        from controllers.backtesting.data_store import load_candles as _load_candles
        base_dir = Path(base_dir)
        catalog = DataCatalog(base_dir=base_dir)
        existing = catalog.find(self._exchange_id, pair, timeframe)
        resume_from_ms = int(existing["end_ms"]) if resume and existing is not None else None

        downloaded = self.download_candles(
            symbol,
            timeframe,
            since_ms,
            until_ms,
            resume_from_ms=resume_from_ms,
            progress_cb=progress_cb,
        )

        combined: list[CandleRow] = []
        out_path = resolve_data_path(self._exchange_id, pair, timeframe, base_dir)
        if resume_from_ms and out_path.exists():
            combined.extend(_load_candles(out_path))
        combined.extend(downloaded)

        deduped: dict[int, CandleRow] = {c.timestamp_ms: c for c in combined}
        rows = sorted(deduped.values(), key=lambda c: c.timestamp_ms)
        if not rows:
            return rows

        _TF_TO_MS = {
            "1m": 60_000, "3m": 180_000, "5m": 300_000,
            "15m": 900_000, "30m": 1_800_000,
            "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
            "6h": 21_600_000, "8h": 28_800_000, "12h": 43_200_000,
            "1d": 86_400_000,
        }
        interval_ms = _TF_TO_MS.get(timeframe, 60_000)
        warnings = validate_candles(rows, expected_interval_ms=interval_ms)
        for w in warnings:
            logger.warning("Candle validation: %s", w)

        save_candles(rows, out_path)
        catalog.register(
            exchange=self._exchange_id,
            pair=pair,
            resolution=timeframe,
            start_ms=rows[0].timestamp_ms,
            end_ms=rows[-1].timestamp_ms,
            row_count=len(rows),
            file_path=str(out_path),
            file_size_bytes=out_path.stat().st_size,
        )
        return rows

    def download_and_register_trades(
        self,
        symbol: str,
        since_ms: int,
        until_ms: int,
        *,
        base_dir: str | Path,
        pair: str,
        resume: bool = True,
        progress_cb: Callable[[int, int, int], None] | None = None,
    ) -> list[TradeRow]:
        """Download raw trades, persist to parquet, and register in catalog."""
        base_dir = Path(base_dir)
        catalog = DataCatalog(base_dir=base_dir)
        existing = catalog.find(self._exchange_id, pair, "trades")
        resume_from_ms = int(existing["end_ms"]) if resume and existing is not None else None

        downloaded = self.download_trades(
            symbol,
            since_ms,
            until_ms,
            resume_from_ms=resume_from_ms,
            progress_cb=progress_cb,
        )

        combined: list[TradeRow] = []
        out_path = resolve_data_path(self._exchange_id, pair, "trades", base_dir)
        if resume_from_ms and out_path.exists():
            combined.extend(load_trades(out_path))
        combined.extend(downloaded)

        deduped: dict[tuple[str, int, str, str, str], TradeRow] = {}
        for trade in combined:
            key = (
                f"id:{trade.trade_id}"
                if trade.trade_id
                else f"fallback:{trade.timestamp_ms}:{trade.side}:{trade.price.normalize()}:{trade.size.normalize()}",
                trade.timestamp_ms,
                trade.side,
                str(trade.price.normalize()),
                str(trade.size.normalize()),
            )
            deduped[key] = trade
        rows = sorted(deduped.values(), key=lambda trade: trade.timestamp_ms)
        if not rows:
            return rows

        save_trades(rows, out_path)
        catalog.register(
            exchange=self._exchange_id,
            pair=pair,
            resolution="trades",
            start_ms=rows[0].timestamp_ms,
            end_ms=rows[-1].timestamp_ms,
            row_count=len(rows),
            file_path=str(out_path),
            file_size_bytes=out_path.stat().st_size,
        )
        return rows

    def download_and_register_funding(
        self,
        symbol: str,
        since_ms: int,
        until_ms: int,
        *,
        base_dir: str | Path,
        pair: str,
        resume: bool = True,
        progress_cb: Callable[[int, int, int], None] | None = None,
    ) -> list[FundingRow]:
        """Download funding history, persist to parquet, and register in catalog."""
        base_dir = Path(base_dir)
        catalog = DataCatalog(base_dir=base_dir)
        existing = catalog.find(self._exchange_id, pair, "funding")
        resume_from_ms = int(existing["end_ms"]) if resume and existing is not None else None

        downloaded = self.download_funding_rates(
            symbol,
            since_ms,
            until_ms,
            resume_from_ms=resume_from_ms,
            progress_cb=progress_cb,
        )

        combined: list[FundingRow] = []
        out_path = resolve_data_path(self._exchange_id, pair, "funding", base_dir)
        if resume_from_ms and out_path.exists():
            combined.extend(load_funding_rates(out_path))
        combined.extend(downloaded)

        deduped: dict[int, FundingRow] = {row.timestamp_ms: row for row in combined}
        rows = sorted(deduped.values(), key=lambda row: row.timestamp_ms)
        if not rows:
            return rows

        save_funding_rates(rows, out_path)
        catalog.register(
            exchange=self._exchange_id,
            pair=pair,
            resolution="funding",
            start_ms=rows[0].timestamp_ms,
            end_ms=rows[-1].timestamp_ms,
            row_count=len(rows),
            file_path=str(out_path),
            file_size_bytes=out_path.stat().st_size,
        )
        return rows

    # ------------------------------------------------------------------
    # Mark / Index candles
    # ------------------------------------------------------------------

    def download_mark_candles(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
        until_ms: int,
        limit: int = 1000,
        resume_from_ms: int | None = None,
        progress_cb: Callable[[int, int, int], None] | None = None,
    ) -> list[CandleRow]:
        """Download mark-price OHLCV for *symbol* via ``params={"price": "mark"}``."""
        return self._download_candles_with_params(
            symbol, timeframe, since_ms, until_ms,
            params={"price": "mark"},
            label="mark",
            limit=limit,
            resume_from_ms=resume_from_ms,
            progress_cb=progress_cb,
        )

    def download_index_candles(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
        until_ms: int,
        limit: int = 1000,
        resume_from_ms: int | None = None,
        progress_cb: Callable[[int, int, int], None] | None = None,
    ) -> list[CandleRow]:
        """Download index-price OHLCV for *symbol* via ``params={"price": "index"}``."""
        return self._download_candles_with_params(
            symbol, timeframe, since_ms, until_ms,
            params={"price": "index"},
            label="index",
            limit=limit,
            resume_from_ms=resume_from_ms,
            progress_cb=progress_cb,
        )

    def _download_candles_with_params(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
        until_ms: int,
        *,
        params: dict[str, str],
        label: str,
        limit: int = 1000,
        resume_from_ms: int | None = None,
        progress_cb: Callable[[int, int, int], None] | None = None,
    ) -> list[CandleRow]:
        """Shared implementation for mark/index candle downloads."""
        exchange = self._ensure_exchange()
        limit = min(limit, self._ohlcv_max_limit)
        effective_since = max(since_ms, resume_from_ms) if resume_from_ms else since_ms
        current_since = effective_since

        if resume_from_ms and resume_from_ms > since_ms:
            logger.info(
                "Resuming %s %s %s download from %d",
                symbol, label, timeframe, resume_from_ms,
            )

        logger.info(
            "Downloading %s %s %s [%d, %d) from %s ...",
            symbol, label, timeframe, effective_since, until_ms, self._exchange_id,
        )

        raw_bars: list[list] = []
        while current_since < until_ms:
            def _fetch(_since: int = current_since, _params: dict = params) -> list:
                return exchange.fetch_ohlcv(
                    symbol, timeframe=timeframe, since=_since, limit=limit, params=_params,
                )

            batch = self._call_with_backoff(
                _fetch,
                context=f"{self._exchange_id} fetch_ohlcv({label}) {symbol}@{timeframe}",
            )
            if not batch:
                break

            batch = [b for b in batch if b[0] < until_ms]
            if not batch:
                break

            raw_bars.extend(batch)
            last_ts: int = batch[-1][0]
            if last_ts <= current_since:
                break

            current_since = last_ts + 1
            if progress_cb is not None:
                progress_cb(len(raw_bars), last_ts, until_ms)
            time.sleep(self._delay_s)

        candles = self._raw_bars_to_candle_rows(raw_bars)
        logger.info("Downloaded %d %s candles for %s %s", len(candles), label, symbol, timeframe)
        return candles

    # ------------------------------------------------------------------
    # Long/short ratio
    # ------------------------------------------------------------------

    def download_long_short_ratio(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
        until_ms: int,
        limit: int = 200,
        resume_from_ms: int | None = None,
        progress_cb: Callable[[int, int, int], None] | None = None,
    ) -> list[LongShortRatioRow]:
        """Download long/short ratio history for *symbol*.

        Raises NotImplementedError if the exchange lacks the capability.
        """
        exchange = self._ensure_exchange()
        if not exchange.has.get("fetchLongShortRatioHistory"):
            raise NotImplementedError(
                f"Exchange {self._exchange_id!r} does not support "
                f"fetchLongShortRatioHistory for {symbol!r}."
            )

        effective_since = max(since_ms, resume_from_ms) if resume_from_ms else since_ms
        current_since = effective_since

        logger.info(
            "Downloading LS ratio %s %s [%d, %d) from %s ...",
            symbol, timeframe, effective_since, until_ms, self._exchange_id,
        )

        raw: list[dict] = []
        while current_since < until_ms:
            def _fetch(_since: int = current_since) -> list:
                return exchange.fetch_long_short_ratio_history(
                    symbol, timeframe=timeframe, since=_since, limit=limit,
                )

            batch = self._call_with_backoff(
                _fetch,
                context=f"{self._exchange_id} fetch_long_short_ratio_history {symbol}",
            )
            if not batch:
                break

            batch = [r for r in batch if int(r.get("timestamp", 0) or 0) < until_ms]
            if not batch:
                break

            raw.extend(batch)
            last_ts = int(batch[-1]["timestamp"])
            if last_ts <= current_since:
                break

            current_since = last_ts + 1
            if progress_cb is not None:
                progress_cb(len(raw), last_ts, until_ms)
            time.sleep(self._delay_s)

        rows = self._raw_ls_ratio_to_rows(raw)
        logger.info("Downloaded %d LS-ratio rows for %s", len(rows), symbol)
        return rows

    # ------------------------------------------------------------------
    # Register convenience methods (mark, index, LS ratio)
    # ------------------------------------------------------------------

    def download_and_register_mark_candles(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
        until_ms: int,
        *,
        base_dir: str | Path,
        pair: str,
        resume: bool = True,
        progress_cb: Callable[[int, int, int], None] | None = None,
    ) -> list[CandleRow]:
        """Download mark candles, persist, and register in catalog."""
        return self._download_and_register_candles_variant(
            symbol, timeframe, since_ms, until_ms,
            variant="mark",
            base_dir=base_dir, pair=pair, resume=resume, progress_cb=progress_cb,
        )

    def download_and_register_index_candles(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
        until_ms: int,
        *,
        base_dir: str | Path,
        pair: str,
        resume: bool = True,
        progress_cb: Callable[[int, int, int], None] | None = None,
    ) -> list[CandleRow]:
        """Download index candles, persist, and register in catalog."""
        return self._download_and_register_candles_variant(
            symbol, timeframe, since_ms, until_ms,
            variant="index",
            base_dir=base_dir, pair=pair, resume=resume, progress_cb=progress_cb,
        )

    def _download_and_register_candles_variant(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
        until_ms: int,
        *,
        variant: str,
        base_dir: str | Path,
        pair: str,
        resume: bool = True,
        progress_cb: Callable[[int, int, int], None] | None = None,
    ) -> list[CandleRow]:
        """Shared register logic for mark/index candle variants."""
        from controllers.backtesting.data_store import load_candles
        base_dir = Path(base_dir)
        resolution_key = f"{variant}_{timeframe}"
        catalog = DataCatalog(base_dir=base_dir)
        existing = catalog.find(self._exchange_id, pair, resolution_key)
        resume_from_ms = int(existing["end_ms"]) if resume and existing is not None else None

        download_fn = self.download_mark_candles if variant == "mark" else self.download_index_candles
        downloaded = download_fn(
            symbol, timeframe, since_ms, until_ms,
            resume_from_ms=resume_from_ms, progress_cb=progress_cb,
        )

        combined: list[CandleRow] = []
        out_path = resolve_data_path(self._exchange_id, pair, resolution_key, base_dir)
        if resume_from_ms and out_path.exists():
            combined.extend(load_candles(out_path))
        combined.extend(downloaded)

        deduped: dict[int, CandleRow] = {c.timestamp_ms: c for c in combined}
        rows = sorted(deduped.values(), key=lambda c: c.timestamp_ms)
        if not rows:
            return rows

        save_candles(rows, out_path)
        catalog.register(
            exchange=self._exchange_id,
            pair=pair,
            resolution=resolution_key,
            start_ms=rows[0].timestamp_ms,
            end_ms=rows[-1].timestamp_ms,
            row_count=len(rows),
            file_path=str(out_path),
            file_size_bytes=out_path.stat().st_size,
        )
        return rows

    def download_and_register_long_short_ratio(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
        until_ms: int,
        *,
        base_dir: str | Path,
        pair: str,
        resume: bool = True,
        progress_cb: Callable[[int, int, int], None] | None = None,
    ) -> list[LongShortRatioRow]:
        """Download LS ratio history, persist, and register in catalog."""
        base_dir = Path(base_dir)
        catalog = DataCatalog(base_dir=base_dir)
        existing = catalog.find(self._exchange_id, pair, "ls_ratio")
        resume_from_ms = int(existing["end_ms"]) if resume and existing is not None else None

        downloaded = self.download_long_short_ratio(
            symbol, timeframe, since_ms, until_ms,
            resume_from_ms=resume_from_ms, progress_cb=progress_cb,
        )

        combined: list[LongShortRatioRow] = []
        out_path = resolve_data_path(self._exchange_id, pair, "ls_ratio", base_dir)
        if resume_from_ms and out_path.exists():
            combined.extend(load_long_short_ratio(out_path))
        combined.extend(downloaded)

        deduped: dict[int, LongShortRatioRow] = {r.timestamp_ms: r for r in combined}
        rows = sorted(deduped.values(), key=lambda r: r.timestamp_ms)
        if not rows:
            return rows

        save_long_short_ratio(rows, out_path)
        catalog.register(
            exchange=self._exchange_id,
            pair=pair,
            resolution="ls_ratio",
            start_ms=rows[0].timestamp_ms,
            end_ms=rows[-1].timestamp_ms,
            row_count=len(rows),
            file_path=str(out_path),
            file_size_bytes=out_path.stat().st_size,
        )
        return rows

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _raw_bars_to_candle_rows(raw_bars: list[list]) -> list[CandleRow]:
        """Convert ccxt OHLCV lists to :class:`CandleRow` objects.

        Performs de-duplication (keeps first occurrence) and sorts by
        ``timestamp_ms`` ascending.
        """
        seen: set[int] = set()
        unique: list[list] = []
        for bar in raw_bars:
            ts: int = int(bar[0])
            if ts not in seen:
                seen.add(ts)
                unique.append(bar)
        unique.sort(key=lambda b: b[0])

        return [
            CandleRow(
                timestamp_ms=int(b[0]),
                open=Decimal(str(b[1])),
                high=Decimal(str(b[2])),
                low=Decimal(str(b[3])),
                close=Decimal(str(b[4])),
                volume=Decimal(str(b[5])),
            )
            for b in unique
        ]

    @staticmethod
    def _raw_trades_to_trade_rows(raw_trades: list[dict]) -> list[TradeRow]:
        """Convert ccxt trade dicts to :class:`TradeRow` objects, sorted by timestamp."""
        rows = [
            TradeRow(
                timestamp_ms=int(t["timestamp"]),
                side=str(t.get("side", "buy")),
                price=Decimal(str(t["price"])),
                size=Decimal(str(t["amount"])),
                trade_id=str(t.get("id") or ""),
            )
            for t in raw_trades
            if t.get("timestamp") is not None
        ]
        rows.sort(key=lambda r: r.timestamp_ms)
        return rows

    @staticmethod
    def _raw_funding_to_rows(raw_rates: list[dict]) -> list[FundingRow]:
        rows = [
            FundingRow(
                timestamp_ms=int(rate["timestamp"]),
                rate=Decimal(str(rate.get("fundingRate", rate.get("rate", "0")))),
            )
            for rate in raw_rates
            if rate.get("timestamp") is not None
        ]
        rows.sort(key=lambda row: row.timestamp_ms)
        deduped: dict[int, FundingRow] = {row.timestamp_ms: row for row in rows}
        return sorted(deduped.values(), key=lambda row: row.timestamp_ms)

    @staticmethod
    def _raw_ls_ratio_to_rows(raw: list[dict]) -> list[LongShortRatioRow]:
        rows = [
            LongShortRatioRow(
                timestamp_ms=int(r["timestamp"]),
                long_account_ratio=float(r.get("longAccount", 0.0)),
                short_account_ratio=float(r.get("shortAccount", 0.0)),
                long_short_ratio=float(r.get("longShortRatio", 0.0)),
            )
            for r in raw
            if r.get("timestamp") is not None
        ]
        rows.sort(key=lambda r: r.timestamp_ms)
        deduped: dict[int, LongShortRatioRow] = {r.timestamp_ms: r for r in rows}
        return sorted(deduped.values(), key=lambda r: r.timestamp_ms)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download historical backtest/replay data from CCXT exchanges")
    parser.add_argument("--exchange", required=True, help="CCXT exchange id (e.g. bitget, binance)")
    parser.add_argument("--pair", required=True, help="Trading pair (e.g. BTC/USDT:USDT)")
    parser.add_argument(
        "--types", default="candles",
        help="Comma-separated list: candles,mark,index,trades,funding,ls_ratio",
    )
    parser.add_argument(
        "--resolution", default="1m",
        help="Comma-separated candle resolutions (e.g. 1m,5m,15m,1h)",
    )
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    default_output = os.environ.get("BACKTEST_CATALOG_DIR", "").strip() or "data/historical"
    parser.add_argument("--output", default=default_output, help="Historical data base directory")
    args = parser.parse_args()

    since_ms = int(datetime.fromisoformat(args.start).replace(tzinfo=UTC).timestamp() * 1000)
    until_ms = int(datetime.fromisoformat(args.end).replace(tzinfo=UTC).timestamp() * 1000)
    pair = _catalog_pair_key(args.pair)
    types = {item.strip().lower() for item in args.types.split(",") if item.strip()}
    resolutions = [r.strip() for r in args.resolution.split(",") if r.strip()]

    downloader = DataDownloader(exchange_id=args.exchange)

    for resolution in resolutions:
        if "candles" in types:
            print(f"--- candles @ {resolution} ---")
            candles = downloader.download_and_register_candles(
                args.pair, resolution, since_ms, until_ms,
                base_dir=args.output, pair=pair,
            )
            if not candles:
                print(f"No candles downloaded for {resolution}.")

        if "mark" in types:
            print(f"--- mark candles @ {resolution} ---")
            rows = downloader.download_and_register_mark_candles(
                args.pair, resolution, since_ms, until_ms,
                base_dir=args.output, pair=pair,
            )
            if not rows:
                print(f"No mark candles downloaded for {resolution}.")

        if "index" in types:
            print(f"--- index candles @ {resolution} ---")
            rows = downloader.download_and_register_index_candles(
                args.pair, resolution, since_ms, until_ms,
                base_dir=args.output, pair=pair,
            )
            if not rows:
                print(f"No index candles downloaded for {resolution}.")

    if "trades" in types:
        print("--- trades ---")
        trades = downloader.download_and_register_trades(
            args.pair, since_ms, until_ms,
            base_dir=args.output, pair=pair,
        )
        if not trades:
            print("No trades downloaded.")

    if "funding" in types:
        print("--- funding ---")
        rates = downloader.download_and_register_funding(
            args.pair, since_ms, until_ms,
            base_dir=args.output, pair=pair,
        )
        if not rates:
            print("No funding rates downloaded.")

    if "ls_ratio" in types:
        print("--- ls_ratio ---")
        ls_rows = downloader.download_and_register_long_short_ratio(
            args.pair, "5m", since_ms, until_ms,
            base_dir=args.output, pair=pair,
        )
        if not ls_rows:
            print("No LS ratio data downloaded.")


if __name__ == "__main__":
    main()
