"""Tests for controllers.protective_stop — protocol-based stop manager."""
from decimal import Decimal
from typing import Optional

from controllers.protective_stop import ProtectiveStopBackend, ProtectiveStopManager


class MockStopBackend(ProtectiveStopBackend):
    def __init__(self):
        self.placed = []
        self.cancelled = []
        self._next_id = 100

    def place_stop(self, symbol: str, side: str, amount: Decimal, trigger_price: Decimal) -> Optional[str]:
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
