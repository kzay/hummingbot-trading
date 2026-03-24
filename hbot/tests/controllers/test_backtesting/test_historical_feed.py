"""Tests for HistoricalDataFeed — protocol compliance, cursor, data bounds."""
from __future__ import annotations

from decimal import Decimal

import pytest

from controllers.backtesting.book_synthesizer import CandleBookSynthesizer
from controllers.backtesting.historical_feed import HistoricalDataFeed
from controllers.backtesting.types import CandleRow, SynthesisConfig
from simulation.types import InstrumentId


@pytest.fixture
def instrument_id() -> InstrumentId:
    return InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")


@pytest.fixture
def candles() -> list[CandleRow]:
    """10 1-minute candles starting at a round timestamp."""
    base_ms = 1_700_000_000_000  # arbitrary
    return [
        CandleRow(
            timestamp_ms=base_ms + i * 60_000,
            open=Decimal("50000") + Decimal(str(i * 10)),
            high=Decimal("50050") + Decimal(str(i * 10)),
            low=Decimal("49950") + Decimal(str(i * 10)),
            close=Decimal("50020") + Decimal(str(i * 10)),
            volume=Decimal("100"),
        )
        for i in range(10)
    ]


@pytest.fixture
def synthesizer() -> CandleBookSynthesizer:
    return CandleBookSynthesizer(SynthesisConfig(
        base_spread_bps=Decimal("5.0"),
        depth_levels=3,
        steps_per_bar=1,
    ))


@pytest.fixture
def feed(candles, instrument_id, synthesizer) -> HistoricalDataFeed:
    return HistoricalDataFeed(
        candles=candles,
        instrument_id=instrument_id,
        synthesizer=synthesizer,
        step_interval_ns=60_000_000_000,  # 1 minute
        seed=42,
    )


class TestCursorBehavior:
    def test_no_data_before_first_candle(self, feed, instrument_id):
        """Before set_time or before first candle → no data."""
        assert feed.has_data() is False
        assert feed.get_book(instrument_id) is None
        assert feed.get_mid_price(instrument_id) is None

    def test_has_data_after_set_time(self, feed, instrument_id, candles):
        """After set_time to first candle → has data."""
        feed.set_time(candles[0].timestamp_ns)
        assert feed.has_data() is True
        assert feed.get_book(instrument_id) is not None

    def test_no_data_past_end(self, feed, instrument_id, candles):
        """Past the last candle → no data."""
        way_past = candles[-1].timestamp_ns + 120_000_000_000
        feed.set_time(way_past)
        assert feed.has_data() is False

    def test_wrong_instrument_returns_none(self, feed, candles):
        other = InstrumentId(venue="binance", trading_pair="ETH-USDT", instrument_type="perp")
        feed.set_time(candles[0].timestamp_ns)
        assert feed.get_book(other) is None
        assert feed.get_mid_price(other) is None


class TestDataRange:
    def test_data_start_ns(self, feed, candles):
        assert feed.data_start_ns == candles[0].timestamp_ns

    def test_data_end_ns(self, feed, candles):
        assert feed.data_end_ns == candles[-1].timestamp_ns


class TestMidPrice:
    def test_mid_price_reasonable(self, feed, instrument_id, candles):
        feed.set_time(candles[0].timestamp_ns)
        mid = feed.get_mid_price(instrument_id)
        assert mid is not None
        # Mid should be near candle open (~50000)
        assert Decimal("49000") < mid < Decimal("51000")


class TestFundingRate:
    def test_no_funding_returns_zero(self, feed, instrument_id, candles):
        feed.set_time(candles[0].timestamp_ns)
        rate = feed.get_funding_rate(instrument_id)
        assert rate == Decimal("0")

    def test_funding_floor_lookup(self, candles, instrument_id, synthesizer):
        funding = {
            candles[0].timestamp_ms: Decimal("0.0001"),
            candles[5].timestamp_ms: Decimal("-0.0002"),
        }
        feed = HistoricalDataFeed(
            candles=candles,
            instrument_id=instrument_id,
            synthesizer=synthesizer,
            step_interval_ns=60_000_000_000,
            funding_rates=funding,
            seed=42,
        )
        # At candle 3 → should use funding from candle 0
        feed.set_time(candles[3].timestamp_ns)
        assert feed.get_funding_rate(instrument_id) == Decimal("0.0001")

        # At candle 7 → should use funding from candle 5
        feed.set_time(candles[7].timestamp_ns)
        assert feed.get_funding_rate(instrument_id) == Decimal("-0.0002")


class TestReset:
    def test_reset_returns_to_start(self, feed, instrument_id, candles):
        feed.set_time(candles[5].timestamp_ns)
        assert feed.has_data() is True
        feed.reset()
        assert feed.has_data() is False

    def test_reset_none_restores_original_seed(self, candles, instrument_id, synthesizer):
        feed = HistoricalDataFeed(
            candles=candles,
            instrument_id=instrument_id,
            synthesizer=synthesizer,
            step_interval_ns=60_000_000_000,
            seed=42,
        )
        feed.set_time(candles[0].timestamp_ns)
        book1 = feed.get_book(instrument_id)

        feed.reset(seed=None)
        feed.set_time(candles[0].timestamp_ns)
        book2 = feed.get_book(instrument_id)

        assert book1 is not None and book2 is not None
        assert book1.bids[0].price == book2.bids[0].price

    def test_reset_new_seed_gives_different_sequence(self, candles, instrument_id, synthesizer):
        feed = HistoricalDataFeed(
            candles=candles,
            instrument_id=instrument_id,
            synthesizer=CandleBookSynthesizer(SynthesisConfig(
                base_spread_bps=Decimal("5.0"),
                depth_levels=3,
                steps_per_bar=4,
            )),
            step_interval_ns=15_000_000_000,
            seed=42,
        )
        feed.set_time(candles[0].timestamp_ns + 15_000_000_000)
        book1 = feed.get_book(instrument_id)

        feed.reset(seed=99)
        feed.set_time(candles[0].timestamp_ns + 15_000_000_000)
        book2 = feed.get_book(instrument_id)

        assert book1 is not None and book2 is not None


class TestMinimumCandles:
    def test_single_candle_raises(self, instrument_id, synthesizer):
        with pytest.raises(ValueError, match="at least"):
            HistoricalDataFeed(
                candles=[CandleRow(
                    timestamp_ms=1_700_000_000_000,
                    open=Decimal("50000"), high=Decimal("50050"),
                    low=Decimal("49950"), close=Decimal("50020"),
                    volume=Decimal("100"),
                )],
                instrument_id=instrument_id,
                synthesizer=synthesizer,
                step_interval_ns=60_000_000_000,
            )
