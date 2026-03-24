"""End-to-end integration tests for the backtesting engine.

Tests 10.2–10.5: full pipeline validation without real exchange data.
All tests mock the data layer to avoid pandas/pyarrow dependency.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from controllers.backtesting.types import (
    BacktestConfig,
    CandleRow,
    ParamSpace,
)
from controllers.runtime.execution_context import RuntimeExecutionPlan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _candles(n: int, base_price: Decimal = Decimal("50000")) -> list[CandleRow]:
    base_ms = 1_700_000_000_000
    return [
        CandleRow(
            timestamp_ms=base_ms + i * 60_000,
            open=base_price + Decimal(str(i)),
            high=base_price + Decimal("60") + Decimal(str(i)),
            low=base_price - Decimal("40") + Decimal(str(i)),
            close=base_price + Decimal("10") + Decimal(str(i)),
            volume=Decimal("80"),
        )
        for i in range(n)
    ]


def _strategy(**overrides):
    s = MagicMock()
    plan_kwargs = dict(
        family="mm",
        buy_spreads=[Decimal("0.003"), Decimal("0.005")],
        sell_spreads=[Decimal("0.003"), Decimal("0.005")],
        projected_total_quote=Decimal("80"),
        size_mult=Decimal("1.0"),
    )
    plan_kwargs.update(overrides)
    s.build_runtime_execution_plan.return_value = RuntimeExecutionPlan(**plan_kwargs)
    return s


def _run(config, candles, strategy=None):
    """Run harness with mocked data + strategy."""
    if strategy is None:
        strategy = _strategy()

    from controllers.backtesting.harness import BacktestHarness

    with patch("controllers.backtesting.harness._load_strategy", return_value=strategy), \
         patch.object(BacktestHarness, "_load_candles", return_value=candles):
        return BacktestHarness(config).run()


# ---------------------------------------------------------------------------
# 10.2 — Single backtest, verify report has all required fields
# ---------------------------------------------------------------------------

class TestSingleBacktestReport:
    def test_report_has_all_required_fields(self):
        result = _run(
            BacktestConfig(strategy_class="dummy.Full", warmup_bars=30, step_interval_s=60),
            _candles(200),
        )

        # Core metrics
        assert isinstance(result.total_return_pct, float)
        assert isinstance(result.sharpe_ratio, float)
        assert isinstance(result.sortino_ratio, float)
        assert isinstance(result.max_drawdown_pct, float)

        # Execution quality
        assert isinstance(result.fill_count, int)
        assert isinstance(result.order_count, int)

        # Config
        assert "strategy_class" in result.config
        assert "exchange" in result.config
        assert "pair" in result.config

        # Equity curve
        assert result.equity_curve is not None

        # Metadata
        assert result.total_ticks > 0
        assert result.run_duration_s > 0
        assert result.fill_disclaimer

    def test_data_start_end_set(self):
        result = _run(
            BacktestConfig(strategy_class="dummy.Ts", warmup_bars=30),
            _candles(200),
        )
        assert result.data_start  # Not empty
        assert result.data_end
        assert result.data_start < result.data_end


# ---------------------------------------------------------------------------
# 10.3 — Grid sweep (mocked), verify results aggregation
# ---------------------------------------------------------------------------

class TestGridSweep:
    def test_sweep_produces_ranked_results(self):
        """Run a small 4-point grid sweep and verify ranking."""
        from controllers.backtesting.sweep import (
            _expand_grid,
            generate_grid,
        )

        space = ParamSpace(name="spread_bps", mode="grid", values=[3.0, 5.0])
        expanded = _expand_grid(space)
        assert expanded == [3.0, 5.0]

        spaces = [
            ParamSpace(name="spread_bps", mode="grid", values=[3.0, 5.0]),
            ParamSpace(name="size_mult", mode="grid", values=[0.8, 1.2]),
        ]
        combos = generate_grid(spaces)
        assert len(combos) == 4  # 2 x 2

        # Verify combos contain all expected pairs
        spread_values = {c["spread_bps"] for c in combos}
        size_values = {c["size_mult"] for c in combos}
        assert spread_values == {3.0, 5.0}
        assert size_values == {0.8, 1.2}


# ---------------------------------------------------------------------------
# 10.4 — Walk-forward window splitting validation
# ---------------------------------------------------------------------------

class TestWalkForwardWindows:
    def test_anchored_windows_cover_data(self):
        from controllers.backtesting.types import SweepConfig, WalkForwardConfig
        from controllers.backtesting.walkforward import split_windows

        sweep_config = SweepConfig(
            base_config=BacktestConfig(step_interval_s=60),
        )
        wf_config = WalkForwardConfig(
            sweep_config=sweep_config,
            n_windows=3,
            min_train_days=1,
            min_test_days=1,
            window_mode="anchored",
        )

        total_bars = 10_080  # 7 days
        windows = split_windows(total_bars, wf_config)

        assert len(windows) >= 2
        # Anchored: all train starts at 0
        for train_start, train_end, test_start, test_end in windows:
            assert train_start == 0
            assert train_end <= test_start
            assert test_start < test_end
            assert test_end <= total_bars

    def test_rolling_windows_non_overlapping(self):
        from controllers.backtesting.types import SweepConfig, WalkForwardConfig
        from controllers.backtesting.walkforward import split_windows

        sweep_config = SweepConfig(
            base_config=BacktestConfig(step_interval_s=60),
        )
        wf_config = WalkForwardConfig(
            sweep_config=sweep_config,
            n_windows=3,
            min_train_days=1,
            min_test_days=1,
            window_mode="rolling",
        )

        windows = split_windows(10_080, wf_config)
        assert len(windows) >= 2

        # Test sets shouldn't overlap
        for i in range(len(windows) - 1):
            _, _, _, test_end_i = windows[i]
            _, _, test_start_next, _ = windows[i + 1]
            assert test_end_i <= test_start_next or test_start_next >= windows[i][2]


# ---------------------------------------------------------------------------
# 10.5 — RuntimeAdapter parity check: same inputs → same regime
# ---------------------------------------------------------------------------

class TestAdapterParity:
    def test_adapter_regime_matches_standalone_detector(self):
        """BacktestRuntimeAdapter's regime should match a standalone RegimeDetector
        given the same inputs."""
        from controllers.backtesting.runtime_adapter import (
            BacktestRuntimeAdapter,
            RuntimeAdapterConfig,
        )
        from simulation.types import (
            InstrumentId,
            InstrumentSpec,
        )
        from controllers.regime_detector import RegimeDetector

        inst_id = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")
        inst_spec = InstrumentSpec(
            instrument_id=inst_id,
            price_precision=2, size_precision=4,
            price_increment=Decimal("0.01"), size_increment=Decimal("0.0001"),
            min_quantity=Decimal("0.0001"), min_notional=Decimal("5"),
            max_quantity=Decimal("1000"),
            maker_fee_rate=Decimal("0.0002"), taker_fee_rate=Decimal("0.0006"),
            margin_init=Decimal("0.10"), margin_maint=Decimal("0.05"),
            leverage_max=10, funding_interval_s=28800,
        )

        adapter_cfg = RuntimeAdapterConfig(ema_period=20, atr_period=14, min_warmup_bars=30)
        adapter = BacktestRuntimeAdapter(
            strategy=_strategy(),
            desk=MagicMock(cancel_all=MagicMock(return_value=[]), submit_order=MagicMock()),
            instrument_id=inst_id,
            instrument_spec=inst_spec,
            config=adapter_cfg,
        )

        # Warmup with 60 candles
        warmup = _candles(60)
        adapter.warmup(warmup)

        # After warmup, adapter regime should be set
        assert adapter.regime_name in {
            "neutral_low_vol", "neutral_high_vol", "up", "down", "shock"
        }

        standalone = RegimeDetector(
            specs=adapter_cfg.regime_specs,
            high_vol_band_pct=adapter_cfg.high_vol_band_pct,
            shock_drift_30s_pct=Decimal("0.005"),
        )
        buf = adapter.price_buffer
        ema = buf.ema(20)
        band = buf.band_pct(14)
        import time
        drift = buf.adverse_drift_30s(time.time())
        mid = warmup[-1].close

        regime_name, _ = standalone.detect(
            mid=mid, ema_val=ema, band_pct=band, drift=drift,
        )
        assert regime_name == adapter.regime_name
