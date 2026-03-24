"""Tests for controllers.protective_stop — protocol-based stop manager."""
from decimal import Decimal

import pytest

from controllers.protective_stop import ProtectiveStopBackend, ProtectiveStopManager


class MockStopBackend(ProtectiveStopBackend):
    def __init__(self):
        self.placed = []
        self.cancelled = []
        self._next_id = 100

    def place_stop(self, symbol: str, side: str, amount: Decimal, trigger_price: Decimal) -> str | None:
        oid = str(self._next_id)
        self._next_id += 1
        self.placed.append({"symbol": symbol, "side": side, "amount": amount, "trigger": trigger_price, "id": oid})
        return oid

    def cancel_stop(self, symbol: str, order_id: str) -> bool:
        self.cancelled.append({"symbol": symbol, "order_id": order_id})
        return True

    def cancel_all_stops(self, symbol: str) -> None:
        pass


def _make_manager(backend=None) -> ProtectiveStopManager:
    return ProtectiveStopManager(
        exchange_id="bitget_perpetual",
        trading_pair="BTC-USDT",
        stop_loss_pct=Decimal("0.03"),
        refresh_interval_s=60,
        backend=backend,
    )


def test_manager_disabled_without_backend():
    mgr = _make_manager()
    assert mgr.is_enabled is False
    mgr.update(Decimal("1.0"), Decimal("50000"))
    assert mgr.active_stop_order_id is None


def test_manager_places_stop_on_long():
    backend = MockStopBackend()
    mgr = _make_manager(backend)
    assert mgr.is_enabled is True
    mgr.update(Decimal("0.5"), Decimal("50000"))
    assert len(backend.placed) == 1
    assert backend.placed[0]["side"] == "sell"
    assert backend.placed[0]["trigger"] == Decimal("50000") * Decimal("0.97")
    assert mgr.active_stop_order_id == "100"


def test_manager_places_stop_on_short():
    backend = MockStopBackend()
    mgr = _make_manager(backend)
    mgr.update(Decimal("-0.5"), Decimal("50000"))
    assert len(backend.placed) == 1
    assert backend.placed[0]["side"] == "buy"


def test_manager_cancels_on_position_change():
    backend = MockStopBackend()
    mgr = _make_manager(backend)
    mgr.update(Decimal("0.5"), Decimal("50000"))
    assert mgr.active_stop_order_id == "100"
    mgr.update(Decimal("0.8"), Decimal("51000"))
    assert len(backend.cancelled) == 1
    assert backend.cancelled[0]["order_id"] == "100"
    assert mgr.active_stop_order_id == "101"


def test_manager_cancels_on_flat():
    backend = MockStopBackend()
    mgr = _make_manager(backend)
    mgr.update(Decimal("0.5"), Decimal("50000"))
    assert mgr.active_stop_order_id == "100"
    mgr.update(Decimal("0"), Decimal("0"))
    assert len(backend.cancelled) == 1
    assert mgr.active_stop_order_id is None


def test_manager_no_op_when_unchanged():
    backend = MockStopBackend()
    mgr = _make_manager(backend)
    mgr.update(Decimal("0.5"), Decimal("50000"))
    assert len(backend.placed) == 1
    mgr.update(Decimal("0.5"), Decimal("50000"))
    assert len(backend.placed) == 1


def test_cancel_all():
    backend = MockStopBackend()
    mgr = _make_manager(backend)
    mgr.update(Decimal("0.5"), Decimal("50000"))
    mgr.cancel_all()
    assert mgr.active_stop_order_id is None
    assert len(backend.cancelled) == 1


def test_initialize_with_injected_backend():
    backend = MockStopBackend()
    mgr = _make_manager(backend)
    assert mgr.initialize() is True
    assert mgr.is_enabled is True


def test_perp_symbol_format():
    backend = MockStopBackend()
    mgr = ProtectiveStopManager(
        exchange_id="bitget_perpetual",
        trading_pair="BTC-USDT",
        stop_loss_pct=Decimal("0.03"),
        backend=backend,
    )
    mgr.update(Decimal("1.0"), Decimal("50000"))
    assert backend.placed[0]["symbol"] == "BTC/USDT:USDT"


# ------------------------------------------------------------------
# Parametrized boundary tests
# ------------------------------------------------------------------

@pytest.mark.parametrize("position,expected_side,trigger_factor", [
    (Decimal("0.5"), "sell", Decimal("0.97")),
    (Decimal("1.0"), "sell", Decimal("0.97")),
    (Decimal("0.001"), "sell", Decimal("0.97")),
    (Decimal("-0.5"), "buy", Decimal("1.03")),
    (Decimal("-1.0"), "buy", Decimal("1.03")),
    (Decimal("-0.001"), "buy", Decimal("1.03")),
])
def test_stop_placement_by_position_side(position, expected_side, trigger_factor):
    backend = MockStopBackend()
    mgr = _make_manager(backend)
    price = Decimal("50000")
    mgr.update(position, price)
    assert len(backend.placed) == 1
    assert backend.placed[0]["side"] == expected_side
    assert backend.placed[0]["trigger"] == price * trigger_factor


@pytest.mark.parametrize("position", [
    Decimal("0"),
    Decimal("0.0"),
])
def test_no_stop_when_flat(position):
    backend = MockStopBackend()
    mgr = _make_manager(backend)
    mgr.update(position, Decimal("50000"))
    assert len(backend.placed) == 0
    assert mgr.active_stop_order_id is None


@pytest.mark.parametrize("from_pos,to_pos,expect_cancel", [
    (Decimal("0.5"), Decimal("0.8"), True),
    (Decimal("0.5"), Decimal("0"), True),
    (Decimal("-0.5"), Decimal("-0.8"), True),
    (Decimal("-0.5"), Decimal("0"), True),
    (Decimal("0.5"), Decimal("-0.3"), True),
])
def test_position_transitions(from_pos, to_pos, expect_cancel):
    backend = MockStopBackend()
    mgr = _make_manager(backend)
    mgr.update(from_pos, Decimal("50000"))
    initial_placed = len(backend.placed)
    mgr.update(to_pos, Decimal("51000") if to_pos != Decimal("0") else Decimal("0"))
    if expect_cancel:
        assert len(backend.cancelled) >= 1
    else:
        assert len(backend.cancelled) == 0
        assert len(backend.placed) == initial_placed


# ------------------------------------------------------------------
# NaN/Inf safety tests
# ------------------------------------------------------------------

@pytest.mark.parametrize("bad_value", [
    Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"),
])
def test_nan_inf_position_base_rejected(bad_value):
    backend = MockStopBackend()
    mgr = _make_manager(backend)
    mgr.update(bad_value, Decimal("50000"))
    assert len(backend.placed) == 0

@pytest.mark.parametrize("bad_value", [
    Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"),
])
def test_nan_inf_avg_entry_rejected(bad_value):
    backend = MockStopBackend()
    mgr = _make_manager(backend)
    mgr.update(Decimal("0.5"), bad_value)
    assert len(backend.placed) == 0


# ------------------------------------------------------------------
# Failure escalation tests
# ------------------------------------------------------------------

class FailingBackend(ProtectiveStopBackend):
    """Backend that always fails to place stops."""
    def place_stop(self, symbol, side, amount, trigger_price):
        return None
    def cancel_stop(self, symbol, order_id):
        return False
    def cancel_all_stops(self, symbol):
        pass


def test_placement_failure_escalation_after_threshold():
    backend = FailingBackend()
    mgr = _make_manager(backend)
    assert mgr.placement_failure_escalation is False
    # Each update triggers two placement attempts (initial + retry)
    for _ in range(3):
        mgr.update(Decimal("0.5"), Decimal("50000"))
        mgr._last_refresh_ts = 0  # force re-evaluation
    assert mgr._consecutive_placement_failures >= 3
    assert mgr.placement_failure_escalation is True


def test_placement_failure_resets_on_success():
    calls = {"count": 0}

    class EventuallySucceedsBackend(ProtectiveStopBackend):
        def place_stop(self, symbol, side, amount, trigger_price):
            calls["count"] += 1
            if calls["count"] >= 5:
                return "order-ok"
            return None
        def cancel_stop(self, symbol, order_id):
            return True
        def cancel_all_stops(self, symbol):
            pass

    backend = EventuallySucceedsBackend()
    mgr = _make_manager(backend)
    # Fail a few times
    mgr.update(Decimal("0.5"), Decimal("50000"))
    mgr._last_refresh_ts = 0
    mgr.update(Decimal("0.5"), Decimal("50000"))
    assert mgr._consecutive_placement_failures > 0
    # Eventually succeed
    mgr._last_refresh_ts = 0
    mgr.update(Decimal("0.5"), Decimal("50000"))
    assert mgr._consecutive_placement_failures == 0
