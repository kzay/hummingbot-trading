"""Core domain types for the backtesting engine.

All types are pure Python dataclasses with no external dependencies.
The backtesting package must remain self-contained — production runtime
modules (controllers.runtime.*, controllers.price_buffer, etc.) are never
imported here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Market data rows
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CandleRow:
    """Single OHLCV candle bar."""

    timestamp_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @property
    def mid(self) -> Decimal:
        return (self.open + self.close) / 2

    @property
    def range(self) -> Decimal:
        return self.high - self.low

    @property
    def timestamp_ns(self) -> int:
        return self.timestamp_ms * 1_000_000


_NAN_DECIMAL = Decimal("NaN")


class VisibleCandleRow:
    """Lookahead guard: masks high/low/close until the final intra-bar step.

    Returns math.nan (as Decimal) for high, low, close when step_index < max_step,
    making accidental use produce obviously wrong results rather than subtle bias.
    """

    __slots__ = ("_candle", "_visible")

    def __init__(self, candle: CandleRow, step_index: int, max_step: int) -> None:
        self._candle = candle
        self._visible = step_index >= max_step

    @property
    def timestamp_ms(self) -> int:
        return self._candle.timestamp_ms

    @property
    def open(self) -> Decimal:
        return self._candle.open

    @property
    def high(self) -> Decimal:
        return self._candle.high if self._visible else _NAN_DECIMAL

    @property
    def low(self) -> Decimal:
        return self._candle.low if self._visible else _NAN_DECIMAL

    @property
    def close(self) -> Decimal:
        return self._candle.close if self._visible else _NAN_DECIMAL

    @property
    def volume(self) -> Decimal:
        return self._candle.volume

    @property
    def mid(self) -> Decimal:
        if self._visible:
            return (self._candle.open + self._candle.close) / 2
        return self._candle.open

    @property
    def range(self) -> Decimal:
        if self._visible:
            return self._candle.high - self._candle.low
        return _NAN_DECIMAL

    @property
    def timestamp_ns(self) -> int:
        return self._candle.timestamp_ms * 1_000_000

    def __repr__(self) -> str:
        vis = "full" if self._visible else "masked"
        return f"VisibleCandleRow({vis}, ts={self._candle.timestamp_ms})"


@dataclass(frozen=True)
class TradeRow:
    """Single trade tick."""

    timestamp_ms: int
    side: str  # "buy" | "sell"
    price: Decimal
    size: Decimal
    trade_id: str = ""

    @property
    def timestamp_ns(self) -> int:
        return self.timestamp_ms * 1_000_000


@dataclass(frozen=True)
class FundingRow:
    """Single historical funding-rate observation."""

    timestamp_ms: int
    rate: Decimal

    @property
    def timestamp_ns(self) -> int:
        return self.timestamp_ms * 1_000_000


@dataclass(frozen=True)
class LongShortRatioRow:
    """Single long/short account ratio observation from derivatives exchange."""

    timestamp_ms: int
    long_account_ratio: float
    short_account_ratio: float
    long_short_ratio: float

    @property
    def timestamp_ns(self) -> int:
        return self.timestamp_ms * 1_000_000


# ---------------------------------------------------------------------------
# Book synthesis config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SynthesisConfig:
    """Configuration for book synthesis from candle/trade data."""

    base_spread_bps: Decimal = Decimal("5.0")
    vol_spread_mult: Decimal = Decimal("1.0")
    depth_levels: int = 5
    depth_decay: Decimal = Decimal("0.70")
    base_depth_size: Decimal = Decimal("1.0")
    steps_per_bar: int = 1
    seed: int = 42


# ---------------------------------------------------------------------------
# Backtest configuration
# ---------------------------------------------------------------------------

@dataclass
class DataSourceConfig:
    """Where to load historical data from."""

    exchange: str = "bitget"
    pair: str = "BTC-USDT"
    resolution: str = "1m"
    start_date: str = ""  # ISO format: "2025-01-01"
    end_date: str = ""
    instrument_type: str = "perp"
    data_path: str = ""  # Override: load from specific file instead of catalog
    catalog_dir: str = "data/historical"  # Base directory for DataCatalog


@dataclass
class BacktestConfig:
    """Full configuration for a single backtest run."""

    # Strategy
    strategy_class: str = ""  # e.g. "controllers.bots.bot7.pullback_v1.PullbackV1Strategy"
    strategy_config: dict[str, Any] = field(default_factory=dict)

    # Data source
    data_source: DataSourceConfig = field(default_factory=DataSourceConfig)

    # Paper engine overrides
    initial_equity: Decimal = Decimal("500")
    fill_model: str = "latency_aware"  # Default for candle-based backtests per design D4b
    fill_model_preset: str = "balanced"
    seed: int = 42
    leverage: int = 1

    # Timing
    step_interval_s: int = 60  # Clock step size in seconds
    warmup_bars: int = 60  # Bars to feed to PriceBuffer before backtest starts

    # Latency simulation (0 = instant, realistic ≈ 50-150ms)
    insert_latency_ms: int = 0
    cancel_latency_ms: int = 0
    latency_model: str = "none"  # "none" | "fast" | "realistic" | "configured_latency_ms"

    # Book synthesis
    synthesis: SynthesisConfig = field(default_factory=SynthesisConfig)

    # Multi-instrument (optional)
    additional_instruments: list[DataSourceConfig] = field(default_factory=list)

    # Lookahead guard: when False, adapters receive VisibleCandleRow (masked)
    allow_full_candle: bool = False

    # Output
    output_dir: str = "reports/backtest"
    run_id: str = ""
    progress_dir: str = ""  # If set, harness writes progress.json here


# ---------------------------------------------------------------------------
# Backtest results
# ---------------------------------------------------------------------------

@dataclass
class EquitySnapshot:
    """Daily portfolio equity snapshot."""

    date: str  # ISO date
    equity: Decimal
    drawdown_pct: Decimal
    daily_return_pct: Decimal
    cumulative_return_pct: Decimal
    position_notional: Decimal
    num_fills: int


@dataclass
class FillRecord:
    """Record of a single fill event during backtest."""

    timestamp_ns: int
    order_id: str
    side: str
    fill_price: Decimal
    fill_quantity: Decimal
    fee: Decimal
    is_maker: bool
    slippage_bps: Decimal
    mid_slippage_bps: Decimal
    source_bot: str = ""


@dataclass
class RegimeMetrics:
    """Performance metrics for a single regime."""

    regime_name: str
    time_fraction: float
    sharpe: float
    max_drawdown_pct: float
    fill_count: int
    net_edge_bps: float
    num_days: int


@dataclass
class BacktestResult:
    """Complete results from a single backtest run."""

    # Config summary
    config: dict[str, Any] = field(default_factory=dict)

    # Core metrics
    total_return_pct: float = 0.0
    cagr_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_days: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win_loss_ratio: float = 0.0
    closed_trade_count: int = 0
    winning_trade_count: int = 0
    losing_trade_count: int = 0
    gross_profit_quote: Decimal = Decimal("0")
    gross_loss_quote: Decimal = Decimal("0")
    avg_win_quote: Decimal = Decimal("0")
    avg_loss_quote: Decimal = Decimal("0")
    expectancy_quote: Decimal = Decimal("0")
    realized_net_pnl_quote: Decimal = Decimal("0")
    residual_pnl_quote: Decimal = Decimal("0")

    # Fee attribution
    total_fees: Decimal = Decimal("0")
    maker_fees: Decimal = Decimal("0")
    taker_fees: Decimal = Decimal("0")
    funding_paid: Decimal = Decimal("0")
    funding_received: Decimal = Decimal("0")
    fee_drag_pct: float = 0.0
    maker_fill_ratio: float = 0.0

    # Execution quality
    fill_count: int = 0
    order_count: int = 0
    fill_rate: float = 0.0
    avg_slippage_bps: float = 0.0
    avg_mid_slippage_bps: float = 0.0
    partial_fill_ratio: float = 0.0

    # Turnover
    total_notional_traded: Decimal = Decimal("0")
    avg_daily_turnover: Decimal = Decimal("0")
    turnover_ratio: float = 0.0

    # Edge decay (rolling Sharpe values)
    edge_decay_curve: list[tuple[str, float]] = field(default_factory=list)

    # Regime-conditional
    regime_metrics: list[RegimeMetrics] = field(default_factory=list)

    # Spread capture efficiency
    spread_capture_efficiency: float = 0.0
    theoretical_max_pnl: Decimal = Decimal("0")

    # Inventory
    inventory_half_life_minutes: float = 0.0
    terminal_position_base: Decimal = Decimal("0")
    terminal_position_notional: Decimal = Decimal("0")
    terminal_mark_price: Decimal = Decimal("0")

    # Equity curve
    equity_curve: list[EquitySnapshot] = field(default_factory=list)
    fills: list[FillRecord] = field(default_factory=list)

    # Metadata
    run_duration_s: float = 0.0
    data_start: str = ""
    data_end: str = ""
    strategy_name: str = ""
    total_ticks: int = 0
    warnings: list[str] = field(default_factory=list)
    fill_disclaimer: str = ""


# ---------------------------------------------------------------------------
# Sweep configuration
# ---------------------------------------------------------------------------

@dataclass
class ParamSpace:
    """Definition of a single parameter's search space."""

    name: str
    mode: str  # "grid" | "range" | "log_range"
    values: list[Any] = field(default_factory=list)  # For grid mode
    min_val: float = 0.0  # For range/log_range
    max_val: float = 0.0
    step: float = 0.0  # For range mode
    num_points: int = 0  # For log_range mode


@dataclass
class SweepConfig:
    """Configuration for parameter sweep."""

    base_config: BacktestConfig = field(default_factory=BacktestConfig)
    param_spaces: list[ParamSpace] = field(default_factory=list)
    sweep_mode: str = "grid"  # "grid" | "random" | "bayesian"
    n_samples: int = 50  # For random/bayesian mode
    objective: str = "sharpe_ratio"  # Metric to optimize
    workers: int = 0  # 0 = cpu_count() - 1
    seed: int = 42


@dataclass
class SweepResult:
    """Result of a single run within a sweep."""

    params: dict[str, Any] = field(default_factory=dict)
    result: BacktestResult | None = None
    error: str = ""
    rank: int = 0


# ---------------------------------------------------------------------------
# Walk-forward configuration
# ---------------------------------------------------------------------------

@dataclass
class WalkForwardConfig:
    """Configuration for walk-forward validation."""

    sweep_config: SweepConfig = field(default_factory=SweepConfig)
    window_mode: str = "anchored"  # "anchored" | "rolling"
    train_ratio: float = 0.70
    min_train_days: int = 30
    min_test_days: int = 7
    n_windows: int = 0  # 0 = auto-compute from data length
    strategy_type: str = "mm"  # "mm" | "directional" — determines OOS threshold

    # Validation settings
    block_bootstrap_replications: int = 1000
    block_size_minutes: int = 30
    monte_carlo_seed: int = 42
    fee_stress_multipliers: list[float] = field(default_factory=lambda: [1.0, 1.5, 2.0])
    stressed_maker_ratio: float = 0.60


@dataclass
class WindowResult:
    """Result of a single walk-forward window."""

    window_index: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    best_params: dict[str, Any] = field(default_factory=dict)
    is_sharpe: float = 0.0
    oos_sharpe: float = 0.0
    oos_result: BacktestResult | None = None


@dataclass
class WalkForwardResult:
    """Complete walk-forward validation results."""

    windows: list[WindowResult] = field(default_factory=list)

    # Aggregate metrics
    mean_is_sharpe: float = 0.0
    mean_oos_sharpe: float = 0.0
    oos_degradation_ratio: float = 0.0
    oos_threshold: float = 0.50  # Determined by strategy_type

    # Deflated Sharpe
    raw_sharpe: float = 0.0
    deflated_sharpe: float = 0.0
    dsr_n_trials: int = 0
    dsr_pvalue: float = 0.0

    # Block bootstrap
    bootstrap_percentile: float = 0.0

    # Parameter stability
    param_cv: dict[str, float] = field(default_factory=dict)
    param_plateau_pass: dict[str, bool] = field(default_factory=dict)

    # Fee stress
    fee_margin_of_safety: float = 0.0
    sharpe_at_fee_levels: dict[str, float] = field(default_factory=dict)
    fee_stress_sharpes: list[float] = field(default_factory=list)
    sharpe_at_stressed_maker: float = 0.0

    # Regime-conditional
    regime_oos_degradation: dict[str, float] = field(default_factory=dict)

    # Multi-strategy correction
    holm_bonferroni_pass: bool = True
    bh_fdr_pass: bool = True

    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Harness ↔ adapter protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class BacktestTickAdapter(Protocol):
    """Contract between the harness time-loop and the strategy adapter.

    The harness calls only these methods; any object satisfying this protocol
    can be plugged in — from a zero-dependency standalone adapter to a
    production-parity bridge that wraps RegimeDetector/SpreadEngine/etc.
    """

    @property
    def regime_name(self) -> str:
        """Name of the currently active regime (e.g. ``"neutral_low_vol"``)."""
        ...

    @property
    def last_submitted_count(self) -> int:
        """Number of orders submitted on the most recent tick."""
        ...

    def warmup(self, candles: list[CandleRow]) -> int:
        """Bulk-load historical candles before the time-loop starts.

        Returns the number of bars consumed.
        """
        ...

    def tick(
        self,
        now_s: float,
        mid: Decimal,
        book: Any,
        equity_quote: Decimal,
        position_base: Decimal,
        candle: CandleRow | None = None,
    ) -> Any:
        """Execute one tick: produce an execution plan and submit orders.

        *candle* carries the full OHLCV bar for the current time step so
        adapters can feed real high/low/volume into their indicator buffers
        instead of flat mid-only samples.  ``mid`` remains available for
        intra-bar order-placement pricing derived from the synthesized book.

        Returns a plan object (truthy) or ``None`` if the tick was skipped.
        """
        ...

    def record_fill_notional(self, notional: Decimal) -> None:
        """Record filled notional for daily turnover tracking."""
        ...
