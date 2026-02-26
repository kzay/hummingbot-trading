"""Tests for the explicit order state machine (Phase 2).

Covers:
- All valid transitions
- Rejection of invalid transitions
- Reserve lifecycle under state machine
"""
from decimal import Decimal

import pytest

from controllers.paper_engine_v2.types import (
    OrderStatus,
    order_status_transition,
)


class TestOrderStateMachineTransitions:
    # Valid forward transitions
    def test_pending_to_open(self):
        assert order_status_transition(OrderStatus.PENDING_SUBMIT, OrderStatus.OPEN) == OrderStatus.OPEN

    def test_pending_to_canceled(self):
        assert order_status_transition(OrderStatus.PENDING_SUBMIT, OrderStatus.CANCELED) == OrderStatus.CANCELED

    def test_pending_to_rejected(self):
        assert order_status_transition(OrderStatus.PENDING_SUBMIT, OrderStatus.REJECTED) == OrderStatus.REJECTED

    def test_open_to_partial(self):
        assert order_status_transition(OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED) == OrderStatus.PARTIALLY_FILLED

    def test_open_to_filled(self):
        assert order_status_transition(OrderStatus.OPEN, OrderStatus.FILLED) == OrderStatus.FILLED

    def test_open_to_canceled(self):
        assert order_status_transition(OrderStatus.OPEN, OrderStatus.CANCELED) == OrderStatus.CANCELED

    def test_partial_to_filled(self):
        assert order_status_transition(OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED) == OrderStatus.FILLED

    def test_partial_to_canceled(self):
        assert order_status_transition(OrderStatus.PARTIALLY_FILLED, OrderStatus.CANCELED) == OrderStatus.CANCELED

    def test_partial_to_partial(self):
        assert order_status_transition(OrderStatus.PARTIALLY_FILLED, OrderStatus.PARTIALLY_FILLED) == OrderStatus.PARTIALLY_FILLED

    # Invalid transitions (all terminal states have no outgoing)
    def test_filled_to_canceled_invalid(self):
        with pytest.raises(ValueError, match="Invalid order state transition"):
            order_status_transition(OrderStatus.FILLED, OrderStatus.CANCELED)

    def test_canceled_to_open_invalid(self):
        with pytest.raises(ValueError, match="Invalid order state transition"):
            order_status_transition(OrderStatus.CANCELED, OrderStatus.OPEN)

    def test_rejected_to_open_invalid(self):
        with pytest.raises(ValueError, match="Invalid order state transition"):
            order_status_transition(OrderStatus.REJECTED, OrderStatus.OPEN)

    def test_pending_cannot_go_to_partial(self):
        with pytest.raises(ValueError, match="Invalid order state transition"):
            order_status_transition(OrderStatus.PENDING_SUBMIT, OrderStatus.PARTIALLY_FILLED)

    def test_filled_to_filled_invalid(self):
        with pytest.raises(ValueError):
            order_status_transition(OrderStatus.FILLED, OrderStatus.FILLED)

    # Error message quality
    def test_error_message_includes_current_and_target(self):
        with pytest.raises(ValueError) as exc_info:
            order_status_transition(OrderStatus.FILLED, OrderStatus.OPEN)
        msg = str(exc_info.value)
        assert "filled" in msg
        assert "open" in msg


class TestOrderStateMachineInEngine:
    """Integration: state machine enforced in matching engine."""

    def test_submitted_order_transitions_to_open(self):
        """With no-latency model, order goes PENDING_SUBMIT → OPEN immediately."""
        from decimal import Decimal
        import time
        from controllers.paper_engine_v2.fee_models import MakerTakerFeeModel
        from controllers.paper_engine_v2.fill_models import TopOfBookFillModel
        from controllers.paper_engine_v2.latency_model import NO_LATENCY
        from controllers.paper_engine_v2.matching_engine import EngineConfig, OrderMatchingEngine
        from controllers.paper_engine_v2.portfolio import PaperPortfolio, PortfolioConfig
        from tests.controllers.test_paper_engine_v2.conftest import BTC_SPOT, make_book, make_order, make_spec

        spec = make_spec(BTC_SPOT)
        portfolio = PaperPortfolio({"USDT": Decimal("10000"), "BTC": Decimal("1")}, PortfolioConfig())
        engine = OrderMatchingEngine(
            instrument_id=BTC_SPOT,
            instrument_spec=spec,
            portfolio=portfolio,
            fill_model=TopOfBookFillModel(),
            fee_model=MakerTakerFeeModel(Decimal("0.0002"), Decimal("0.0006")),
            latency_model=NO_LATENCY,
            config=EngineConfig(),
        )
        engine.update_book(make_book())
        order = make_order("buy", "limit_maker", "99.95", "0.1")
        engine.submit_order(order, int(time.time() * 1e9))
        assert order.status == OrderStatus.OPEN

    def test_reserve_released_on_cancel_only_once(self):
        """Reserve must not be double-released on cancel."""
        from decimal import Decimal
        import time
        from controllers.paper_engine_v2.fee_models import MakerTakerFeeModel
        from controllers.paper_engine_v2.fill_models import TopOfBookFillModel
        from controllers.paper_engine_v2.latency_model import NO_LATENCY
        from controllers.paper_engine_v2.matching_engine import EngineConfig, OrderMatchingEngine
        from controllers.paper_engine_v2.portfolio import PaperPortfolio, PortfolioConfig
        from tests.controllers.test_paper_engine_v2.conftest import BTC_SPOT, make_book, make_order, make_spec

        usdt_start = Decimal("1000")
        spec = make_spec(BTC_SPOT)
        portfolio = PaperPortfolio({"USDT": usdt_start, "BTC": Decimal("0")}, PortfolioConfig())
        engine = OrderMatchingEngine(
            instrument_id=BTC_SPOT,
            instrument_spec=spec,
            portfolio=portfolio,
            fill_model=TopOfBookFillModel(),
            fee_model=MakerTakerFeeModel(Decimal("0.0002"), Decimal("0.0006")),
            latency_model=NO_LATENCY,
            config=EngineConfig(),
        )
        engine.update_book(make_book())
        order = make_order("buy", "limit_maker", "99.95", "0.1")
        now = int(time.time() * 1e9)
        engine.submit_order(order, now)
        # Cancel once
        engine.cancel_order(order.order_id, now + 1)
        avail_after_cancel = portfolio.available("USDT")
        # Cancel again (should be no-op)
        engine.cancel_order(order.order_id, now + 2)
        # Available should not increase (no double-release)
        assert portfolio.available("USDT") == avail_after_cancel
