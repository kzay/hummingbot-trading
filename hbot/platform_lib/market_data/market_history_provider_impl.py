from __future__ import annotations

import itertools
import logging
import os
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

try:
    import psycopg
except Exception:  # pragma: no cover - optional in lightweight test environments.
    psycopg = None  # type: ignore[assignment]

from platform_lib.market_data.market_history_provider import MarketHistoryProvider
from platform_lib.market_data.market_history_types import MarketBar, MarketBarKey, MarketHistoryStatus

if TYPE_CHECKING:
    from controllers.price_buffer import MinuteBar, PriceBuffer

BarReader = Callable[[MarketBarKey, int, int, int | None, bool], list[MarketBar]]
SampleReader = Callable[[MarketBarKey, int], list[tuple[float, Decimal]]]
NowMsReader = Callable[[], int]

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _to_ts_utc_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000.0, tz=UTC).isoformat()


class MarketHistoryProviderImpl(MarketHistoryProvider):
    def __init__(
        self,
        *,
        db_reader: BarReader | None = None,
        stream_reader: BarReader | None = None,
        rest_reader: BarReader | None = None,
        file_reader: BarReader | None = None,
        sample_reader: SampleReader | None = None,
        now_ms_reader: NowMsReader | None = None,
    ) -> None:
        self._db_reader = db_reader or self._read_bars_from_db
        self._stream_reader = stream_reader
        self._rest_reader = rest_reader
        self._file_reader = file_reader
        self._sample_reader = sample_reader
        self._now_ms_reader = now_ms_reader or _now_ms

    def get_bars(
        self,
        key: MarketBarKey,
        bar_interval_s: int = 60,
        limit: int = 300,
        end_time_ms: int | None = None,
        require_closed: bool = True,
    ) -> tuple[list[MarketBar], MarketHistoryStatus]:
        bounded_limit = max(1, int(limit))
        effective_end_ms = int(end_time_ms or self._now_ms_reader())
        source_chain: list[str] = []
        degraded_reason = ""

        db_bars = self._read_with(self._db_reader, key, 60, bounded_limit * max(1, int(bar_interval_s // 60)), effective_end_ms, True)
        bars = self._rollup(db_bars, bar_interval_s)
        if bars:
            source_chain.append("db_v2")

        stream_bars: list[MarketBar] = []
        if self._stream_reader is not None:
            stream_bars = self._read_with(self._stream_reader, key, bar_interval_s, bounded_limit, effective_end_ms, require_closed)
            if stream_bars:
                bars = self._merge_bars(bars, stream_bars)
                source_chain.append("stream_tail")

        prepared_bars = self._prepare_bars(
            bars,
            require_closed=require_closed,
            end_time_ms=effective_end_ms,
            limit=bounded_limit,
        )
        prepared_status = self._build_status(
            bars=prepared_bars,
            bar_interval_s=bar_interval_s,
            requested=bounded_limit,
            source_used="+".join(source_chain) if source_chain else "empty",
            degraded_reason=degraded_reason,
            now_ms=effective_end_ms,
        )

        if self._needs_fallback(prepared_status, bounded_limit):
            if self._rest_reader is not None:
                rest_bars = self._read_with(self._rest_reader, key, bar_interval_s, bounded_limit, effective_end_ms, require_closed)
                if rest_bars:
                    bars = self._merge_bars(rest_bars, bars)
                    if "rest_backfill" not in source_chain:
                        source_chain.append("rest_backfill")
                    degraded_reason = "rest_backfill"
            repaired_bars = self._prepare_bars(
                bars,
                require_closed=require_closed,
                end_time_ms=effective_end_ms,
                limit=bounded_limit,
            )
            repaired_status = self._build_status(
                bars=repaired_bars,
                bar_interval_s=bar_interval_s,
                requested=bounded_limit,
                source_used="+".join(source_chain) if source_chain else "empty",
                degraded_reason=degraded_reason,
                now_ms=effective_end_ms,
            )
            if self._needs_fallback(repaired_status, bounded_limit) and self._file_reader is not None:
                file_bars = self._read_with(self._file_reader, key, bar_interval_s, bounded_limit, effective_end_ms, require_closed)
                if file_bars:
                    bars = self._merge_bars(file_bars, bars)
                    if "minute_log" not in source_chain:
                        source_chain.append("minute_log")
                    degraded_reason = degraded_reason or "minute_log"
        bars = self._prepare_bars(
            bars,
            require_closed=require_closed,
            end_time_ms=effective_end_ms,
            limit=bounded_limit,
        )
        status = self._build_status(
            bars=bars,
            bar_interval_s=bar_interval_s,
            requested=bounded_limit,
            source_used="+".join(source_chain) if source_chain else "empty",
            degraded_reason=degraded_reason,
            now_ms=effective_end_ms,
        )
        return bars, status

    def get_status(
        self,
        key: MarketBarKey,
        bar_interval_s: int = 60,
    ) -> MarketHistoryStatus:
        _, status = self.get_bars(key, bar_interval_s=bar_interval_s, limit=1)
        return status

    def seed_price_buffer(
        self,
        buffer: PriceBuffer,
        key: MarketBarKey,
        bars_needed: int,
        now_ms: int,
    ) -> MarketHistoryStatus:
        from controllers.price_buffer import MinuteBar  # lazy: avoid circular layer dep

        bars, status = self.get_bars(
            key=key,
            bar_interval_s=60,
            limit=max(1, int(bars_needed)),
            end_time_ms=now_ms,
            require_closed=True,
        )
        if not bars:
            return status
        minute_bars = [
            MinuteBar(
                ts_minute=int(bar.bucket_start_ms // 1000),
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
            )
            for bar in bars
        ]
        buffer.seed_bars(minute_bars)
        degraded_reason = str(status.degraded_reason or "")
        if self._sample_reader is not None:
            samples = self._sample_reader(key, 120)
            if samples:
                buffer.seed_samples(samples)
            else:
                degraded_reason = degraded_reason or "sample_tail_missing"

        seeded_status = MarketHistoryStatus(
            status=status.status if not degraded_reason else "degraded",
            freshness_ms=status.freshness_ms,
            max_gap_s=status.max_gap_s,
            coverage_ratio=status.coverage_ratio,
            source_used=status.source_used,
            degraded_reason=degraded_reason,
            bars_returned=status.bars_returned,
            bars_requested=status.bars_requested,
        )
        return seeded_status

    def _read_with(
        self,
        reader: BarReader | None,
        key: MarketBarKey,
        bar_interval_s: int,
        limit: int,
        end_time_ms: int | None,
        require_closed: bool,
    ) -> list[MarketBar]:
        if reader is None:
            return []
        try:
            return list(reader(key, bar_interval_s, limit, end_time_ms, require_closed))
        except Exception:
            return []

    def _read_bars_from_db(
        self,
        key: MarketBarKey,
        bar_interval_s: int,
        limit: int,
        end_time_ms: int | None,
        require_closed: bool,
    ) -> list[MarketBar]:
        if psycopg is None:
            return []
        host = os.getenv("OPS_DB_HOST", "postgres")
        port = int(os.getenv("OPS_DB_PORT", "5432"))
        dbname = os.getenv("OPS_DB_NAME", "kzay_capital_ops")
        user = os.getenv("OPS_DB_USER", "hbot")
        password = os.getenv("OPS_DB_PASSWORD", "kzay_capital_dev_password")
        rows: list[MarketBar] = []
        conn = None
        try:
            conn = psycopg.connect(host=host, port=port, dbname=dbname, user=user, password=password, connect_timeout=3)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXTRACT(EPOCH FROM bucket_minute_utc) * 1000.0 AS bucket_ms,
                           open_price,
                           high_price,
                           low_price,
                           close_price,
                           bar_source
                    FROM market_bar_v2
                    WHERE connector_name = %(connector_name)s
                      AND trading_pair = ANY(%(pairs)s)
                      AND bar_source = %(bar_source)s
                      AND bar_interval_s = 60
                      AND (%(end_ts_utc)s IS NULL OR bucket_minute_utc <= %(end_ts_utc)s::timestamptz)
                    ORDER BY bucket_minute_utc DESC
                    LIMIT %(limit)s
                    """,
                    {
                        "connector_name": str(key.connector_name or "").strip(),
                        "pairs": self._pair_candidates(key.trading_pair),
                        "bar_source": str(key.bar_source or "quote_mid"),
                        "end_ts_utc": _to_ts_utc_from_ms(int(end_time_ms)) if end_time_ms else None,
                        "limit": max(1, int(limit)),
                    },
                )
                for row in reversed(list(cur.fetchall() or [])):
                    bucket_ms = int(float(row[0]))
                    open_price = _to_decimal(row[1])
                    high_price = _to_decimal(row[2])
                    low_price = _to_decimal(row[3])
                    close_price = _to_decimal(row[4])
                    bar_source = str(row[5] or key.bar_source)
                    if None in {open_price, high_price, low_price, close_price}:
                        continue
                    rows.append(
                        MarketBar(
                            bucket_start_ms=bucket_ms,
                            bar_interval_s=60,
                            open=open_price or _ZERO,
                            high=high_price or _ZERO,
                            low=low_price or _ZERO,
                            close=close_price or _ZERO,
                            is_closed=True,
                            bar_source=bar_source,
                        )
                    )
        except Exception:
            logger.warning("_read_bars_from_db query failed for %s", key, exc_info=True)
            return []
        finally:
            if conn:
                conn.close()
        return rows

    def _prepare_bars(
        self,
        bars: Sequence[MarketBar],
        *,
        require_closed: bool,
        end_time_ms: int,
        limit: int,
    ) -> list[MarketBar]:
        prepared = list(bars)
        if require_closed:
            prepared = [bar for bar in prepared if bool(bar.is_closed)]
        if end_time_ms > 0:
            prepared = [bar for bar in prepared if int(bar.bucket_start_ms) <= end_time_ms]
        return sorted(prepared, key=lambda item: int(item.bucket_start_ms))[-max(1, int(limit)) :]

    def _needs_fallback(self, status: MarketHistoryStatus, requested: int) -> bool:
        if int(status.bars_returned or 0) < min(5, max(1, int(requested))):
            return True
        return str(status.status or "empty") in {"empty", "stale", "gapped"}

    def _pair_candidates(self, trading_pair: str) -> list[str]:
        raw = str(trading_pair or "").strip().upper()
        if not raw:
            return []
        out = {raw, raw.replace("/", "-"), raw.replace("_", "-")}
        norm = raw.replace("/", "").replace("-", "").replace("_", "")
        out.add(norm)
        if len(norm) > 4:
            out.add(f"{norm[:-4]}-{norm[-4:]}")
        return sorted(item for item in out if item)

    def _rollup(self, bars: Sequence[MarketBar], bar_interval_s: int) -> list[MarketBar]:
        effective_interval_s = max(60, int(bar_interval_s or 60))
        if effective_interval_s <= 60:
            return list(sorted(bars, key=lambda item: int(item.bucket_start_ms)))
        bucket_ms = effective_interval_s * 1000
        grouped: dict[int, list[MarketBar]] = {}
        for bar in sorted(bars, key=lambda item: int(item.bucket_start_ms)):
            bucket_start_ms = (int(bar.bucket_start_ms) // bucket_ms) * bucket_ms
            grouped.setdefault(bucket_start_ms, []).append(bar)
        rolled: list[MarketBar] = []
        for bucket_start_ms in sorted(grouped.keys()):
            group = grouped[bucket_start_ms]
            if not group:
                continue
            rolled.append(
                MarketBar(
                    bucket_start_ms=bucket_start_ms,
                    bar_interval_s=effective_interval_s,
                    open=group[0].open,
                    high=max(bar.high for bar in group),
                    low=min(bar.low for bar in group),
                    close=group[-1].close,
                    volume_base=sum(((bar.volume_base or _ZERO) for bar in group), _ZERO) or None,
                    volume_quote=sum(((bar.volume_quote or _ZERO) for bar in group), _ZERO) or None,
                    is_closed=all(bool(bar.is_closed) for bar in group),
                    bar_source=group[-1].bar_source,
                )
            )
        return rolled

    def _merge_bars(self, base: Sequence[MarketBar], overlay: Sequence[MarketBar]) -> list[MarketBar]:
        merged: dict[int, MarketBar] = {int(bar.bucket_start_ms): bar for bar in base}
        for bar in overlay:
            merged[int(bar.bucket_start_ms)] = bar
        return [merged[key] for key in sorted(merged.keys())]

    def _build_status(
        self,
        *,
        bars: Sequence[MarketBar],
        bar_interval_s: int,
        requested: int,
        source_used: str,
        degraded_reason: str,
        now_ms: int,
    ) -> MarketHistoryStatus:
        effective_interval_s = max(60, int(bar_interval_s or 60))
        if not bars:
            return MarketHistoryStatus(
                status="empty",
                freshness_ms=max(0, int(now_ms)),
                max_gap_s=effective_interval_s * max(1, requested),
                coverage_ratio=0.0,
                source_used=source_used,
                degraded_reason=degraded_reason,
                bars_returned=0,
                bars_requested=requested,
            )
        ordered = sorted(bars, key=lambda item: int(item.bucket_start_ms))
        max_gap_s = 0
        for prev_bar, bar in itertools.pairwise(ordered):
            diff_s = max(0, int((int(bar.bucket_start_ms) - int(prev_bar.bucket_start_ms)) / 1000) - effective_interval_s)
            max_gap_s = max(max_gap_s, diff_s)
        expected = max(1, requested)
        coverage_ratio = min(1.0, float(len(ordered)) / float(expected))
        freshness_ms = max(0, int(now_ms) - (int(ordered[-1].bucket_start_ms) + effective_interval_s * 1000))
        status = "fresh"
        if coverage_ratio < 0.98 or max_gap_s > max(120, 2 * effective_interval_s):
            status = "gapped"
        elif freshness_ms > max(90_000, 2 * effective_interval_s * 1000):
            status = "stale"
        if degraded_reason:
            status = "degraded" if status == "fresh" else status
        return MarketHistoryStatus(
            status=status,
            freshness_ms=freshness_ms,
            max_gap_s=max_gap_s,
            coverage_ratio=coverage_ratio,
            source_used=source_used,
            degraded_reason=degraded_reason,
            bars_returned=len(ordered),
            bars_requested=requested,
        )


def market_bars_to_candles(bars: Iterable[MarketBar]) -> list[dict[str, float]]:
    candles: list[dict[str, float]] = []
    for bar in bars:
        candles.append(
            {
                "bucket_ms": int(bar.bucket_start_ms),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
            }
        )
    return candles
