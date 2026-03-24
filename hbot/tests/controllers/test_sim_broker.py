"""Tests for SimBroker — shadow executor for live-vs-paper calibration."""
from __future__ import annotations

import random
import tempfile
from decimal import Decimal
from pathlib import Path

from controllers.sim_broker import SimBroker, SimBrokerConfig


def _make_broker(enabled: bool = True, prob: float = 1.0) -> SimBroker:
    return SimBroker(SimBrokerConfig(enabled=enabled, prob_fill_on_limit=prob))


def _tick(broker: SimBroker, mid: str, buys: list | None = None, sells: list | None = None) -> dict:
    data: dict = {"mid_price": mid}
    if buys:
        data["buy_prices"] = [b[0] for b in buys]
        data["buy_amounts"] = [b[1] for b in buys]
    if sells:
        data["sell_prices"] = [s[0] for s in sells]
        data["sell_amounts"] = [s[1] for s in sells]
    return broker.on_tick(data)


class TestSimBrokerLifecycle:
    def test_disabled_broker_returns_empty(self):
        broker = _make_broker(enabled=False)
        with tempfile.TemporaryDirectory() as td:
            broker.start(td)
            result = _tick(broker, "50000")
            assert result == {}

    def test_not_started_returns_empty(self):
        broker = _make_broker()
        result = _tick(broker, "50000")
        assert result == {}

    def test_start_creates_csv(self):
        broker = _make_broker()
        with tempfile.TemporaryDirectory() as td:
            broker.start(td)
            assert (Path(td) / "shadow_minute.csv").exists()
            broker.stop()

    def test_stop_is_idempotent(self):
        broker = _make_broker()
        with tempfile.TemporaryDirectory() as td:
            broker.start(td)
            broker.stop()
            broker.stop()


class TestSimBrokerFillGeneration:
    def test_deterministic_fill_with_prob_1(self):
        broker = _make_broker(prob=1.0)
        with tempfile.TemporaryDirectory() as td:
            broker.start(td)
            result = _tick(broker, "50000", buys=[("49990", "0.01")])
            assert int(result["shadow_fill_count"]) == 1
            broker.stop()

    def test_no_fill_with_prob_0(self):
        broker = _make_broker(prob=0.0)
        with tempfile.TemporaryDirectory() as td:
            broker.start(td)
            result = _tick(broker, "50000", buys=[("49990", "0.01")])
            assert int(result["shadow_fill_count"]) == 0
            broker.stop()

    def test_probabilistic_fill(self):
        random.seed(42)
        broker = _make_broker(prob=0.5)
        with tempfile.TemporaryDirectory() as td:
            broker.start(td)
            fills = 0
            for _ in range(100):
                result = _tick(broker, "50000", buys=[("49990", "0.001")])
                fills = int(result["shadow_fill_count"])
            assert 20 < fills < 80
            broker.stop()


class TestSimBrokerPositionTracking:
    def test_buy_creates_long_position(self):
        broker = _make_broker()
        with tempfile.TemporaryDirectory() as td:
            broker.start(td)
            _tick(broker, "50000", buys=[("49990", "0.1")])
            assert broker._position.base == Decimal("0.1")
            broker.stop()

    def test_sell_creates_short_position(self):
        broker = _make_broker()
        with tempfile.TemporaryDirectory() as td:
            broker.start(td)
            _tick(broker, "50000", sells=[("50010", "0.1")])
            assert broker._position.base == Decimal("-0.1")
            broker.stop()

    def test_close_position_realizes_pnl(self):
        broker = _make_broker()
        with tempfile.TemporaryDirectory() as td:
            broker.start(td)
            _tick(broker, "50000", buys=[("50000", "0.1")])
            _tick(broker, "50100", sells=[("50100", "0.1")])
            assert broker._position.base == Decimal("0")
            assert broker._position.realized_pnl == Decimal("10.0")
            broker.stop()


class TestSimBrokerAdverseFills:
    def test_fill_with_bad_edge_is_adverse(self):
        """edge_bps = (price - mid) / mid * 10000 * sign; adverse when < -2."""
        broker = _make_broker()
        with tempfile.TemporaryDirectory() as td:
            broker.start(td)
            _tick(broker, "50000", buys=[("49980", "0.1")])
            assert broker._position.adverse_fills == 1
            broker.stop()

    def test_fill_with_good_edge_is_not_adverse(self):
        broker = _make_broker()
        with tempfile.TemporaryDirectory() as td:
            broker.start(td)
            _tick(broker, "50000", buys=[("49995", "0.1")])
            assert broker._position.adverse_fills == 0
            broker.stop()


class TestSimBrokerErrorHandling:
    def test_invalid_mid_returns_empty(self):
        broker = _make_broker()
        with tempfile.TemporaryDirectory() as td:
            broker.start(td)
            result = _tick(broker, "NaN")
            assert result == {}
            broker.stop()

    def test_zero_mid_returns_empty(self):
        broker = _make_broker()
        with tempfile.TemporaryDirectory() as td:
            broker.start(td)
            result = _tick(broker, "0")
            assert result == {}
            broker.stop()

    def test_negative_mid_returns_empty(self):
        broker = _make_broker()
        with tempfile.TemporaryDirectory() as td:
            broker.start(td)
            result = _tick(broker, "-100")
            assert result == {}
            broker.stop()
