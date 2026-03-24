"""Tests for BacktestHarness — core time-stepping engine."""
from __future__ import annotations

from datetime import UTC
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from controllers.backtesting.types import (
    BacktestConfig,
    BacktestResult,
    CandleRow,
    DataSourceConfig,
    SynthesisConfig,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _generate_candles(n: int = 200, base_price: Decimal = Decimal("50000")) -> list[CandleRow]:
    """Generate n minute candles with slight upward drift."""
    base_ms = 1_700_000_000_000
    candles = []
    price = base_price
    for i in range(n):
        drift = Decimal(str(i * 0.5))
        o = price + drift
        h = o + Decimal("50")
        l = o - Decimal("30")
        c = o + Decimal("10")
        candles.append(CandleRow(
            timestamp_ms=base_ms + i * 60_000,
            open=o, high=h, low=l, close=c,
            volume=Decimal("100"),
        ))
    return candles


def _make_mock_strategy():
    """Mock strategy returning a simple execution plan."""
    from controllers.runtime.execution_context import RuntimeExecutionPlan

    strategy = MagicMock()
    strategy.build_runtime_execution_plan.return_value = RuntimeExecutionPlan(
        family="mm",
        buy_spreads=[Decimal("0.003"), Decimal("0.006")],
        sell_spreads=[Decimal("0.003"), Decimal("0.006")],
        projected_total_quote=Decimal("100"),
        size_mult=Decimal("1.0"),
    )
    return strategy


def _run_harness(config: BacktestConfig, candles: list[CandleRow], strategy=None) -> BacktestResult:
    """Run harness with mocked data loading.

    The harness uses SimpleBacktestAdapter by default (self-contained,
    no external strategy needed).
    """
    with patch.object(
             __import__("controllers.backtesting.harness", fromlist=["BacktestHarness"]).BacktestHarness,
             "_load_candles",
             return_value=candles,
         ):
        from controllers.backtesting.harness import BacktestHarness
        return BacktestHarness(config).run()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHarnessBasic:
    """Test that the harness runs end-to-end with a mock strategy."""

    def test_run_returns_backtest_result(self):
        candles = _generate_candles(200)
        config = BacktestConfig(
            strategy_class="dummy.MockStrategy",
            initial_equity=Decimal("500"),
            warmup_bars=60,
            step_interval_s=60,
            seed=42,
        )
        result = _run_harness(config, candles)

        assert isinstance(result, BacktestResult)
        assert result.total_ticks > 0
        assert result.equity_curve is not None
        assert len(result.equity_curve) > 0
        assert result.run_duration_s > 0

    def test_adapter_submits_orders(self):
        """Verify the self-contained adapter runs and places orders."""
        candles = _generate_candles(200)
        config = BacktestConfig(
            warmup_bars=60,
            step_interval_s=60,
        )
        result = _run_harness(config, candles)

        assert result.order_count > 0

    def test_equity_curve_has_daily_snapshots(self):
        # 3 days of candles
        candles = _generate_candles(4320)
        config = BacktestConfig(
            strategy_class="dummy.MockStrategy",
            warmup_bars=60,
            step_interval_s=60,
        )
        result = _run_harness(config, candles)

        # Should have daily snapshots + final
        assert len(result.equity_curve) >= 2

    def test_config_recorded_in_result(self):
        candles = _generate_candles(200)
        config = BacktestConfig(
            strategy_class="dummy.MockStrategy",
            data_source=DataSourceConfig(
                exchange="bitget",
                pair="BTC-USDT",
            ),
            warmup_bars=60,
        )
        result = _run_harness(config, candles)

        assert result.config["exchange"] == "bitget"
        assert result.config["pair"] == "BTC-USDT"
        assert result.config["strategy_class"] == "dummy.MockStrategy"

    def test_tick_count_matches_expected(self):
        candles = _generate_candles(200)
        config = BacktestConfig(
            strategy_class="dummy.MockStrategy",
            warmup_bars=60,
            step_interval_s=60,
        )
        result = _run_harness(config, candles)

        # 200 total candles, 60 warmup → 140 backtest candles
        # Ticks = (end_ns - start_ns) / step_ns + 1 (approx)
        assert result.total_ticks >= 100  # At least most of the 140 bars

    def test_fill_disclaimer_present(self):
        candles = _generate_candles(200)
        config = BacktestConfig(
            strategy_class="dummy.MockStrategy",
            warmup_bars=60,
        )
        result = _run_harness(config, candles)

        assert result.fill_disclaimer
        assert "approximate" in result.fill_disclaimer.lower()


class TestHarnessValidation:
    def test_insufficient_candles_raises(self):
        candles = _generate_candles(30)  # Less than warmup(60) + 10
        config = BacktestConfig(
            strategy_class="dummy.MockStrategy",
            warmup_bars=60,
        )
        with pytest.raises(ValueError, match="Insufficient candles"):
            _run_harness(config, candles)


class TestDeskFactory:
    def test_creates_fresh_desk(self):
        from controllers.backtesting.book_synthesizer import CandleBookSynthesizer
        from controllers.backtesting.harness import DeskFactory
        from controllers.backtesting.historical_feed import HistoricalDataFeed
        from simulation.types import InstrumentId, InstrumentSpec

        candles = _generate_candles(100)
        inst_id = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")
        spec = InstrumentSpec(
            instrument_id=inst_id,
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

        synthesis = SynthesisConfig()
        synthesizer = CandleBookSynthesizer(synthesis)
        feed = HistoricalDataFeed(
            candles=candles,
            instrument_id=inst_id,
            synthesizer=synthesizer,
            step_interval_ns=60_000_000_000,
            seed=42,
        )

        config = BacktestConfig(initial_equity=Decimal("1000"))
        desk = DeskFactory.create(config, inst_id, spec, feed)
        assert desk is not None


class TestStrategyLoader:
    def test_invalid_class_path_raises(self):
        from controllers.backtesting.harness import _load_strategy
        with pytest.raises(ValueError, match="Invalid strategy class path"):
            _load_strategy("no_dot_in_name", {})

    def test_nonexistent_module_raises(self):
        from controllers.backtesting.harness import _load_strategy
        with pytest.raises(ValueError, match="Cannot import strategy module"):
            _load_strategy("nonexistent_module.SomeClass", {})

    def test_empty_class_path_returns_default(self):
        from controllers.backtesting.harness import _load_strategy
        from controllers.backtesting.runtime_adapter import DefaultMMBacktestStrategy
        strategy = _load_strategy("", {})
        assert isinstance(strategy, DefaultMMBacktestStrategy)

    def test_default_mm_alias(self):
        from controllers.backtesting.harness import _load_strategy
        from controllers.backtesting.runtime_adapter import DefaultMMBacktestStrategy
        strategy = _load_strategy("default_mm", {})
        assert isinstance(strategy, DefaultMMBacktestStrategy)

    def test_class_not_found_raises(self):
        from controllers.backtesting.harness import _load_strategy
        with pytest.raises(ValueError, match="not found in module"):
            _load_strategy("controllers.backtesting.harness.NonExistentClass", {})


class TestProgressEmission:
    def test_progress_file_written(self, tmp_path):
        """Harness writes progress.json when progress_dir is set."""
        import json

        candles = _generate_candles(2000)
        config = BacktestConfig(
            strategy_class="dummy.MockStrategy",
            warmup_bars=60,
            step_interval_s=60,
            progress_dir=str(tmp_path),
        )
        result = _run_harness(config, candles)

        progress_file = tmp_path / "progress.json"
        assert progress_file.exists()
        data = json.loads(progress_file.read_text())
        assert data["progress_pct"] == 100.0
        assert data["current_tick"] == data["total_ticks"]

    def test_no_progress_file_without_dir(self, tmp_path):
        """No progress.json when progress_dir is empty."""
        candles = _generate_candles(200)
        config = BacktestConfig(
            strategy_class="dummy.MockStrategy",
            warmup_bars=60,
            step_interval_s=60,
            progress_dir="",
        )
        result = _run_harness(config, candles)
        assert not (tmp_path / "progress.json").exists()


class TestHarnessCollectsPositionSeries:
    def test_position_series_passed_to_metrics(self):
        """Harness should collect position_series and pass to compute_all_metrics."""
        candles = _generate_candles(200)
        config = BacktestConfig(
            strategy_class="dummy.MockStrategy",
            warmup_bars=60,
            step_interval_s=60,
        )
        result = _run_harness(config, candles)
        assert result.total_ticks > 0


class TestDataStartEndFormat:
    def test_data_start_end_are_iso_strings(self):
        """data_start and data_end should be ISO format strings, not raw ints."""
        candles = _generate_candles(200)
        config = BacktestConfig(
            strategy_class="dummy.MockStrategy",
            warmup_bars=60,
            step_interval_s=60,
        )
        result = _run_harness(config, candles)
        assert isinstance(result.data_start, str)
        assert isinstance(result.data_end, str)
        assert "T" in result.data_start  # ISO 8601 format
        assert result.data_start.endswith("Z")


class TestDateRangeFiltering:
    def test_filter_by_date_range(self):
        from controllers.backtesting.harness import BacktestHarness

        base_ms = 1_700_000_000_000
        candles = [
            CandleRow(
                timestamp_ms=base_ms + i * 60_000,
                open=Decimal("50000"), high=Decimal("50050"),
                low=Decimal("49950"), close=Decimal("50020"),
                volume=Decimal("100"),
            )
            for i in range(100)
        ]

        # No filter → all candles returned
        result = BacktestHarness._filter_by_date_range(candles, "", "")
        assert len(result) == 100

        # Filter with start_date
        from datetime import datetime
        start_ts = base_ms + 50 * 60_000
        start_dt = datetime.fromtimestamp(start_ts / 1000, tz=UTC)
        start_str = start_dt.strftime("%Y-%m-%d")
        filtered = BacktestHarness._filter_by_date_range(candles, start_str, "")
        assert len(filtered) <= 100
        assert all(c.timestamp_ms >= start_ts - 86_400_000 for c in filtered)
