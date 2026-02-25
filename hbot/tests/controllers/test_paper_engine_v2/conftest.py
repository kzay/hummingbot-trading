"""Shared fixtures for Paper Engine v2 tests."""
import time
from decimal import Decimal
import pytest

from controllers.paper_engine_v2.types import (
    BookLevel, InstrumentId, InstrumentSpec, OrderBookSnapshot,
    OrderSide, PaperOrder, PaperOrderType, OrderStatus, _ZERO,
)
from controllers.paper_engine_v2.data_feeds import StaticDataFeed


BTC_SPOT = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="spot")
BTC_PERP = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")
ETH_SPOT = InstrumentId(venue="binance", trading_pair="ETH-USDT", instrument_type="spot")


def make_spec(iid: InstrumentId, price_inc="0.01", size_inc="0.0001",
              min_qty="0.0001", min_notional="1", max_qty="1000",
              maker="0.0002", taker="0.0006",
              margin_init="0.10", margin_maint="0.05", leverage_max=20) -> InstrumentSpec:
    return InstrumentSpec(
        instrument_id=iid,
        price_precision=2, size_precision=4,
        price_increment=Decimal(price_inc), size_increment=Decimal(size_inc),
        min_quantity=Decimal(min_qty), min_notional=Decimal(min_notional),
        max_quantity=Decimal(max_qty),
        maker_fee_rate=Decimal(maker), taker_fee_rate=Decimal(taker),
        margin_init=Decimal(margin_init), margin_maint=Decimal(margin_maint),
        leverage_max=leverage_max,
        funding_interval_s=28800 if iid.is_perp else 0,
    )


def make_book(bid_price="100.00", ask_price="100.05",
              bid_size="5.0", ask_size="3.0",
              iid: InstrumentId = None) -> OrderBookSnapshot:
    if iid is None:
        iid = BTC_SPOT
    return OrderBookSnapshot(
        instrument_id=iid,
        bids=(BookLevel(price=Decimal(bid_price), size=Decimal(bid_size)),),
        asks=(BookLevel(price=Decimal(ask_price), size=Decimal(ask_size)),),
        timestamp_ns=int(time.time() * 1e9),
    )


def make_order(side="buy", order_type="limit_maker", price="99.95", qty="1.0",
               iid: InstrumentId = None, source_bot="test") -> PaperOrder:
    if iid is None:
        iid = BTC_SPOT
    now_ns = int(time.time() * 1e9)
    side_e = OrderSide.BUY if side == "buy" else OrderSide.SELL
    type_map = {
        "limit": PaperOrderType.LIMIT,
        "limit_maker": PaperOrderType.LIMIT_MAKER,
        "market": PaperOrderType.MARKET,
    }
    return PaperOrder(
        order_id=f"test_{int(now_ns % 1e9)}",
        instrument_id=iid,
        side=side_e,
        order_type=type_map[order_type],
        price=Decimal(price),
        quantity=Decimal(qty),
        status=OrderStatus.OPEN,
        created_at_ns=now_ns,
        updated_at_ns=now_ns,
        source_bot=source_bot,
    )


@pytest.fixture
def spot_spec():
    return make_spec(BTC_SPOT)

@pytest.fixture
def perp_spec():
    return make_spec(BTC_PERP)

@pytest.fixture
def standard_book():
    return make_book()

@pytest.fixture
def static_feed(standard_book):
    return StaticDataFeed(book=standard_book)
