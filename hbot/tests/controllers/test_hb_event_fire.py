from __future__ import annotations

import sys
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from simulation.bridge.hb_event_fire import (
    _find_controller_for_connector,
    _fire_fill_event,
    _realized_pnl_delta_quote,
)
from simulation.types import InstrumentId, OrderFilled


def test_realized_pnl_delta_quote_positive() -> None:
    ctrl = SimpleNamespace(_realized_pnl_today=Decimal("1.25"))
    out = _realized_pnl_delta_quote(ctrl, before_value=1.00)
    assert abs(out - 0.25) < 1e-9


def test_realized_pnl_delta_quote_negative() -> None:
    ctrl = SimpleNamespace(_realized_pnl_today=Decimal("0.80"))
    out = _realized_pnl_delta_quote(ctrl, before_value=1.00)
    assert abs(out + 0.20) < 1e-9


def test_realized_pnl_delta_quote_handles_missing_controller() -> None:
    out = _realized_pnl_delta_quote(None, before_value=1.00)
    assert out == 0.0


def test_find_controller_for_connector_prefers_pair_scope() -> None:
    ctrl_btc = SimpleNamespace(config=SimpleNamespace(connector_name="bitget", trading_pair="BTC-USDT", instance_name="bot1"))
    ctrl_eth = SimpleNamespace(config=SimpleNamespace(connector_name="bitget", trading_pair="ETH-USDT", instance_name="bot2"))
    strategy = SimpleNamespace(controllers={"ctrl_btc": ctrl_btc, "ctrl_eth": ctrl_eth})

    resolved = _find_controller_for_connector(strategy, "bitget", trading_pair="ETH-USDT")
    assert resolved is ctrl_eth


def test_find_controller_for_connector_uses_instance_scope() -> None:
    ctrl_a = SimpleNamespace(config=SimpleNamespace(connector_name="bitget", trading_pair="BTC-USDT", instance_name="bot1"))
    ctrl_b = SimpleNamespace(config=SimpleNamespace(connector_name="bitget", trading_pair="BTC-USDT", instance_name="bot2"))
    strategy = SimpleNamespace(controllers={"ctrl_a": ctrl_a, "ctrl_b": ctrl_b})

    resolved = _find_controller_for_connector(strategy, "bitget", trading_pair="BTC-USDT", instance_name="bot2")
    assert resolved is ctrl_b


def test_find_controller_for_connector_returns_none_when_ambiguous() -> None:
    ctrl_a = SimpleNamespace(config=SimpleNamespace(connector_name="bitget", trading_pair="BTC-USDT", instance_name="bot1"))
    ctrl_b = SimpleNamespace(config=SimpleNamespace(connector_name="bitget", trading_pair="BTC-USDT", instance_name="bot2"))
    strategy = SimpleNamespace(controllers={"ctrl_a": ctrl_a, "ctrl_b": ctrl_b})

    resolved = _find_controller_for_connector(strategy, "bitget")
    assert resolved is None


def _install_fill_event_stubs(monkeypatch) -> None:
    class _FakeHBOrderFilledEvent:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class _FakeTradeFee:
        def __init__(self, percent, flat_fees):
            self.percent = percent
            self.flat_fees = flat_fees

    class _FakeTokenAmount:
        def __init__(self, token, amount):
            self.token = token
            self.amount = amount

    fake_events = SimpleNamespace(
        OrderFilledEvent=_FakeHBOrderFilledEvent,
        TradeFee=_FakeTradeFee,
        TokenAmount=_FakeTokenAmount,
    )
    fake_common = SimpleNamespace(TradeType=SimpleNamespace(BUY="BUY", SELL="SELL"))
    fake_identity = SimpleNamespace(validate_event_identity=lambda payload: (False, "test"))
    monkeypatch.setitem(sys.modules, "hummingbot.core.event.events", fake_events)
    monkeypatch.setitem(sys.modules, "hummingbot.core.data_type.common", fake_common)
    monkeypatch.setitem(sys.modules, "platform.contracts.event_identity", fake_identity)


def test_fire_fill_event_drops_unscoped_paper_fill_without_runtime_order(monkeypatch) -> None:
    _install_fill_event_stubs(monkeypatch)
    controller = SimpleNamespace(
        config=SimpleNamespace(connector_name="bitget", trading_pair="BTC-USDT", instance_name="bot1"),
        id="ctrl_1",
        did_fill_order=MagicMock(),
        _realized_pnl_today=Decimal("0"),
    )
    strategy = SimpleNamespace(
        controllers={"ctrl_1": controller},
        _paper_desk_v2_bridges={},
        _paper_exchange_runtime_orders={},
    )
    bridge_state = SimpleNamespace(get_redis=lambda: None)
    fill_event = OrderFilled(
        event_id="evt-1",
        timestamp_ns=1,
        instrument_id=InstrumentId("bitget", "BTC-USDT", "perp"),
        order_id="pe-ghost-fill-1",
        side="buy",
        fill_price=Decimal("100"),
        fill_quantity=Decimal("0.1"),
        fee=Decimal("0.01"),
        is_maker=False,
        remaining_quantity=Decimal("0"),
        source_bot="bitget",
    )

    _fire_fill_event(strategy, "bitget", fill_event, bridge_state)

    controller.did_fill_order.assert_not_called()


def test_fire_fill_event_accepts_scoped_runtime_owned_paper_fill(monkeypatch) -> None:
    _install_fill_event_stubs(monkeypatch)
    controller = SimpleNamespace(
        config=SimpleNamespace(connector_name="bitget", trading_pair="BTC-USDT", instance_name="bot1"),
        id="ctrl_1",
        did_fill_order=MagicMock(),
        _realized_pnl_today=Decimal("0"),
    )
    runtime_order = SimpleNamespace(trade_type="buy")
    strategy = SimpleNamespace(
        controllers={"ctrl_1": controller},
        _paper_desk_v2_bridges={},
        _paper_exchange_runtime_orders={"bitget": {"pe-owned-fill-1": runtime_order}},
    )
    bridge_state = SimpleNamespace(get_redis=lambda: None)
    fill_event = OrderFilled(
        event_id="evt-2",
        timestamp_ns=1,
        instrument_id=InstrumentId("bitget", "BTC-USDT", "perp"),
        order_id="pe-owned-fill-1",
        side="buy",
        fill_price=Decimal("100"),
        fill_quantity=Decimal("0.1"),
        fee=Decimal("0.01"),
        is_maker=False,
        remaining_quantity=Decimal("0"),
        source_bot="bitget",
    )

    _fire_fill_event(strategy, "bitget", fill_event, bridge_state)

    controller.did_fill_order.assert_called_once()


def test_fire_fill_event_uses_sell_trade_type_from_runtime_order(monkeypatch) -> None:
    _install_fill_event_stubs(monkeypatch)
    controller = SimpleNamespace(
        config=SimpleNamespace(connector_name="bitget", trading_pair="BTC-USDT", instance_name="bot1"),
        id="ctrl_1",
        did_fill_order=MagicMock(),
        _realized_pnl_today=Decimal("0"),
    )
    runtime_order = SimpleNamespace(trade_type="sell")
    strategy = SimpleNamespace(
        controllers={"ctrl_1": controller},
        _paper_desk_v2_bridges={},
        _paper_exchange_runtime_orders={"bitget": {"pe-owned-sell-fill": runtime_order}},
    )
    bridge_state = SimpleNamespace(get_redis=lambda: None)
    fill_event = OrderFilled(
        event_id="evt-sell",
        timestamp_ns=1,
        instrument_id=InstrumentId("bitget", "BTC-USDT", "perp"),
        order_id="pe-owned-sell-fill",
        side="sell",
        fill_price=Decimal("100"),
        fill_quantity=Decimal("0.1"),
        fee=Decimal("0.01"),
        is_maker=False,
        remaining_quantity=Decimal("0"),
        source_bot="bitget",
    )

    _fire_fill_event(strategy, "bitget", fill_event, bridge_state)

    assert controller.did_fill_order.call_args.args[0].trade_type == "SELL"


def test_fire_fill_event_logs_instance_name_attachment_failure(monkeypatch) -> None:
    class _FailingHBOrderFilledEvent:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                object.__setattr__(self, key, value)

        def __setattr__(self, key, value):
            if key == "instance_name":
                raise RuntimeError("cannot attach instance_name")
            object.__setattr__(self, key, value)

    class _FakeTradeFee:
        def __init__(self, percent, flat_fees):
            self.percent = percent
            self.flat_fees = flat_fees

    class _FakeTokenAmount:
        def __init__(self, token, amount):
            self.token = token
            self.amount = amount

    monkeypatch.setitem(
        sys.modules,
        "hummingbot.core.event.events",
        SimpleNamespace(
            OrderFilledEvent=_FailingHBOrderFilledEvent,
            TradeFee=_FakeTradeFee,
            TokenAmount=_FakeTokenAmount,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "hummingbot.core.data_type.common",
        SimpleNamespace(TradeType=SimpleNamespace(BUY="BUY", SELL="SELL")),
    )
    monkeypatch.setitem(
        sys.modules,
        "platform.contracts.event_identity",
        SimpleNamespace(validate_event_identity=lambda payload: (False, "test")),
    )
    controller = SimpleNamespace(
        config=SimpleNamespace(connector_name="bitget", trading_pair="BTC-USDT", instance_name="bot1"),
        id="ctrl_1",
        did_fill_order=MagicMock(),
        _realized_pnl_today=Decimal("0"),
    )
    runtime_order = SimpleNamespace(trade_type="buy")
    strategy = SimpleNamespace(
        controllers={"ctrl_1": controller},
        _paper_desk_v2_bridges={},
        _paper_exchange_runtime_orders={"bitget": {"pe-owned-fill-2": runtime_order}},
    )
    bridge_state = SimpleNamespace(get_redis=lambda: None)
    fill_event = OrderFilled(
        event_id="evt-log-instance-name",
        timestamp_ns=1,
        instrument_id=InstrumentId("bitget", "BTC-USDT", "perp"),
        order_id="pe-owned-fill-2",
        side="buy",
        fill_price=Decimal("100"),
        fill_quantity=Decimal("0.1"),
        fee=Decimal("0.01"),
        is_maker=False,
        remaining_quantity=Decimal("0"),
        source_bot="bitget",
    )

    with patch("simulation.bridge.hb_event_fire.logger.debug") as debug_mock:
        _fire_fill_event(strategy, "bitget", fill_event, bridge_state)

    controller.did_fill_order.assert_called_once()
    debug_mock.assert_called_once()
