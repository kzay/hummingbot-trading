"""Integration tests for TradingDesk — full tick loop."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from controllers.runtime.v3.data_surface import KernelDataSurface
from controllers.runtime.v3.orders import DeskOrder
from controllers.runtime.v3.risk.bot_gate import BotRiskConfig, BotRiskGate
from controllers.runtime.v3.risk.desk_risk_gate import DeskRiskGate
from controllers.runtime.v3.risk.portfolio_gate import PortfolioRiskGate
from controllers.runtime.v3.risk.signal_gate import SignalRiskGate
from controllers.runtime.v3.signals import (
    SignalLevel,
    TelemetrySchema,
    TradingSignal,
)
from controllers.runtime.v3.trading_desk import TradingDesk
from controllers.runtime.v3.types import MarketSnapshot, PositionSnapshot

_ZERO = Decimal("0")


class FakeStrategy:
    """A simple strategy that always returns a directional buy signal."""

    def __init__(self, warmup: int = 0):
        self._warmup = warmup
        self.evaluate_count = 0

    def evaluate(self, snapshot: MarketSnapshot) -> TradingSignal:
        self.evaluate_count += 1
        if snapshot.mid <= _ZERO:
            return TradingSignal.no_trade("no_mid")
        return TradingSignal(
            family="directional",
            direction="buy",
            conviction=Decimal("0.80"),
            target_net_base_pct=Decimal("0.05"),
            levels=(
                SignalLevel(side="buy", spread_pct=Decimal("0.001"), size_quote=Decimal("100"), level_id="L1"),
            ),
            metadata={"custom_score": Decimal("0.9")},
            reason="test_signal",
        )

    def warmup_bars_required(self) -> int:
        return self._warmup

    def telemetry_schema(self) -> TelemetrySchema:
        return TelemetrySchema()


class NoTradeStrategy:
    """A strategy that always returns no_trade."""

    def evaluate(self, snapshot: MarketSnapshot) -> TradingSignal:
        return TradingSignal.no_trade("always_off")

    def warmup_bars_required(self) -> int:
        return 0

    def telemetry_schema(self) -> TelemetrySchema:
        return TelemetrySchema()


def _make_kernel_mock(bars: int = 250, mid: Decimal = Decimal("65000")):
    """Minimal kernel mock for KernelDataSurface."""
    k = MagicMock()
    k._tick_count = 1
    k._last_mid = mid
    k._last_book_bid = mid - Decimal("50")
    k._last_book_ask = mid + Decimal("50")
    k._last_book_bid_size = Decimal("1")
    k._last_book_ask_size = Decimal("1")
    k._ob_imbalance = _ZERO
    k._book_stale_since_ts = 0
    k._position_base = _ZERO
    k._base_pct_net = _ZERO
    k._base_pct_gross = _ZERO
    k._avg_entry_price = _ZERO
    k._is_perp = False
    k._equity_quote = Decimal("5000")
    k._daily_equity_open = Decimal("5000")
    k._daily_equity_peak = Decimal("5000")
    k._traded_notional_today = _ZERO
    k._active_regime = "neutral_low_vol"
    k._band_pct_ewma = _ZERO
    k._regime_ema_value = _ZERO
    k._regime_atr_value = _ZERO
    k._funding_rate = _ZERO
    k._mark_price = _ZERO
    k._ml_direction_hint = ""
    k._ml_direction_hint_confidence = 0.0
    k._last_external_model_version = ""
    k._external_regime_override = None
    k._resolved_specs = {}

    pb = MagicMock()
    pb.ema = lambda p: mid if p == 20 else None
    pb.atr = lambda p: Decimal("350") if p == 14 else None
    pb.rsi = lambda p: Decimal("50") if p == 14 else None
    pb.adx = lambda p: Decimal("25") if p == 14 else None
    # bars_available as int
    pb.bars_available = bars
    k._price_buffer = pb

    cfg = MagicMock()
    cfg.connector_name = "bitget_perpetual"
    cfg.trading_pair = "BTC-USDT"
    cfg.leverage = 1
    for attr in ["total_amount_quote", "buy_spreads", "sell_spreads",
                 "executor_refresh_time", "stop_loss", "take_profit",
                 "time_limit", "min_net_edge_bps", "edge_resume_bps",
                 "max_daily_loss_pct_hard", "max_drawdown_pct_hard",
                 "max_daily_turnover_x_hard"]:
        setattr(cfg, attr, None)
    k.config = cfg

    return k


def _make_desk(
    strategy=None,
    kernel_mock=None,
    execution_family: str = "directional",
    risk_gate: DeskRiskGate | None = None,
    submitter=None,
) -> TradingDesk:
    if strategy is None:
        strategy = FakeStrategy()
    if kernel_mock is None:
        kernel_mock = _make_kernel_mock()
    surface = KernelDataSurface(kernel_mock)
    if risk_gate is None:
        risk_gate = DeskRiskGate(
            portfolio=PortfolioRiskGate(),
            bot=BotRiskGate(),
            signal=SignalRiskGate(),
        )
    return TradingDesk(
        strategy=strategy,
        data_surface=surface,
        risk_gate=risk_gate,
        execution_family=execution_family,
        order_submitter=submitter,
        instance_name="test_bot",
    )


class TestTickLoop:
    def test_single_tick_executes_all_phases(self):
        strategy = FakeStrategy()
        desk = _make_desk(strategy=strategy)
        desk.tick()

        assert desk.tick_count == 1
        assert strategy.evaluate_count == 1
        assert desk.last_signal.family == "directional"
        assert desk.last_decision.approved is True

    def test_multiple_ticks(self):
        strategy = FakeStrategy()
        kernel = _make_kernel_mock()
        desk = _make_desk(strategy=strategy, kernel_mock=kernel)

        for i in range(5):
            kernel._tick_count = i + 1
            desk.tick()

        assert desk.tick_count == 5
        assert strategy.evaluate_count == 5

    def test_no_trade_signal_does_not_submit(self):
        submitter = MagicMock()
        desk = _make_desk(strategy=NoTradeStrategy(), submitter=submitter)
        desk.tick()

        submitter.submit.assert_not_called()

    def test_orders_submitted_on_approval(self):
        submitter = MagicMock()
        desk = _make_desk(submitter=submitter)
        desk.tick()

        submitter.submit.assert_called()


class TestWarmup:
    def test_skips_signal_during_warmup(self):
        strategy = FakeStrategy(warmup=500)
        kernel = _make_kernel_mock(bars=100)
        desk = _make_desk(strategy=strategy, kernel_mock=kernel)

        desk.tick()
        assert strategy.evaluate_count == 0  # Not evaluated during warmup

    def test_starts_after_warmup_complete(self):
        strategy = FakeStrategy(warmup=200)
        kernel = _make_kernel_mock(bars=250)
        desk = _make_desk(strategy=strategy, kernel_mock=kernel)

        desk.tick()
        assert strategy.evaluate_count == 1  # Evaluated after warmup


class TestRiskRejection:
    def test_risk_rejection_blocks_execution(self):
        submitter = MagicMock()
        bot_gate = BotRiskGate(BotRiskConfig(max_daily_loss_pct_hard=Decimal("0")))
        risk = DeskRiskGate(bot=bot_gate)

        kernel = _make_kernel_mock()
        # Set daily loss above 0 to trigger rejection
        kernel._daily_equity_open = Decimal("5100")
        kernel._equity_quote = Decimal("5000")

        desk = _make_desk(
            submitter=submitter,
            kernel_mock=kernel,
            risk_gate=risk,
        )
        desk.tick()

        assert desk.last_decision.approved is False
        submitter.submit.assert_not_called()


class TestOrderLifecycle:
    def test_cancel_order(self):
        desk = _make_desk()
        desk.tick()  # Creates some orders

        if desk.open_order_count > 0:
            oid = list(desk._open_orders.keys())[0]
            assert desk.cancel_order(oid) is True
            assert oid not in desk._open_orders

    def test_cancel_all(self):
        desk = _make_desk()
        desk.tick()

        count = desk.cancel_all()
        assert desk.open_order_count == 0

    def test_cancel_nonexistent_returns_false(self):
        desk = _make_desk()
        assert desk.cancel_order("nonexistent_id") is False

    def test_submit_orders_returns_ids(self):
        desk = _make_desk()
        orders = [
            DeskOrder(side="buy", order_type="limit", price=Decimal("64900"), amount_quote=Decimal("100")),
            DeskOrder(side="sell", order_type="limit", price=Decimal("65100"), amount_quote=Decimal("100")),
        ]
        ids = desk.submit_orders(orders)
        assert len(ids) == 2
        assert desk.open_order_count == 2


class TestAdapterSelection:
    def test_mm_grid_family(self):
        desk = _make_desk(execution_family="mm_grid")
        assert desk._adapter.__class__.__name__ == "MMGridExecutionAdapter"

    def test_directional_family(self):
        desk = _make_desk(execution_family="directional")
        assert desk._adapter.__class__.__name__ == "DirectionalExecutionAdapter"

    def test_hybrid_family(self):
        desk = _make_desk(execution_family="hybrid")
        assert desk._adapter.__class__.__name__ == "HybridExecutionAdapter"

    def test_unknown_family_raises(self):
        with pytest.raises(ValueError, match="Unknown execution family"):
            _make_desk(execution_family="unknown")
