"""Tests for v3 telemetry emitter."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from controllers.runtime.v3.risk_types import RiskDecision
from controllers.runtime.v3.signals import TelemetryField, TelemetrySchema, TradingSignal
from controllers.runtime.v3.telemetry import BASE_COLUMNS, TelemetryEmitter
from controllers.runtime.v3.types import (
    EquitySnapshot,
    MarketSnapshot,
    OrderBookSnapshot,
    PositionSnapshot,
    RegimeSnapshot,
)

_ZERO = Decimal("0")


def _snap(ts_ms: int = 1000000) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp_ms=ts_ms,
        mid=Decimal("65000"),
        order_book=OrderBookSnapshot(
            best_bid=Decimal("64990"),
            best_ask=Decimal("65010"),
            spread_pct=Decimal("0.0003"),
        ),
        equity=EquitySnapshot(
            equity_quote=Decimal("5000"),
            daily_pnl_quote=Decimal("50"),
            daily_loss_pct=_ZERO,
            max_drawdown_pct=Decimal("0.005"),
            daily_open_equity=Decimal("4950"),
            daily_turnover_x=Decimal("3"),
        ),
        position=PositionSnapshot(
            base_amount=Decimal("0.01"),
            net_base_pct=Decimal("0.05"),
        ),
        regime=RegimeSnapshot(name="up"),
    )


def _signal(**kwargs) -> TradingSignal:
    defaults = dict(
        family="directional",
        direction="buy",
        conviction=Decimal("0.85"),
        reason="pullback_detected",
        metadata={"pb_rsi": Decimal("42"), "pb_score": Decimal("0.8")},
    )
    defaults.update(kwargs)
    return TradingSignal(**defaults)


def _schema() -> TelemetrySchema:
    return TelemetrySchema(fields=(
        TelemetryField(name="pb_rsi", key="pb_rsi", type="decimal", default=_ZERO),
        TelemetryField(name="pb_score", key="pb_score", type="decimal", default=_ZERO),
    ))


class TestColumnDiscovery:
    def test_columns_include_base_and_strategy(self):
        emitter = TelemetryEmitter(strategy_schema=_schema())
        assert "mid" in emitter.columns
        assert "pb_rsi" in emitter.columns
        assert "pb_score" in emitter.columns
        assert len(emitter.columns) == len(BASE_COLUMNS) + 2

    def test_empty_schema_only_base_columns(self):
        emitter = TelemetryEmitter(strategy_schema=TelemetrySchema())
        assert emitter.columns == BASE_COLUMNS


class TestEmitTick:
    def test_row_contains_all_fields(self):
        emitter = TelemetryEmitter(strategy_schema=_schema())
        decision = RiskDecision.approve("desk")
        row = emitter.emit_tick(_snap(), _signal(), decision)

        assert row["mid"] == Decimal("65000")
        assert row["regime"] == "up"
        assert row["signal_family"] == "directional"
        assert row["signal_conviction"] == Decimal("0.85")
        assert row["risk_approved"] is True
        assert row["pb_rsi"] == Decimal("42")
        assert row["pb_score"] == Decimal("0.8")

    def test_missing_metadata_uses_defaults(self):
        emitter = TelemetryEmitter(strategy_schema=_schema())
        sig = _signal(metadata={})  # No pb_rsi or pb_score
        decision = RiskDecision.approve("desk")
        row = emitter.emit_tick(_snap(), sig, decision)

        assert row["pb_rsi"] == _ZERO
        assert row["pb_score"] == _ZERO

    def test_csv_writer_called(self):
        csv = MagicMock()
        emitter = TelemetryEmitter(strategy_schema=_schema(), csv_writer=csv)
        emitter.emit_tick(_snap(), _signal(), RiskDecision.approve("desk"))
        csv.log_tick.assert_called_once()

    def test_redis_publisher_called(self):
        redis = MagicMock()
        emitter = TelemetryEmitter(strategy_schema=_schema(), redis_publisher=redis)
        emitter.emit_tick(_snap(), _signal(), RiskDecision.approve("desk"))
        redis.publish_snapshot.assert_called_once()

    def test_csv_error_does_not_raise(self):
        csv = MagicMock()
        csv.log_tick.side_effect = IOError("disk full")
        emitter = TelemetryEmitter(strategy_schema=_schema(), csv_writer=csv)
        # Should not raise
        row = emitter.emit_tick(_snap(), _signal(), RiskDecision.approve("desk"))
        assert row["mid"] == Decimal("65000")


class TestEmitFill:
    def test_fill_event_structure(self):
        emitter = TelemetryEmitter(strategy_schema=_schema(), instance_name="bot7")
        fill = emitter.emit_fill(
            order_id="ord-123",
            side="buy",
            price=Decimal("65000"),
            amount=Decimal("0.01"),
            fee=Decimal("0.065"),
            slippage_bps=Decimal("2.5"),
            realized_pnl=Decimal("3.50"),
            strategy_name="bot7_pullback",
        )
        assert fill["order_id"] == "ord-123"
        assert fill["side"] == "buy"
        assert fill["instance_name"] == "bot7"
        assert fill["strategy_name"] == "bot7_pullback"

    def test_fill_increments_daily_counters(self):
        emitter = TelemetryEmitter(strategy_schema=_schema())
        emitter.emit_fill(order_id="1", side="buy", price=Decimal("100"), amount=Decimal("1"), fee=_ZERO)
        emitter.emit_fill(order_id="2", side="sell", price=Decimal("200"), amount=Decimal("2"), fee=_ZERO)
        assert emitter._daily_fill_count == 2
        assert emitter._daily_turnover_quote == Decimal("500")  # 100*1 + 200*2


class TestDailyRollover:
    def test_rollover_resets_counters(self):
        csv = MagicMock()
        emitter = TelemetryEmitter(strategy_schema=_schema(), csv_writer=csv)
        decision = RiskDecision.approve("desk")

        # Day 1
        day1_ms = 86_400_000 * 100  # some day
        emitter.emit_tick(_snap(ts_ms=day1_ms), _signal(), decision)
        emitter.emit_fill(order_id="1", side="buy", price=Decimal("100"), amount=Decimal("1"), fee=_ZERO)
        assert emitter._daily_fill_count == 1

        # Day 2
        day2_ms = day1_ms + 86_400_000
        emitter.emit_tick(_snap(ts_ms=day2_ms), _signal(), decision)
        # Counters should be reset
        assert emitter._daily_fill_count == 0
        assert emitter._daily_turnover_quote == _ZERO
        # Daily summary should have been written
        csv.log_daily.assert_called_once()

    def test_emit_daily_summary(self):
        emitter = TelemetryEmitter(strategy_schema=_schema(), instance_name="bot1")
        summary = emitter.emit_daily_summary(_snap())
        assert summary["open_equity"] == str(Decimal("4950"))
        assert summary["close_equity"] == str(Decimal("5000"))
        assert summary["instance_name"] == "bot1"
