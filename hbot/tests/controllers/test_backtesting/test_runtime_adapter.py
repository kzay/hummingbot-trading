"""Tests for BacktestRuntimeAdapter — regime detection, data context, order lifecycle."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from controllers.backtesting.runtime_adapter import (
    BacktestRuntimeAdapter,
    RuntimeAdapterConfig,
)
from controllers.backtesting.types import CandleRow
from simulation.types import (
    BookLevel,
    InstrumentId,
    InstrumentSpec,
    OrderBookSnapshot,
)
from controllers.runtime.data_context import RuntimeDataContext
from controllers.runtime.execution_context import RuntimeExecutionPlan

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def instrument_id() -> InstrumentId:
    return InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")


@pytest.fixture
def instrument_spec(instrument_id) -> InstrumentSpec:
    return InstrumentSpec(
        instrument_id=instrument_id,
        price_precision=2,
        size_precision=4,
        price_increment=Decimal("0.01"),
        size_increment=Decimal("0.0001"),
        min_quantity=Decimal("0.0001"),
        min_notional=Decimal("5"),
        max_quantity=Decimal("1000"),
        maker_fee_rate=Decimal("0.0002"),
        taker_fee_rate=Decimal("0.0006"),
        margin_init=Decimal("0.10"),
        margin_maint=Decimal("0.05"),
        leverage_max=10,
        funding_interval_s=28800,
    )


def _make_strategy():
    """Create a mock strategy implementing StrategyRuntimeHooks."""
    strategy = MagicMock()
    strategy.build_runtime_execution_plan.return_value = RuntimeExecutionPlan(
        family="mm",
        buy_spreads=[Decimal("0.002"), Decimal("0.004")],
        sell_spreads=[Decimal("0.002"), Decimal("0.004")],
        projected_total_quote=Decimal("100"),
        size_mult=Decimal("1.0"),
    )
    return strategy


def _make_desk():
    """Create a mock PaperDesk."""
    desk = MagicMock()
    desk.cancel_all.return_value = []
    desk.submit_order.return_value = MagicMock()
    desk._portfolio = MagicMock()
    desk._portfolio.equity_quote.return_value = Decimal("500")
    return desk


def _make_warmup_candles(n: int = 60) -> list[CandleRow]:
    """Generate n warmup candles."""
    base_ms = 1_700_000_000_000
    return [
        CandleRow(
            timestamp_ms=base_ms + i * 60_000,
            open=Decimal("50000") + Decimal(str(i)),
            high=Decimal("50050") + Decimal(str(i)),
            low=Decimal("49950") + Decimal(str(i)),
            close=Decimal("50010") + Decimal(str(i)),
            volume=Decimal("100"),
        )
        for i in range(n)
    ]


def _make_book(
    mid: Decimal = Decimal("50000"),
    inst_id: InstrumentId | None = None,
) -> OrderBookSnapshot:
    if inst_id is None:
        inst_id = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")
    spread = Decimal("0.5")
    return OrderBookSnapshot(
        instrument_id=inst_id,
        bids=(BookLevel(price=mid - spread, size=Decimal("1")),),
        asks=(BookLevel(price=mid + spread, size=Decimal("1")),),
        timestamp_ns=1_700_000_000_000_000_000,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWarmup:
    def test_seed_bars(self, instrument_id, instrument_spec):
        adapter = BacktestRuntimeAdapter(
            strategy=_make_strategy(),
            desk=_make_desk(),
            instrument_id=instrument_id,
            instrument_spec=instrument_spec,
            config=RuntimeAdapterConfig(min_warmup_bars=30),
        )
        candles = _make_warmup_candles(60)
        seeded = adapter.warmup(candles)
        assert seeded >= 30  # Should seed at least min_warmup_bars

    def test_empty_warmup(self, instrument_id, instrument_spec):
        adapter = BacktestRuntimeAdapter(
            strategy=_make_strategy(),
            desk=_make_desk(),
            instrument_id=instrument_id,
            instrument_spec=instrument_spec,
            config=RuntimeAdapterConfig(),
        )
        assert adapter.warmup([]) == 0


class TestTickLifecycle:
    def test_tick_before_warmup_returns_none(self, instrument_id, instrument_spec):
        """Before warmup buffer ready, tick should return None (no orders)."""
        adapter = BacktestRuntimeAdapter(
            strategy=_make_strategy(),
            desk=_make_desk(),
            instrument_id=instrument_id,
            instrument_spec=instrument_spec,
            config=RuntimeAdapterConfig(min_warmup_bars=30),
        )
        # Tick without warmup
        result = adapter.tick(
            now_s=1_700_000_000.0,
            mid=Decimal("50000"),
            book=_make_book(),
            equity_quote=Decimal("500"),
            position_base=Decimal("0"),
        )
        assert result is None

    def test_tick_after_warmup_returns_plan(self, instrument_id, instrument_spec):
        """After warmup, tick should invoke strategy and return execution plan."""
        strategy = _make_strategy()
        desk = _make_desk()
        adapter = BacktestRuntimeAdapter(
            strategy=strategy,
            desk=desk,
            instrument_id=instrument_id,
            instrument_spec=instrument_spec,
            config=RuntimeAdapterConfig(min_warmup_bars=30),
        )

        # Warmup
        adapter.warmup(_make_warmup_candles(60))

        # Tick
        now_s = 1_700_000_000.0 + 3600 + 60  # Well past warmup
        plan = adapter.tick(
            now_s=now_s,
            mid=Decimal("50000"),
            book=_make_book(),
            equity_quote=Decimal("500"),
            position_base=Decimal("0"),
        )

        assert plan is not None
        assert len(plan.buy_spreads) == 2
        assert len(plan.sell_spreads) == 2
        # Strategy was called
        strategy.build_runtime_execution_plan.assert_called_once()
        # Desk operations: cancel + submit orders
        desk.cancel_all.assert_called()
        assert desk.submit_order.call_count == 4  # 2 buy + 2 sell

    def test_data_context_has_all_fields(self, instrument_id, instrument_spec):
        """RuntimeDataContext passed to strategy should have all required fields."""
        strategy = _make_strategy()
        adapter = BacktestRuntimeAdapter(
            strategy=strategy,
            desk=_make_desk(),
            instrument_id=instrument_id,
            instrument_spec=instrument_spec,
            config=RuntimeAdapterConfig(min_warmup_bars=30),
        )
        adapter.warmup(_make_warmup_candles(60))

        now_s = 1_700_000_000.0 + 3600 + 60
        adapter.tick(
            now_s=now_s,
            mid=Decimal("50000"),
            book=_make_book(),
            equity_quote=Decimal("500"),
            position_base=Decimal("0.01"),
        )

        # Inspect the data_context passed to strategy
        call_args = strategy.build_runtime_execution_plan.call_args
        data_context = call_args[0][0]
        assert isinstance(data_context, RuntimeDataContext)
        assert data_context.mid == Decimal("50000")
        assert data_context.equity_quote == Decimal("500")
        assert data_context.regime_name in {"neutral_low_vol", "neutral_high_vol", "up", "down", "shock"}
        assert data_context.regime_spec is not None
        assert data_context.spread_state is not None
        assert data_context.market is not None


class TestRegimeDetection:
    def test_regime_starts_neutral(self, instrument_id, instrument_spec):
        adapter = BacktestRuntimeAdapter(
            strategy=_make_strategy(),
            desk=_make_desk(),
            instrument_id=instrument_id,
            instrument_spec=instrument_spec,
            config=RuntimeAdapterConfig(),
        )
        assert adapter.regime_name == "neutral_low_vol"


class TestFillNotionalTracking:
    def test_record_fill_notional(self, instrument_id, instrument_spec):
        adapter = BacktestRuntimeAdapter(
            strategy=_make_strategy(),
            desk=_make_desk(),
            instrument_id=instrument_id,
            instrument_spec=instrument_spec,
            config=RuntimeAdapterConfig(),
        )
        assert adapter._traded_notional_today == Decimal("0")
        adapter.record_fill_notional(Decimal("1000"))
        assert adapter._traded_notional_today == Decimal("1000")
        adapter.record_fill_notional(Decimal("500"))
        assert adapter._traded_notional_today == Decimal("1500")

    def test_last_submitted_count_after_tick(self, instrument_id, instrument_spec):
        adapter = BacktestRuntimeAdapter(
            strategy=_make_strategy(),
            desk=_make_desk(),
            instrument_id=instrument_id,
            instrument_spec=instrument_spec,
            config=RuntimeAdapterConfig(min_warmup_bars=30),
        )
        adapter.warmup(_make_warmup_candles(60))

        now_s = 1_700_000_000.0 + 3600 + 60
        adapter.tick(
            now_s=now_s,
            mid=Decimal("50000"),
            book=_make_book(),
            equity_quote=Decimal("500"),
            position_base=Decimal("0"),
        )
        assert adapter.last_submitted_count == 4  # 2 buy + 2 sell from mock


class TestPriceBufferIntegration:
    def test_candle_warmup_feeds_ema_atr(self, instrument_id, instrument_spec):
        """After warmup, PriceBuffer should have valid EMA/ATR."""
        adapter = BacktestRuntimeAdapter(
            strategy=_make_strategy(),
            desk=_make_desk(),
            instrument_id=instrument_id,
            instrument_spec=instrument_spec,
            config=RuntimeAdapterConfig(ema_period=20, atr_period=14, min_warmup_bars=30),
        )
        adapter.warmup(_make_warmup_candles(60))

        buf = adapter.price_buffer
        assert buf.ready(30)
        assert buf.ema(20) is not None
        assert buf.atr(14) is not None
        assert buf.band_pct(14) is not None

        ema = buf.ema(20)
        # EMA should be near the candle close values (~50050)
        assert Decimal("49000") < ema < Decimal("51000")
