"""Tests for paper_engine_v2 types."""
import time
from decimal import Decimal

import pytest

from controllers.paper_engine_v2.types import (
    BookLevel, InstrumentId, InstrumentSpec,
    OrderBookSnapshot, OrderSide, OrderStatus,
    PaperOrder, PaperOrderType, PaperPosition, _ZERO,
)
from tests.controllers.test_paper_engine_v2.conftest import (
    BTC_PERP, BTC_SPOT, ETH_SPOT, make_book, make_spec,
)


class TestInstrumentId:
    def test_key_format(self):
        iid = InstrumentId("bitget", "BTC-USDT", "spot")
        assert iid.key == "bitget:BTC-USDT:spot"

    def test_base_quote_assets(self):
        iid = InstrumentId("bitget", "BTC-USDT", "spot")
        assert iid.base_asset == "BTC"
        assert iid.quote_asset == "USDT"

    def test_is_perp(self):
        assert BTC_PERP.is_perp is True
        assert BTC_SPOT.is_perp is False

    def test_frozen(self):
        iid = InstrumentId("x", "A-B", "spot")
        with pytest.raises((AttributeError, TypeError)):
            iid.venue = "y"  # type: ignore


class TestInstrumentSpec:
    def test_quantize_price_buy_rounds_down(self):
        spec = make_spec(BTC_SPOT, price_inc="0.01")
        result = spec.quantize_price(Decimal("100.005"), "buy")
        assert result == Decimal("100.00")

    def test_quantize_price_sell_rounds_up(self):
        spec = make_spec(BTC_SPOT, price_inc="0.01")
        result = spec.quantize_price(Decimal("100.001"), "sell")
        assert result == Decimal("100.01")

    def test_quantize_size_rounds_down(self):
        spec = make_spec(BTC_SPOT, size_inc="0.001")
        result = spec.quantize_size(Decimal("1.0009"))
        assert result == Decimal("1.000")

    def test_quantize_size_clamps_to_min(self):
        spec = make_spec(BTC_SPOT, size_inc="0.001", min_qty="0.01")
        result = spec.quantize_size(Decimal("0.0001"))
        assert result == Decimal("0.010")

    def test_validate_order_passes(self):
        spec = make_spec(BTC_SPOT, min_qty="0.001", min_notional="1", max_qty="100")
        assert spec.validate_order(Decimal("100"), Decimal("0.01")) is None

    def test_validate_order_below_min_qty(self):
        spec = make_spec(BTC_SPOT, min_qty="0.001")
        result = spec.validate_order(Decimal("100"), Decimal("0.0001"))
        assert result is not None
        assert "min" in result

    def test_validate_order_below_min_notional(self):
        spec = make_spec(BTC_SPOT, min_notional="10")
        result = spec.validate_order(Decimal("1"), Decimal("1"))  # notional = 1 < 10
        assert result is not None

    def test_validate_order_above_max_qty(self):
        spec = make_spec(BTC_SPOT, max_qty="10")
        result = spec.validate_order(Decimal("100"), Decimal("100"))
        assert result is not None

    def test_compute_margin_init_perp(self):
        spec = make_spec(BTC_PERP, margin_init="0.10")
        margin = spec.compute_margin_init(Decimal("1"), Decimal("100"), leverage=10)
        assert margin == Decimal("1.0")  # (100/10) * 0.10 = 1.0

    def test_compute_margin_init_spot_is_zero(self):
        spec = make_spec(BTC_SPOT)
        margin = spec.compute_margin_init(Decimal("1"), Decimal("100"), leverage=1)
        assert margin == _ZERO

    def test_spot_usdt_factory(self):
        spec = InstrumentSpec.spot_usdt("binance", "ETH-USDT")
        assert spec.instrument_id.is_perp is False
        assert spec.funding_interval_s == 0

    def test_perp_usdt_factory(self):
        spec = InstrumentSpec.perp_usdt("bitget", "BTC-USDT")
        assert spec.instrument_id.is_perp is True
        assert spec.funding_interval_s == 28800


class TestPaperPosition:
    def test_flat_constructor(self):
        pos = PaperPosition.flat(BTC_SPOT)
        assert pos.quantity == _ZERO
        assert pos.side == "flat"

    def test_side_long_short(self):
        pos = PaperPosition.flat(BTC_SPOT)
        pos.quantity = Decimal("1")
        assert pos.side == "long"
        pos.quantity = Decimal("-1")
        assert pos.side == "short"

    def test_net_pnl(self):
        pos = PaperPosition.flat(BTC_SPOT)
        pos.realized_pnl = Decimal("10")
        pos.unrealized_pnl = Decimal("5")
        pos.total_fees_paid = Decimal("2")
        pos.funding_paid = Decimal("1")
        assert pos.net_pnl == Decimal("12")  # 10+5-2-1

    def test_to_dict_from_dict_roundtrip(self):
        pos = PaperPosition.flat(BTC_SPOT)
        pos.quantity = Decimal("0.5")
        pos.avg_entry_price = Decimal("50000")
        pos.realized_pnl = Decimal("100")
        d = pos.to_dict()
        pos2 = PaperPosition.from_dict(d, BTC_SPOT)
        assert pos2.quantity == pos.quantity
        assert pos2.avg_entry_price == pos.avg_entry_price


class TestOrderBookSnapshot:
    def test_best_bid_ask(self):
        book = make_book("100.00", "100.05")
        assert book.best_bid.price == Decimal("100.00")
        assert book.best_ask.price == Decimal("100.05")

    def test_mid_price(self):
        book = make_book("100.00", "100.10")
        assert book.mid_price == Decimal("100.05")

    def test_spread_pct(self):
        book = make_book("100.00", "100.10")
        assert abs(book.spread_pct - Decimal("0.001")) < Decimal("0.00001")

    def test_empty_book_returns_none(self):
        book = OrderBookSnapshot(
            instrument_id=BTC_SPOT, bids=(), asks=(), timestamp_ns=0
        )
        assert book.best_bid is None
        assert book.mid_price is None
