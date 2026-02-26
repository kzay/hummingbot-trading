"""Tests for the EventSubscriber protocol in hb_bridge.py (Phase 5).

Tests clean decoupled event routing without requiring HB imports.
"""
from decimal import Decimal
from typing import List

import pytest

from controllers.paper_engine_v2.hb_bridge import (
    EventSubscriber,
    _dispatch_to_subscribers,
    _EVENT_SUBSCRIBERS,
    register_event_subscriber,
    unregister_event_subscriber,
)
from controllers.paper_engine_v2.types import (
    InstrumentId,
    OrderCanceled,
    OrderFilled,
    OrderRejected,
    _ZERO,
)

BTC_PERP = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")


class _Recorder:
    """Test EventSubscriber that records all received events."""

    def __init__(self):
        self.fills: List[OrderFilled] = []
        self.cancels: List[OrderCanceled] = []
        self.rejects: List[OrderRejected] = []

    def on_fill(self, event: OrderFilled, connector_name: str) -> None:
        self.fills.append(event)

    def on_cancel(self, event: OrderCanceled, connector_name: str) -> None:
        self.cancels.append(event)

    def on_reject(self, event: OrderRejected, connector_name: str) -> None:
        self.rejects.append(event)


class _RaisingSubscriber:
    """Subscriber that always raises — must not propagate to caller."""

    def on_fill(self, event, connector_name): raise RuntimeError("oops")
    def on_cancel(self, event, connector_name): raise RuntimeError("oops")
    def on_reject(self, event, connector_name): raise RuntimeError("oops")


def _fill_event() -> OrderFilled:
    return OrderFilled(
        event_id="test-fill",
        timestamp_ns=0,
        instrument_id=BTC_PERP,
        order_id="ord1",
        fill_price=Decimal("100"),
        fill_quantity=Decimal("1"),
        fee=Decimal("0.01"),
        is_maker=True,
        remaining_quantity=_ZERO,
        source_bot="test",
    )


def _cancel_event() -> OrderCanceled:
    return OrderCanceled(
        event_id="test-cancel",
        timestamp_ns=0,
        instrument_id=BTC_PERP,
        order_id="ord1",
        source_bot="test",
    )


def _reject_event() -> OrderRejected:
    return OrderRejected(
        event_id="test-reject",
        timestamp_ns=0,
        instrument_id=BTC_PERP,
        order_id="ord1",
        reason="test_reason",
        source_bot="test",
    )


class TestEventSubscriberProtocol:
    def setup_method(self):
        _EVENT_SUBSCRIBERS.clear()

    def teardown_method(self):
        _EVENT_SUBSCRIBERS.clear()

    def test_register_and_receive_fill(self):
        recorder = _Recorder()
        register_event_subscriber(recorder)
        _dispatch_to_subscribers(_fill_event(), "test_connector")
        assert len(recorder.fills) == 1
        assert recorder.fills[0].order_id == "ord1"

    def test_register_and_receive_cancel(self):
        recorder = _Recorder()
        register_event_subscriber(recorder)
        _dispatch_to_subscribers(_cancel_event(), "test_connector")
        assert len(recorder.cancels) == 1

    def test_register_and_receive_reject(self):
        recorder = _Recorder()
        register_event_subscriber(recorder)
        _dispatch_to_subscribers(_reject_event(), "test_connector")
        assert len(recorder.rejects) == 1

    def test_multiple_subscribers_all_receive(self):
        rec1 = _Recorder()
        rec2 = _Recorder()
        register_event_subscriber(rec1)
        register_event_subscriber(rec2)
        _dispatch_to_subscribers(_fill_event(), "connector")
        assert len(rec1.fills) == 1
        assert len(rec2.fills) == 1

    def test_unregister_stops_delivery(self):
        recorder = _Recorder()
        register_event_subscriber(recorder)
        unregister_event_subscriber(recorder)
        _dispatch_to_subscribers(_fill_event(), "connector")
        assert len(recorder.fills) == 0

    def test_raising_subscriber_does_not_propagate(self):
        """Subscriber errors must never crash the trading loop."""
        register_event_subscriber(_RaisingSubscriber())
        # Should not raise
        _dispatch_to_subscribers(_fill_event(), "connector")

    def test_no_subscribers_is_noop(self):
        # Should not raise or error with empty subscriber list
        _dispatch_to_subscribers(_fill_event(), "connector")
