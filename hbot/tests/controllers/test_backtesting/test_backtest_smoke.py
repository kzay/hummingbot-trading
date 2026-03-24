"""Smoke test: run a minimal 100-bar backtest as CI gate.

This test validates the full harness pipeline (feed → desk → adapter → strategy)
without requiring pandas/pyarrow by mocking the data loading layer.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from controllers.backtesting.types import (
    BacktestConfig,
    BacktestResult,
    CandleRow,
)
from controllers.runtime.execution_context import RuntimeExecutionPlan


def _candles(n: int = 120) -> list[CandleRow]:
    base_ms = 1_700_000_000_000
    return [
        CandleRow(
            timestamp_ms=base_ms + i * 60_000,
            open=Decimal("50000") + Decimal(str(i)),
            high=Decimal("50060") + Decimal(str(i)),
            low=Decimal("49950") + Decimal(str(i)),
            close=Decimal("50010") + Decimal(str(i)),
            volume=Decimal("80"),
        )
        for i in range(n)
    ]


def _strategy():
    s = MagicMock()
    s.build_runtime_execution_plan.return_value = RuntimeExecutionPlan(
        family="mm",
        buy_spreads=[Decimal("0.003")],
        sell_spreads=[Decimal("0.003")],
        projected_total_quote=Decimal("50"),
        size_mult=Decimal("1.0"),
    )
    return s


def test_100_bar_smoke():
    """CI gate: full harness runs 100+ bars without error."""
    candles = _candles(120)
    config = BacktestConfig(
        strategy_class="dummy.Smoke",
        warmup_bars=20,
        step_interval_s=60,
        seed=1,
    )

    from controllers.backtesting.harness import BacktestHarness

    with patch("controllers.backtesting.harness._load_strategy", return_value=_strategy()), \
         patch.object(BacktestHarness, "_load_candles", return_value=candles):
        result = BacktestHarness(config).run()

    assert isinstance(result, BacktestResult)
    assert result.total_ticks >= 80
    assert result.run_duration_s < 30  # Should be fast
    assert result.equity_curve  # At least one snapshot
    assert result.fill_disclaimer  # Always present
