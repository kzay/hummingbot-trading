from __future__ import annotations

from decimal import Decimal

from controllers.price_buffer import PriceBuffer
from platform_lib.market_data.market_history_provider_impl import MarketHistoryProviderImpl
from platform_lib.market_data.market_history_types import MarketBar, MarketBarKey


def _bar(bucket_ms: int, open_: str, high: str, low: str, close: str, source: str = "quote_mid") -> MarketBar:
    return MarketBar(
        bucket_start_ms=bucket_ms,
        bar_interval_s=60,
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        is_closed=True,
        bar_source=source,
    )


def test_provider_merges_db_and_stream_tail() -> None:
    provider = MarketHistoryProviderImpl(
        db_reader=lambda *_args: [
            _bar(60_000, "100", "101", "99", "100"),
            _bar(120_000, "100", "102", "100", "101"),
        ],
        stream_reader=lambda *_args: [
            _bar(180_000, "101", "103", "101", "102"),
        ],
        now_ms_reader=lambda: 210_000,
    )

    bars, status = provider.get_bars(
        MarketBarKey("bitget_perpetual", "BTC-USDT", "quote_mid"),
        bar_interval_s=60,
        limit=3,
    )

    assert [int(bar.bucket_start_ms) for bar in bars] == [60_000, 120_000, 180_000]
    assert status.source_used == "db_v2+stream_tail"
    assert status.status == "fresh"


def test_provider_marks_rest_fallback_as_degraded() -> None:
    provider = MarketHistoryProviderImpl(
        db_reader=lambda *_args: [],
        rest_reader=lambda *_args: [_bar(60_000, "100", "100", "100", "100", source="exchange_ohlcv")],
        now_ms_reader=lambda: 90_000,
    )

    bars, status = provider.get_bars(
        MarketBarKey("bitget_perpetual", "BTC-USDT", "quote_mid"),
        bar_interval_s=60,
        limit=5,
    )

    assert len(bars) == 1
    assert status.status == "gapped"
    assert status.degraded_reason == "rest_backfill"
    assert status.source_used == "rest_backfill"


def test_seed_price_buffer_loads_bars_without_degrading_when_sample_reader_unset() -> None:
    provider = MarketHistoryProviderImpl(
        db_reader=lambda *_args: [
            _bar(60_000, "100", "100", "100", "100"),
            _bar(120_000, "101", "101", "101", "101"),
            _bar(180_000, "102", "102", "102", "102"),
        ],
        now_ms_reader=lambda: 240_000,
    )
    buffer = PriceBuffer()

    status = provider.seed_price_buffer(
        buffer,
        MarketBarKey("bitget_perpetual", "BTC-USDT", "quote_mid"),
        bars_needed=3,
        now_ms=240_000,
    )

    assert len(buffer.bars) == 3
    assert buffer.latest_close() == Decimal("102")
    assert status.status == "fresh"
    assert status.degraded_reason == ""


def test_seed_price_buffer_marks_missing_sample_tail_when_reader_configured() -> None:
    provider = MarketHistoryProviderImpl(
        db_reader=lambda *_args: [
            _bar(60_000, "100", "100", "100", "100"),
            _bar(120_000, "101", "101", "101", "101"),
            _bar(180_000, "102", "102", "102", "102"),
        ],
        sample_reader=lambda *_args: [],
        now_ms_reader=lambda: 240_000,
    )
    buffer = PriceBuffer()

    status = provider.seed_price_buffer(
        buffer,
        MarketBarKey("bitget_perpetual", "BTC-USDT", "quote_mid"),
        bars_needed=3,
        now_ms=240_000,
    )

    assert len(buffer.bars) == 3
    assert status.status == "degraded"
    assert status.degraded_reason == "sample_tail_missing"


def test_provider_reader_exception_degrades_to_rest_fallback() -> None:
    def _broken_db(*_args):
        raise RuntimeError("db_down")

    provider = MarketHistoryProviderImpl(
        db_reader=_broken_db,
        rest_reader=lambda *_args: [_bar(60_000, "100", "101", "99", "100", source="exchange_ohlcv")],
        now_ms_reader=lambda: 90_000,
    )

    bars, status = provider.get_bars(
        MarketBarKey("bitget_perpetual", "BTC-USDT", "quote_mid"),
        bar_interval_s=60,
        limit=5,
    )

    assert len(bars) == 1
    assert status.source_used == "rest_backfill"
    assert status.degraded_reason == "rest_backfill"


def test_provider_marks_old_window_as_stale() -> None:
    provider = MarketHistoryProviderImpl(
        db_reader=lambda *_args: [
            _bar(60_000, "100", "100", "100", "100"),
            _bar(120_000, "101", "101", "101", "101"),
            _bar(180_000, "102", "102", "102", "102"),
        ],
        now_ms_reader=lambda: 600_000,
    )

    bars, status = provider.get_bars(
        MarketBarKey("bitget_perpetual", "BTC-USDT", "quote_mid"),
        bar_interval_s=60,
        limit=3,
    )

    assert len(bars) == 3
    assert status.status == "stale"
    assert status.freshness_ms > 120_000


def test_provider_uses_rest_fallback_to_repair_stale_history() -> None:
    provider = MarketHistoryProviderImpl(
        db_reader=lambda *_args: [
            _bar(60_000, "100", "100", "100", "100"),
            _bar(120_000, "101", "101", "101", "101"),
            _bar(180_000, "102", "102", "102", "102"),
        ],
        rest_reader=lambda *_args: [
            _bar(420_000, "103", "103", "103", "103", source="exchange_ohlcv"),
            _bar(480_000, "104", "104", "104", "104", source="exchange_ohlcv"),
            _bar(540_000, "105", "105", "105", "105", source="exchange_ohlcv"),
        ],
        now_ms_reader=lambda: 600_000,
    )

    bars, status = provider.get_bars(
        MarketBarKey("bitget_perpetual", "BTC-USDT", "quote_mid"),
        bar_interval_s=60,
        limit=3,
    )

    assert [int(bar.bucket_start_ms) for bar in bars] == [420_000, 480_000, 540_000]
    assert status.source_used == "db_v2+rest_backfill"
    assert status.degraded_reason == "rest_backfill"
    assert status.status == "degraded"


def test_seed_price_buffer_empty_is_noop() -> None:
    provider = MarketHistoryProviderImpl(
        db_reader=lambda *_args: [],
        now_ms_reader=lambda: 240_000,
    )
    buffer = PriceBuffer()

    status = provider.seed_price_buffer(
        buffer,
        MarketBarKey("bitget_perpetual", "BTC-USDT", "quote_mid"),
        bars_needed=3,
        now_ms=240_000,
    )

    assert len(buffer.bars) == 0
    assert status.status == "empty"
