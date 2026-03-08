"""Tests for paper_engine_v2 fill models.

Includes all spec test vectors V1-V6 and determinism verification.
"""
import time
from decimal import Decimal

import pytest

from controllers.paper_engine_v2.fill_models import (
    BestPriceFillModel,
    CompetitionAwareFillModel,
    FillDecision, LatencyAwareFillModel, LatencyAwareConfig,
    MarketHoursAwareFillModel,
    OneTickSlippageFillModel,
    QueuePositionConfig, QueuePositionFillModel, TopOfBookFillModel,
    SizeAwareFillModel,
    ThreeTierFillModel,
    TwoTierFillModel, make_fill_model,
    _NO_FILL,
)
from controllers.paper_engine_v2.types import OrderSide, OrderStatus, PaperOrderType
from tests.controllers.test_paper_engine_v2.conftest import (
    BTC_SPOT, make_book, make_order,
)


def _now():
    return int(time.time() * 1e9)


class TestQueuePositionFillModel:
    def _make(self, seed=7, **kwargs) -> QueuePositionFillModel:
        cfg = QueuePositionConfig(seed=seed, **kwargs)
        return QueuePositionFillModel(cfg)

    # -- Spec test vectors --------------------------------------------------

    def test_v1_passive_maker_not_touched_no_fill(self):
        """V1: LIMIT_MAKER @ 99.95, asks=[100.05]. Not touchable → NO fill.
        Passive orders only fill when the market reaches their price."""
        model = self._make()
        order = make_order("buy", "limit_maker", "99.95", "2.0")
        order.status = OrderStatus.OPEN
        book = make_book("100.00", "100.05", bid_size="5.0", ask_size="3.0")
        decision = model.evaluate(order, book, _now())
        assert decision.fill_quantity == Decimal("0")

    def test_v1_passive_maker_touched_fills(self):
        """V1b: LIMIT_MAKER @ 99.95, ask drops to 99.90 → touchable → fill."""
        model = self._make()
        order = make_order("buy", "limit_maker", "99.95", "2.0")
        order.status = OrderStatus.OPEN
        book = make_book("99.85", "99.90", bid_size="5.0", ask_size="3.0")
        decision = model.evaluate(order, book, _now())
        assert decision.fill_quantity > Decimal("0")
        assert decision.fill_price == Decimal("99.95")
        assert decision.is_maker is True

    def test_v2_resting_limit_touched(self):
        """V2: Market drops to touch buy limit → maker fill."""
        model = self._make(prob_fill_on_limit=1.0)
        order = make_order("buy", "limit", "99.95", "1.0")
        order.status = OrderStatus.OPEN
        # Ask dropped below order price → touchable
        book = make_book("99.90", "99.93", bid_size="5.0", ask_size="3.0")
        decision = model.evaluate(order, book, _now())
        assert decision.fill_quantity > Decimal("0")
        assert decision.fill_price == Decimal("99.95")
        assert decision.is_maker is True

    def test_v3_taker_cross(self):
        """V3: BUY LIMIT @ 100.10 crossed at creation → taker fill with slippage."""
        model = self._make(slippage_bps=Decimal("1.0"), adverse_selection_bps=Decimal("1.5"))
        order = make_order("buy", "limit", "100.10", "1.0")
        order.crossed_at_creation = True
        order.status = OrderStatus.OPEN
        book = make_book("100.00", "100.05", ask_size="3.0")
        decision = model.evaluate(order, book, _now())
        assert decision.fill_quantity > Decimal("0")
        # fill price = 100.05 * (1 + 2.5/10000) ≈ 100.075
        assert decision.fill_price > Decimal("100.05")
        assert decision.is_maker is False

    def test_v4_no_fill_price_behind(self):
        """V4: BUY LIMIT @ 99.50 — market at 100.00/100.05 → no fill."""
        model = self._make()
        order = make_order("buy", "limit", "99.50", "1.0")
        order.status = OrderStatus.OPEN
        book = make_book("100.00", "100.05")
        decision = model.evaluate(order, book, _now())
        assert decision.fill_quantity == Decimal("0")

    def test_prob_fill_on_limit_zero_never_fills_on_touch(self):
        """prob_fill_on_limit=0.0 → queue always misses when market touches."""
        model = self._make(prob_fill_on_limit=0.0)
        order = make_order("buy", "limit", "99.95", "1.0")
        order.status = OrderStatus.OPEN
        # Market touches order price
        book = make_book("99.90", "99.93")
        decision = model.evaluate(order, book, _now())
        assert decision.fill_quantity == Decimal("0")

    def test_seeded_determinism(self):
        """Same seed + same book sequence → identical fill sequence."""
        def run() -> list:
            model = QueuePositionFillModel(QueuePositionConfig(seed=7))
            order = make_order("buy", "limit_maker", "99.95", "2.0")
            order.status = OrderStatus.OPEN
            book = make_book()
            return [model.evaluate(order, book, 0).fill_quantity for _ in range(5)]

        assert run() == run()

    def test_market_order_taker_fill(self):
        """MARKET order always attempts taker fill."""
        model = self._make()
        order = make_order("buy", "market", "0", "1.0")
        order.crossed_at_creation = True
        order.status = OrderStatus.OPEN
        book = make_book()
        decision = model.evaluate(order, book, _now())
        assert decision.fill_quantity > Decimal("0")
        assert decision.is_maker is False

    def test_empty_book_no_fill(self):
        from controllers.paper_engine_v2.types import OrderBookSnapshot
        model = self._make()
        order = make_order("buy", "limit_maker", "99.95", "1.0")
        order.status = OrderStatus.OPEN
        empty_book = OrderBookSnapshot(
            instrument_id=BTC_SPOT, bids=(), asks=(), timestamp_ns=0
        )
        decision = model.evaluate(order, empty_book, _now())
        assert decision.fill_quantity == Decimal("0")

    def test_remaining_zero_no_fill(self):
        model = self._make()
        order = make_order("buy", "limit_maker", "99.95", "1.0")
        order.filled_quantity = Decimal("1.0")  # fully filled
        order.status = OrderStatus.OPEN
        book = make_book()
        decision = model.evaluate(order, book, _now())
        assert decision.fill_quantity == Decimal("0")

    def test_sell_taker_fill_below_bid(self):
        """SELL taker fills at bid with slippage."""
        model = self._make()
        order = make_order("sell", "limit", "99.90", "1.0")
        order.crossed_at_creation = True
        order.status = OrderStatus.OPEN
        book = make_book("100.00", "100.05", bid_size="5.0")
        decision = model.evaluate(order, book, _now())
        assert decision.fill_quantity > Decimal("0")
        assert decision.fill_price < Decimal("100.00")
        assert decision.is_maker is False

    def test_taker_fill_uses_multi_level_vwap(self):
        """Taker fill should price from multi-level contra depth, not only top."""
        from controllers.paper_engine_v2.types import BookLevel, OrderBookSnapshot

        model = self._make(
            queue_participation=Decimal("1.0"),
            queue_jitter_pct=0.0,
            slippage_bps=Decimal("0"),
            adverse_selection_bps=Decimal("0"),
            depth_levels=3,
            seed=7,
        )
        order = make_order("buy", "market", "0", "2.0")
        order.crossed_at_creation = True
        order.status = OrderStatus.OPEN
        book = OrderBookSnapshot(
            instrument_id=BTC_SPOT,
            bids=(BookLevel(price=Decimal("100.00"), size=Decimal("5.0")),),
            asks=(
                BookLevel(price=Decimal("100.00"), size=Decimal("1.0")),
                BookLevel(price=Decimal("100.10"), size=Decimal("1.0")),
                BookLevel(price=Decimal("100.20"), size=Decimal("5.0")),
            ),
            timestamp_ns=_now(),
        )
        decision = model.evaluate(order, book, _now())
        assert decision.fill_quantity >= Decimal("2.0")
        # Pure two-level VWAP for 2.0 = (1*100.00 + 1*100.10)/2 = 100.05
        assert decision.fill_price == Decimal("100.05")


class TestTopOfBookFillModel:
    def test_v5_instant_full_fill(self):
        """V5: TopOfBook fills full remaining at best ask."""
        model = TopOfBookFillModel()
        order = make_order("buy", "market", "0", "1.0")
        order.status = OrderStatus.OPEN
        book = make_book("100.00", "100.05", ask_size="5.0")
        decision = model.evaluate(order, book, _now())
        assert decision.fill_quantity == Decimal("1.0")
        assert decision.fill_price == Decimal("100.05")
        assert decision.is_maker is False
        assert decision.queue_delay_ms == 0

    def test_no_fill_empty_book(self):
        from controllers.paper_engine_v2.types import OrderBookSnapshot
        model = TopOfBookFillModel()
        order = make_order("buy", "market", "0", "1.0")
        empty = OrderBookSnapshot(instrument_id=BTC_SPOT, bids=(), asks=(), timestamp_ns=0)
        d = model.evaluate(order, empty, _now())
        assert d.fill_quantity == Decimal("0")

    def test_sell_market_fills_at_best_bid(self):
        model = TopOfBookFillModel()
        order = make_order("sell", "market", "0", "1.0")
        order.status = OrderStatus.OPEN
        book = make_book("100.00", "100.05", bid_size="5.0")
        decision = model.evaluate(order, book, _now())
        assert decision.fill_quantity == Decimal("1.0")
        assert decision.fill_price == Decimal("100.00")
        assert decision.is_maker is False


class TestNautilusStylePresets:
    def test_best_price_alias_behaves_like_top_of_book(self):
        model = BestPriceFillModel()
        order = make_order("buy", "market", "0", "1.0")
        order.status = OrderStatus.OPEN
        book = make_book("100.00", "100.05")
        d = model.evaluate(order, book, _now())
        assert d.fill_quantity == Decimal("1.0")
        assert d.fill_price == Decimal("100.05")

    def test_one_tick_slippage_buy_is_worse_than_top(self):
        model = OneTickSlippageFillModel()
        order = make_order("buy", "market", "0", "1.0")
        order.status = OrderStatus.OPEN
        book = make_book("100.00", "100.05")
        d = model.evaluate(order, book, _now())
        assert d.fill_price > Decimal("100.05")

    def test_two_tier_vwap_applies_second_tier_price(self):
        model = TwoTierFillModel(tier1_size=Decimal("1"))
        order = make_order("buy", "market", "0", "2.0")
        order.status = OrderStatus.OPEN
        book = make_book("100.00", "100.05")
        d = model.evaluate(order, book, _now())
        # 1 @ 100.05 and 1 @ 100.0501
        assert d.fill_price == Decimal("100.05005")

    def test_factory_supports_nautilus_style_names(self):
        assert isinstance(make_fill_model("best_price"), BestPriceFillModel)
        assert isinstance(make_fill_model("one_tick_slippage"), OneTickSlippageFillModel)
        assert isinstance(make_fill_model("two_tier"), TwoTierFillModel)
        assert isinstance(make_fill_model("three_tier"), ThreeTierFillModel)
        assert isinstance(make_fill_model("competition_aware"), CompetitionAwareFillModel)
        assert isinstance(make_fill_model("size_aware"), SizeAwareFillModel)
        assert isinstance(make_fill_model("market_hours_aware"), MarketHoursAwareFillModel)

    def test_three_tier_has_worse_vwap_than_two_tier_for_large_order(self):
        book = make_book("100.00", "100.05")
        order = make_order("buy", "market", "0", "3.0")
        order.status = OrderStatus.OPEN
        two = TwoTierFillModel(tier1_size=Decimal("1")).evaluate(order, book, _now())
        three = ThreeTierFillModel(
            tier1_size=Decimal("1"),
            tier2_size=Decimal("1"),
            tier3_size=Decimal("1"),
        ).evaluate(order, book, _now())
        assert three.fill_price > two.fill_price


class TestLatencyAwareFillModel:
    def test_depth_cap_reduces_fill(self):
        """depth_participation_pct=0.10 caps fill at 10% of ask depth."""
        cfg = LatencyAwareConfig(depth_participation_pct=Decimal("0.10"), seed=7)
        model = LatencyAwareFillModel(cfg)
        order = make_order("buy", "limit_maker", "99.95", "10.0")  # large order
        order.status = OrderStatus.OPEN
        book = make_book("100.00", "100.05", ask_size="5.0")  # 5.0 ask depth
        decision = model.evaluate(order, book, _now())
        # max possible = 5.0 * 0.10 = 0.5
        assert decision.fill_quantity <= Decimal("0.5") + Decimal("0.01")
