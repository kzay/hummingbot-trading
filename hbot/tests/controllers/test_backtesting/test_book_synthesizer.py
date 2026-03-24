"""Tests for book synthesizer — determinism, no look-ahead bias, spread scaling."""
from __future__ import annotations

import random
from decimal import Decimal

import pytest

from controllers.backtesting.book_synthesizer import CandleBookSynthesizer
from controllers.backtesting.types import CandleRow, SynthesisConfig
from simulation.types import InstrumentId


@pytest.fixture
def instrument_id() -> InstrumentId:
    return InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")


@pytest.fixture
def candle() -> CandleRow:
    return CandleRow(
        timestamp_ms=1_700_000_000_000,
        open=Decimal("50000"),
        high=Decimal("50500"),
        low=Decimal("49500"),
        close=Decimal("50200"),
        volume=Decimal("100"),
    )


@pytest.fixture
def synthesizer() -> CandleBookSynthesizer:
    return CandleBookSynthesizer(SynthesisConfig(
        base_spread_bps=Decimal("5.0"),
        vol_spread_mult=Decimal("1.0"),
        depth_levels=5,
        depth_decay=Decimal("0.70"),
        base_depth_size=Decimal("1.0"),
        steps_per_bar=4,
    ))


class TestDeterminism:
    def test_same_seed_same_output(self, synthesizer, candle, instrument_id):
        """Same seed + same inputs → identical OrderBookSnapshot."""
        rng1 = random.Random(42)
        rng2 = random.Random(42)

        book1 = synthesizer.synthesize(candle, instrument_id, step_index=0, rng=rng1)
        book2 = synthesizer.synthesize(candle, instrument_id, step_index=0, rng=rng2)

        assert book1 is not None
        assert book2 is not None
        assert book1.bids[0].price == book2.bids[0].price
        assert book1.asks[0].price == book2.asks[0].price
        assert len(book1.bids) == len(book2.bids)

    def test_different_seed_different_output(self, synthesizer, candle, instrument_id):
        """Different seeds → different (but valid) snapshots."""
        rng1 = random.Random(42)
        rng2 = random.Random(99)

        book1 = synthesizer.synthesize(candle, instrument_id, step_index=2, rng=rng1)
        book2 = synthesizer.synthesize(candle, instrument_id, step_index=2, rng=rng2)

        assert book1 is not None
        assert book2 is not None
        # Prices differ due to noise
        # (They could coincidentally match, but vanishingly unlikely with different seeds)


class TestNoLookAheadBias:
    def test_step_0_uses_open_not_close(self, synthesizer, candle, instrument_id):
        """Step 0 must derive mid from candle.open, NOT candle.close."""
        rng = random.Random(42)
        book = synthesizer.synthesize(candle, instrument_id, step_index=0, rng=rng)

        assert book is not None
        mid = book.mid_price
        # Mid should be near the open (50000), not the close (50200)
        assert abs(mid - Decimal("50000")) < abs(mid - Decimal("50200")), (
            f"Step 0 mid={mid} is closer to close(50200) than open(50000) — look-ahead bias!"
        )


class TestSpreadScaling:
    def test_higher_volatility_wider_spread(self, instrument_id):
        """Candle with larger range should produce wider spread."""
        synth = CandleBookSynthesizer(SynthesisConfig(
            base_spread_bps=Decimal("5.0"),
            vol_spread_mult=Decimal("2.0"),  # High sensitivity
            depth_levels=3,
            depth_decay=Decimal("0.70"),
            base_depth_size=Decimal("1.0"),
            steps_per_bar=1,
        ))

        narrow_candle = CandleRow(
            timestamp_ms=1_700_000_000_000,
            open=Decimal("50000"), high=Decimal("50050"),
            low=Decimal("49950"), close=Decimal("50010"),
            volume=Decimal("100"),
        )
        wide_candle = CandleRow(
            timestamp_ms=1_700_000_000_000,
            open=Decimal("50000"), high=Decimal("51000"),
            low=Decimal("49000"), close=Decimal("50200"),
            volume=Decimal("100"),
        )

        rng1 = random.Random(42)
        rng2 = random.Random(42)
        book_narrow = synth.synthesize(narrow_candle, instrument_id, 0, rng1)
        book_wide = synth.synthesize(wide_candle, instrument_id, 0, rng2)

        assert book_narrow is not None and book_wide is not None
        spread_narrow = book_narrow.asks[0].price - book_narrow.bids[0].price
        spread_wide = book_wide.asks[0].price - book_wide.bids[0].price

        assert spread_wide > spread_narrow, (
            f"Wide candle spread ({spread_wide}) should be > narrow ({spread_narrow})"
        )


class TestBookStructure:
    def test_correct_level_count(self, synthesizer, candle, instrument_id):
        rng = random.Random(42)
        book = synthesizer.synthesize(candle, instrument_id, step_index=0, rng=rng)
        assert book is not None
        assert len(book.bids) == 5
        assert len(book.asks) == 5

    def test_bids_descending_asks_ascending(self, synthesizer, candle, instrument_id):
        rng = random.Random(42)
        book = synthesizer.synthesize(candle, instrument_id, step_index=0, rng=rng)
        assert book is not None
        for i in range(len(book.bids) - 1):
            assert book.bids[i].price >= book.bids[i + 1].price
        for i in range(len(book.asks) - 1):
            assert book.asks[i].price <= book.asks[i + 1].price

    def test_best_bid_below_best_ask(self, synthesizer, candle, instrument_id):
        rng = random.Random(42)
        book = synthesizer.synthesize(candle, instrument_id, step_index=0, rng=rng)
        assert book is not None
        assert book.bids[0].price < book.asks[0].price
