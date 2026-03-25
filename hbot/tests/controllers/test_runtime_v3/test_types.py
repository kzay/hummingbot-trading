"""Tests for v3 type definitions — immutability, defaults, protocols."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from controllers.runtime.v3.orders import (
    CancelOrder,
    ClosePosition,
    DeskOrder,
    ModifyOrder,
    PartialReduce,
    SubmitOrder,
)
from controllers.runtime.v3.protocols import (
    ExecutionAdapter,
    RiskLayer,
    StrategySignalSource,
    TradingDeskProtocol,
)
from controllers.runtime.v3.risk_types import RiskDecision
from controllers.runtime.v3.signals import (
    SignalLevel,
    TelemetryField,
    TelemetrySchema,
    TradingSignal,
)
from controllers.runtime.v3.types import (
    EquitySnapshot,
    FundingSnapshot,
    IndicatorSnapshot,
    MarketSnapshot,
    MlSnapshot,
    OrderBookSnapshot,
    PositionSnapshot,
    RegimeSnapshot,
    TradeFlowSnapshot,
)

_ZERO = Decimal("0")


# ── Frozen immutability ──────────────────────────────────────────────


class TestFrozenImmutability:
    """All snapshot / signal types must be frozen dataclasses."""

    @pytest.mark.parametrize(
        "cls",
        [
            IndicatorSnapshot,
            OrderBookSnapshot,
            PositionSnapshot,
            EquitySnapshot,
            TradeFlowSnapshot,
            RegimeSnapshot,
            FundingSnapshot,
            MlSnapshot,
            MarketSnapshot,
            SignalLevel,
            TradingSignal,
            TelemetryField,
            TelemetrySchema,
            DeskOrder,
            SubmitOrder,
            CancelOrder,
            ModifyOrder,
            ClosePosition,
            PartialReduce,
            RiskDecision,
        ],
    )
    def test_is_frozen_dataclass(self, cls):
        assert dataclasses.is_dataclass(cls)
        # frozen=True sets __dataclass_params__.frozen
        assert cls.__dataclass_params__.frozen  # type: ignore[attr-defined]

    def test_market_snapshot_field_mutation_raises(self):
        snap = MarketSnapshot(mid=Decimal("65000"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            snap.mid = Decimal("66000")  # type: ignore[misc]

    def test_trading_signal_field_mutation_raises(self):
        sig = TradingSignal(family="no_trade", direction="off")
        with pytest.raises(dataclasses.FrozenInstanceError):
            sig.conviction = Decimal("1")  # type: ignore[misc]

    def test_desk_order_field_mutation_raises(self):
        order = DeskOrder(side="buy", order_type="limit", price=Decimal("100"), amount_quote=Decimal("50"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            order.price = Decimal("200")  # type: ignore[misc]


# ── Default values ───────────────────────────────────────────────────


class TestDefaults:
    def test_market_snapshot_defaults(self):
        snap = MarketSnapshot()
        assert snap.mid == _ZERO
        assert snap.timestamp_ms == 0
        assert snap.trade_flow is None
        assert snap.funding is None
        assert snap.ml is None
        assert isinstance(snap.indicators, IndicatorSnapshot)
        assert isinstance(snap.order_book, OrderBookSnapshot)
        assert isinstance(snap.position, PositionSnapshot)
        assert isinstance(snap.equity, EquitySnapshot)
        assert isinstance(snap.regime, RegimeSnapshot)

    def test_indicator_snapshot_defaults(self):
        ind = IndicatorSnapshot()
        assert ind.ema == {}
        assert ind.atr == {}
        assert ind.bb_lower == _ZERO
        assert ind.bars_available == 0

    def test_position_snapshot_defaults(self):
        pos = PositionSnapshot()
        assert pos.base_amount == _ZERO
        assert pos.is_perp is False
        assert pos.leverage == 1

    def test_regime_snapshot_defaults(self):
        reg = RegimeSnapshot()
        assert reg.name == "neutral_low_vol"
        assert reg.one_sided == "off"
        assert reg.fill_factor == Decimal("0.40")


# ── TradingSignal ────────────────────────────────────────────────────


class TestTradingSignal:
    def test_no_trade_factory(self):
        sig = TradingSignal.no_trade("flat_market")
        assert sig.family == "no_trade"
        assert sig.direction == "off"
        assert sig.conviction == _ZERO
        assert sig.reason == "flat_market"
        assert sig.levels == ()

    def test_signal_with_levels(self):
        levels = (
            SignalLevel(side="buy", spread_pct=Decimal("0.001"), size_quote=Decimal("100")),
            SignalLevel(side="sell", spread_pct=Decimal("0.001"), size_quote=Decimal("100")),
        )
        sig = TradingSignal(
            family="mm_grid",
            direction="both",
            conviction=Decimal("0.75"),
            levels=levels,
            metadata={"edge_bps": Decimal("5.5")},
        )
        assert len(sig.levels) == 2
        assert sig.levels[0].side == "buy"
        assert sig.metadata["edge_bps"] == Decimal("5.5")


# ── TelemetrySchema ──────────────────────────────────────────────────


class TestTelemetrySchema:
    def test_column_names(self):
        schema = TelemetrySchema(
            fields=(
                TelemetryField(name="pb_rsi", key="rsi", type="decimal", default=_ZERO),
                TelemetryField(name="pb_adx", key="adx", type="decimal", default=_ZERO),
            )
        )
        assert schema.column_names == ["pb_rsi", "pb_adx"]

    def test_extract_with_metadata(self):
        schema = TelemetrySchema(
            fields=(
                TelemetryField(name="score", key="signal_score", default=_ZERO),
                TelemetryField(name="side", key="direction", type="str", default="off"),
            )
        )
        result = schema.extract({"signal_score": Decimal("0.85"), "direction": "buy"})
        assert result == {"score": Decimal("0.85"), "side": "buy"}

    def test_extract_uses_defaults_for_missing_keys(self):
        schema = TelemetrySchema(
            fields=(
                TelemetryField(name="score", key="signal_score", default=_ZERO),
            )
        )
        result = schema.extract({})
        assert result == {"score": _ZERO}


# ── Orders and actions ───────────────────────────────────────────────


class TestOrders:
    def test_desk_order_with_barriers(self):
        order = DeskOrder(
            side="buy",
            order_type="limit",
            price=Decimal("65000"),
            amount_quote=Decimal("100"),
            stop_loss=Decimal("64000"),
            take_profit=Decimal("67000"),
            time_limit_s=3600,
        )
        assert order.stop_loss == Decimal("64000")
        assert order.take_profit == Decimal("67000")

    def test_desk_order_without_barriers(self):
        order = DeskOrder(
            side="sell",
            order_type="market",
            price=Decimal("65000"),
            amount_quote=Decimal("50"),
        )
        assert order.stop_loss is None
        assert order.take_profit is None
        assert order.time_limit_s is None

    def test_action_types_have_distinct_action_field(self):
        assert SubmitOrder().action == "submit"
        assert CancelOrder().action == "cancel"
        assert ModifyOrder().action == "modify"
        assert ClosePosition().action == "close_position"
        assert PartialReduce().action == "partial_reduce"


# ── RiskDecision ─────────────────────────────────────────────────────


class TestRiskDecision:
    def test_approve_factory(self):
        d = RiskDecision.approve("bot", daily_loss_pct=Decimal("0.001"))
        assert d.approved is True
        assert d.layer == "bot"
        assert d.metadata["daily_loss_pct"] == Decimal("0.001")

    def test_reject_factory(self):
        d = RiskDecision.reject("portfolio", "portfolio_breach")
        assert d.approved is False
        assert d.reason == "portfolio_breach"
        assert d.layer == "portfolio"

    def test_modify_factory(self):
        reduced = TradingSignal(family="mm_grid", direction="both", conviction=Decimal("0.5"))
        d = RiskDecision.modify("bot", reduced, reason="turnover_soft_cap")
        assert d.approved is True
        assert d.modified_signal is not None
        assert d.modified_signal.conviction == Decimal("0.5")
        assert d.reason == "turnover_soft_cap"


# ── Protocol checks ──────────────────────────────────────────────────


class TestProtocols:
    def test_strategy_signal_source_is_runtime_checkable(self):
        assert hasattr(StrategySignalSource, "__protocol_attrs__") or callable(
            getattr(StrategySignalSource, "__instancecheck__", None)
        )

    def test_execution_adapter_is_runtime_checkable(self):
        assert hasattr(ExecutionAdapter, "__protocol_attrs__") or callable(
            getattr(ExecutionAdapter, "__instancecheck__", None)
        )

    def test_risk_layer_is_runtime_checkable(self):
        assert hasattr(RiskLayer, "__protocol_attrs__") or callable(
            getattr(RiskLayer, "__instancecheck__", None)
        )

    def test_trading_desk_protocol_is_runtime_checkable(self):
        assert hasattr(TradingDeskProtocol, "__protocol_attrs__") or callable(
            getattr(TradingDeskProtocol, "__instancecheck__", None)
        )
