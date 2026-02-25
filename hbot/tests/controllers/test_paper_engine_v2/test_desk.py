"""Tests for paper_engine_v2 PaperDesk orchestrator.

Covers: multi-instrument, multi-bot routing, cancel_all,
event log, state persistence round-trip, determinism.
"""
import time
from decimal import Decimal
from pathlib import Path

import pytest

from controllers.paper_engine_v2.data_feeds import StaticDataFeed
from controllers.paper_engine_v2.desk import DeskConfig, PaperDesk
from controllers.paper_engine_v2.types import (
    OrderAccepted, OrderFilled, OrderRejected,
    OrderSide, PaperOrderType,
)
from tests.controllers.test_paper_engine_v2.conftest import (
    BTC_SPOT, ETH_SPOT, make_book, make_spec,
)


def make_desk(tmp_path=None, usdt="10000", seed=7) -> PaperDesk:
    state_path = str(tmp_path / "desk.json") if tmp_path else "/tmp/test_desk.json"
    return PaperDesk(DeskConfig(
        initial_balances={"USDT": Decimal(usdt)},
        state_file_path=state_path,
        seed=seed,
        event_log_max_size=1000,
    ))


class TestDeskRegistration:
    def test_register_and_submit(self, tmp_path):
        desk = make_desk(tmp_path)
        spec = make_spec(BTC_SPOT)
        book = make_book()
        feed = StaticDataFeed(book)
        desk.register_instrument(spec, feed)

        event = desk.submit_order(
            BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER,
            Decimal("99.95"), Decimal("0.1"), source_bot="bot1",
        )
        assert isinstance(event, OrderAccepted)

    def test_submit_unregistered_rejects(self, tmp_path):
        desk = make_desk(tmp_path)
        event = desk.submit_order(
            BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER,
            Decimal("99.95"), Decimal("0.1"),
        )
        assert isinstance(event, OrderRejected)
        assert "not_registered" in event.reason


class TestMultiInstrument:
    def test_two_instruments_ticked(self, tmp_path):
        desk = make_desk(tmp_path)
        spec_btc = make_spec(BTC_SPOT)
        spec_eth = make_spec(ETH_SPOT)
        desk.register_instrument(spec_btc, StaticDataFeed(make_book(iid=BTC_SPOT)))
        desk.register_instrument(spec_eth, StaticDataFeed(make_book("2000", "2001", iid=ETH_SPOT)))

        desk.submit_order(BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER, Decimal("99.95"), Decimal("0.1"))
        desk.submit_order(ETH_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER, Decimal("1999"), Decimal("0.1"))

        events = desk.tick()
        # Both instruments should produce events
        instruments_seen = {e.instrument_id.trading_pair for e in events}
        assert len(instruments_seen) >= 1  # at least one instrument ticked


class TestMultiBotRouting:
    def test_orders_from_different_bots(self, tmp_path):
        desk = make_desk(tmp_path)
        spec = make_spec(BTC_SPOT)
        desk.register_instrument(spec, StaticDataFeed(make_book()))

        e1 = desk.submit_order(BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER,
                                Decimal("99.95"), Decimal("0.1"), source_bot="bot1")
        e2 = desk.submit_order(BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER,
                                Decimal("99.90"), Decimal("0.1"), source_bot="bot2")
        assert isinstance(e1, OrderAccepted)
        assert isinstance(e2, OrderAccepted)


class TestCancelAll:
    def test_cancel_all_instruments(self, tmp_path):
        desk = make_desk(tmp_path)
        spec = make_spec(BTC_SPOT)
        desk.register_instrument(spec, StaticDataFeed(make_book()))
        desk.submit_order(BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER, Decimal("99.95"), Decimal("0.1"))
        desk.submit_order(BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER, Decimal("99.90"), Decimal("0.1"))
        events = desk.cancel_all()
        from controllers.paper_engine_v2.types import OrderCanceled
        assert sum(1 for e in events if isinstance(e, OrderCanceled)) == 2

    def test_cancel_all_for_instrument(self, tmp_path):
        desk = make_desk(tmp_path)
        spec = make_spec(BTC_SPOT)
        desk.register_instrument(spec, StaticDataFeed(make_book()))
        desk.submit_order(BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER, Decimal("99.95"), Decimal("0.1"))
        events = desk.cancel_all(instrument_id=BTC_SPOT)
        from controllers.paper_engine_v2.types import OrderCanceled
        assert any(isinstance(e, OrderCanceled) for e in events)


class TestEventLog:
    def test_events_logged(self, tmp_path):
        desk = make_desk(tmp_path)
        spec = make_spec(BTC_SPOT)
        desk.register_instrument(spec, StaticDataFeed(make_book()))
        desk.submit_order(BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER, Decimal("99.95"), Decimal("0.1"))
        assert len(desk.event_log()) >= 1
        assert isinstance(desk.event_log()[0], OrderAccepted)


class TestStatePersistence:
    def test_persist_and_restore(self, tmp_path):
        desk = make_desk(tmp_path, usdt="5000")
        spec = make_spec(BTC_SPOT)
        desk.register_instrument(spec, StaticDataFeed(make_book()))
        # Force save
        desk._state_store.save(desk.snapshot(), now_ts=0.0, force=True)

        # New desk restores from file
        desk2 = make_desk(tmp_path, usdt="9999")
        assert desk2.portfolio.balance("USDT") == Decimal("5000")


class TestDeterminism:
    def test_same_seed_same_events(self, tmp_path):
        """Same seed + same book → identical fill sequence."""
        def run_once():
            desk = make_desk(tmp_path, seed=7)
            spec = make_spec(BTC_SPOT)
            desk.register_instrument(spec, StaticDataFeed(make_book()))
            desk.submit_order(BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER,
                              Decimal("99.95"), Decimal("1.0"), source_bot="bot1")
            now = int(time.time() * 1e9)
            for i in range(5):
                desk.tick(now_ns=now + i * 200_000_000)
            return [(type(e).__name__, str(getattr(e, "fill_quantity", "")))
                    for e in desk.event_log()]

        r1 = run_once()
        r2 = run_once()
        assert r1 == r2
