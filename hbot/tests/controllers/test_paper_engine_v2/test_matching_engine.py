"""Tests for paper_engine_v2 OrderMatchingEngine.

Covers: accept, reject (balance/spec/risk), fill lifecycle, cancel,
time gate, max fills, latency queue, LIMIT_MAKER cross rejection.
"""
import time
from decimal import Decimal

import pytest

from controllers.paper_engine_v2.fee_models import MakerTakerFeeModel
from controllers.paper_engine_v2.fill_models import QueuePositionFillModel, TopOfBookFillModel
from controllers.paper_engine_v2.fill_models import QueuePositionConfig
from controllers.paper_engine_v2.latency_model import NO_LATENCY, LatencyModel
from controllers.paper_engine_v2.matching_engine import EngineConfig, OrderMatchingEngine
from controllers.paper_engine_v2.portfolio import PaperPortfolio, PortfolioConfig
from controllers.paper_engine_v2.types import (
    EngineError, OrderAccepted, OrderCanceled, OrderFilled,
    OrderRejected, OrderSide, OrderStatus, PositionChanged,
    PaperOrderType,
)
from tests.controllers.test_paper_engine_v2.conftest import (
    BTC_PERP, BTC_SPOT, ETH_SPOT, make_book, make_order, make_spec,
)


def _now():
    return int(time.time() * 1e9)


def make_engine(
    iid=None, balances=None, fill_model=None, latency=None,
    max_fills=8, reject_crossed=True, leverage=1,
) -> OrderMatchingEngine:
    if iid is None:
        iid = BTC_SPOT
    spec = make_spec(iid)
    portfolio = PaperPortfolio(
        balances or {"USDT": Decimal("10000"), "BTC": Decimal("1")},
        PortfolioConfig(),
    )
    return OrderMatchingEngine(
        instrument_id=iid,
        instrument_spec=spec,
        portfolio=portfolio,
        fill_model=fill_model or QueuePositionFillModel(),
        fee_model=MakerTakerFeeModel(Decimal("0.0002"), Decimal("0.0006")),
        latency_model=latency or NO_LATENCY,
        config=EngineConfig(max_fills_per_order=max_fills, reject_crossed_maker=reject_crossed),
        leverage=leverage,
    )


class TestOrderAcceptance:
    def test_accept_valid_limit_maker(self):
        engine = make_engine()
        engine.update_book(make_book())
        order = make_order("buy", "limit_maker", "99.95", "0.1")
        event = engine.submit_order(order, _now())
        assert isinstance(event, OrderAccepted)
        assert order.status == OrderStatus.OPEN

    def test_accept_valid_limit(self):
        engine = make_engine()
        engine.update_book(make_book())
        order = make_order("buy", "limit", "99.95", "0.1")
        event = engine.submit_order(order, _now())
        assert isinstance(event, OrderAccepted)

    def test_reject_insufficient_balance(self):
        engine = make_engine(balances={"USDT": Decimal("0"), "BTC": Decimal("0")})
        engine.update_book(make_book())
        order = make_order("buy", "limit_maker", "99.95", "1.0")
        event = engine.submit_order(order, _now())
        assert isinstance(event, OrderRejected)
        assert "insufficient_balance" in event.reason

    def test_reject_below_min_quantity(self):
        engine = make_engine()
        engine.update_book(make_book())
        order = make_order("buy", "limit_maker", "99.95", "0.0000001")  # below min
        event = engine.submit_order(order, _now())
        assert isinstance(event, OrderRejected)

    def test_reject_limit_maker_crossing_spread(self):
        engine = make_engine(reject_crossed=True)
        engine.update_book(make_book("100.00", "100.05"))
        # BUY @ 100.10 crosses best ask of 100.05
        order = make_order("buy", "limit_maker", "100.10", "0.1")
        event = engine.submit_order(order, _now())
        assert isinstance(event, OrderRejected)
        assert "limit_maker_would_cross" in event.reason

    def test_accept_limit_maker_not_crossing(self):
        engine = make_engine()
        engine.update_book(make_book("100.00", "100.05"))
        order = make_order("buy", "limit_maker", "99.95", "0.1")
        event = engine.submit_order(order, _now())
        assert isinstance(event, OrderAccepted)

    def test_quantizes_price_on_submit(self):
        engine = make_engine()
        engine.update_book(make_book())
        order = make_order("buy", "limit_maker", "99.953", "0.1")
        engine.submit_order(order, _now())
        # price_increment=0.01, BUY rounds down
        assert order.price == Decimal("99.95")


class TestFillLifecycle:
    def test_fill_generates_order_filled_event(self):
        engine = make_engine(fill_model=TopOfBookFillModel())
        engine.update_book(make_book())
        order = make_order("buy", "limit_maker", "99.95", "0.1")
        engine.submit_order(order, _now())
        events = engine.tick(_now())
        filled_events = [e for e in events if isinstance(e, OrderFilled)]
        assert len(filled_events) > 0

    def test_fill_generates_position_changed_event(self):
        engine = make_engine(fill_model=TopOfBookFillModel())
        engine.update_book(make_book())
        order = make_order("buy", "limit_maker", "99.95", "0.1")
        engine.submit_order(order, _now())
        events = engine.tick(_now())
        pos_events = [e for e in events if isinstance(e, PositionChanged)]
        assert len(pos_events) > 0

    def test_order_fully_filled_removed_from_open(self):
        engine = make_engine(fill_model=TopOfBookFillModel())
        engine.update_book(make_book())
        order = make_order("buy", "market", "100.10", "0.1")
        order.crossed_at_creation = True
        engine.submit_order(order, _now())
        engine.tick(_now())
        assert len(engine.open_orders()) == 0

    def test_reserve_shrinks_after_partial_fill(self):
        """After a partial fill, the engine should not keep the full original reserve."""
        fill_model = QueuePositionFillModel(QueuePositionConfig(
            queue_participation=Decimal("0.5"),
            min_partial_fill_ratio=Decimal("0.5"),
            max_partial_fill_ratio=Decimal("0.5"),
            prob_fill_on_limit=1.0,
            prob_slippage=0.0,
            seed=7,
        ))
        engine = make_engine(
            balances={"USDT": Decimal("1000"), "BTC": Decimal("0")},
            fill_model=fill_model,
        )
        # Small top-of-book depth forces partial taker fills.
        engine.update_book(make_book(ask_price="100.00", ask_size="1.0"))
        order = make_order("buy", "market", "100.00", "10.0")
        event = engine.submit_order(order, _now())
        assert isinstance(event, OrderAccepted)
        reserved_initial = order._reserved_amount
        assert reserved_initial == Decimal("1000.00") or reserved_initial == Decimal("1000")  # qty * price

        engine.tick(_now())
        assert order.fill_count >= 1
        assert order._reserved_amount < reserved_initial

    def test_max_fills_per_order_respected(self):
        engine = make_engine(fill_model=QueuePositionFillModel(), max_fills=2)
        engine.update_book(make_book())
        order = make_order("buy", "limit_maker", "99.95", "10.0")
        now = _now()
        engine.submit_order(order, now)
        # tick many times with increasing timestamp
        for i in range(10):
            engine.tick(now + i * 200_000_000)  # 200ms apart
        assert order.fill_count <= 2


class TestCancellation:
    def test_cancel_returns_event(self):
        engine = make_engine()
        engine.update_book(make_book())
        order = make_order("buy", "limit_maker", "99.95", "0.1")
        engine.submit_order(order, _now())
        event = engine.cancel_order(order.order_id, _now())
        assert isinstance(event, OrderCanceled)

    def test_cancel_releases_reserve(self):
        engine = make_engine(balances={"USDT": Decimal("100"), "BTC": Decimal("0")})
        engine.update_book(make_book())
        order = make_order("buy", "limit_maker", "99.95", "0.1")
        engine.submit_order(order, _now())
        # After cancel, reserve should be released
        engine.cancel_order(order.order_id, _now())
        assert engine._portfolio.available("USDT") == Decimal("100")

    def test_cancel_all(self):
        engine = make_engine()
        engine.update_book(make_book())
        for i in range(3):
            order = make_order("buy", "limit_maker", str(99 - i), "0.1")
            order.order_id = f"order_{i}"
            engine.submit_order(order, _now())
        events = engine.cancel_all(_now())
        assert sum(1 for e in events if isinstance(e, OrderCanceled)) == 3
        assert len(engine.open_orders()) == 0

    def test_cancel_nonexistent_returns_none(self):
        engine = make_engine()
        result = engine.cancel_order("nonexistent", _now())
        assert result is None


class TestLatencyQueue:
    def test_latency_delays_acceptance(self):
        latency = LatencyModel.from_ms(base_ms=200)  # 200ms
        engine = make_engine(latency=latency)
        engine.update_book(make_book())
        order = make_order("buy", "limit_maker", "99.95", "0.1")
        now = _now()
        event = engine.submit_order(order, now)
        assert isinstance(event, OrderAccepted)
        assert order.status == OrderStatus.PENDING_SUBMIT

        # Tick before latency expires
        events = engine.tick(now + 50_000_000)  # 50ms
        assert order.order_id not in {o.order_id for o in engine.open_orders()}

        # Tick after latency expires
        events = engine.tick(now + 250_000_000)  # 250ms
        assert any(isinstance(e, OrderAccepted) for e in events)


class TestTimegate:
    def test_time_gate_prevents_rapid_fills(self):
        """Two consecutive ticks within latency_ms should not both fill."""
        engine = make_engine(
            fill_model=QueuePositionFillModel(),
        )
        engine.update_book(make_book())
        order = make_order("buy", "limit_maker", "99.95", "5.0")
        now = _now()
        engine.submit_order(order, now)
        # First tick
        engine.tick(now)
        first_fill_count = order.fill_count
        # Second tick immediately (< latency_ms = 150ms)
        engine.tick(now + 10_000_000)  # 10ms
        assert order.fill_count == first_fill_count  # no new fill


class TestErrorHandling:
    def test_submit_no_raise(self):
        """submit_order should never raise even on internal error."""
        engine = make_engine()
        # Corrupt state to trigger error
        engine._spec = None  # type: ignore
        event = engine.submit_order(make_order(), _now())
        assert isinstance(event, (OrderRejected, EngineError))

    def test_tick_no_raise(self):
        engine = make_engine()
        # Submit order first, then corrupt book to trigger error path
        engine.update_book(make_book())
        order = make_order("buy", "limit_maker", "99.95", "0.1")
        engine.submit_order(order, _now())
        engine._fill_model = None  # type: ignore  -- will error in match_orders
        events = engine.tick(_now())
        # Should return EngineError (not raise)
        assert any(isinstance(e, EngineError) for e in events)
