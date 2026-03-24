"""Backtest runtime adapter — wires strategy into PaperDesk via the runtime pipeline.

Reuses the production components (RegimeDetector, SpreadEngine, RiskEvaluator,
PriceBuffer) in a deterministic, harness-controlled loop.  Each tick:

1. Feed candle close into PriceBuffer → produces EMA, ATR, band_pct, drift.
2. RegimeDetector.detect() → regime_name, regime_spec.
3. SpreadEngine.compute_spread_and_edge() → SpreadEdgeState.
4. Build RuntimeDataContext from the above.
5. Call strategy.build_runtime_execution_plan(data_context) → RuntimeExecutionPlan.
6. Convert plan spreads to limit prices, cancel old orders, submit new ones to PaperDesk.

The adapter is *stateless* between runs — create a fresh instance per backtest.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from controllers.backtesting.types import CandleRow
from controllers.core import MarketConditions, RegimeSpec
from controllers.ops_guard import GuardState
from simulation.desk import PaperDesk
from simulation.types import (
    InstrumentId,
    InstrumentSpec,
    OrderBookSnapshot,
    OrderSide,
    PaperOrderType,
)
from controllers.price_buffer import MinuteBar, PriceBuffer
from controllers.regime_detector import RegimeDetector
from controllers.risk_evaluator import RiskEvaluator
from controllers.runtime.contracts import StrategyRuntimeHooks
from controllers.runtime.data_context import RuntimeDataContext
from controllers.runtime.execution_context import RuntimeExecutionPlan
from controllers.runtime.risk_context import RuntimeRiskDecision
from controllers.spread_engine import SpreadEngine

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_10K = Decimal("10000")


# ---------------------------------------------------------------------------
# Backtest strategy protocol + default implementation
# ---------------------------------------------------------------------------

class BacktestStrategyProtocol:
    """Minimal contract a strategy must satisfy for backtesting.

    Any object with ``build_runtime_execution_plan(ctx) -> RuntimeExecutionPlan``
    is accepted (duck typing).  This class is only used as documentation and
    for the default fallback implementation.
    """

    def build_runtime_execution_plan(self, data_context: RuntimeDataContext) -> RuntimeExecutionPlan:
        raise NotImplementedError


class DefaultMMBacktestStrategy(BacktestStrategyProtocol):
    """Generate a symmetric grid of limit-order spreads within the regime's range.

    This is the fallback strategy used when ``strategy_class`` is empty or
    set to ``"default_mm"``.  It produces a ``RuntimeExecutionPlan`` whose
    ``buy_spreads`` and ``sell_spreads`` are evenly spaced between
    ``regime_spec.spread_min`` and ``regime_spec.spread_max``.
    """

    def build_runtime_execution_plan(self, ctx: RuntimeDataContext) -> RuntimeExecutionPlan:
        spec = ctx.regime_spec
        n_levels = max(1, (spec.levels_min + spec.levels_max) // 2)
        spread_min = spec.spread_min
        spread_max = spec.spread_max

        if n_levels == 1:
            spreads = [spread_min]
        else:
            step = (spread_max - spread_min) / Decimal(n_levels - 1)
            spreads = [spread_min + step * Decimal(i) for i in range(n_levels)]

        return RuntimeExecutionPlan(
            family="maker",
            buy_spreads=list(spreads),
            sell_spreads=list(spreads),
            projected_total_quote=ctx.equity_quote * spec.quote_size_pct * Decimal(n_levels),
            size_mult=_ONE,
        )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class RuntimeAdapterConfig:
    """Configuration for BacktestRuntimeAdapter.

    All parameters have safe defaults suitable for a baseline market-making
    backtest.  Override via the YAML ``strategy_config`` section.
    """

    # RegimeDetector
    regime_specs: dict[str, RegimeSpec] = field(default_factory=lambda: {
        "neutral_low_vol": RegimeSpec(
            spread_min=Decimal("0.0020"), spread_max=Decimal("0.0040"),
            levels_min=2, levels_max=4, refresh_s=10,
            target_base_pct=Decimal("0.50"),
            quote_size_pct_min=Decimal("0.02"), quote_size_pct_max=Decimal("0.04"),
            one_sided="off",
        ),
        "neutral_high_vol": RegimeSpec(
            spread_min=Decimal("0.0040"), spread_max=Decimal("0.0080"),
            levels_min=1, levels_max=3, refresh_s=5,
            target_base_pct=Decimal("0.50"),
            quote_size_pct_min=Decimal("0.01"), quote_size_pct_max=Decimal("0.03"),
            one_sided="off",
        ),
        "up": RegimeSpec(
            spread_min=Decimal("0.0025"), spread_max=Decimal("0.0050"),
            levels_min=2, levels_max=3, refresh_s=10,
            target_base_pct=Decimal("0.60"),
            quote_size_pct_min=Decimal("0.02"), quote_size_pct_max=Decimal("0.04"),
            one_sided="off",
        ),
        "down": RegimeSpec(
            spread_min=Decimal("0.0025"), spread_max=Decimal("0.0050"),
            levels_min=2, levels_max=3, refresh_s=10,
            target_base_pct=Decimal("0.40"),
            quote_size_pct_min=Decimal("0.02"), quote_size_pct_max=Decimal("0.04"),
            one_sided="off",
        ),
        "high_vol_shock": RegimeSpec(
            spread_min=Decimal("0.0100"), spread_max=Decimal("0.0200"),
            levels_min=1, levels_max=2, refresh_s=3,
            target_base_pct=Decimal("0.50"),
            quote_size_pct_min=Decimal("0.005"), quote_size_pct_max=Decimal("0.01"),
            one_sided="off",
        ),
    })
    high_vol_band_pct: Decimal = Decimal("0.0080")
    shock_drift_30s_pct: Decimal = Decimal("0.0050")
    regime_hold_ticks: int = 3

    # SpreadEngine
    turnover_cap_x: Decimal = Decimal("20.0")
    spread_step_multiplier: Decimal = Decimal("1.5")
    vol_penalty_multiplier: Decimal = Decimal("0.5")
    slippage_est_pct: Decimal = Decimal("0.0005")
    min_net_edge_bps: int = 1
    edge_resume_bps: int = 4

    # RiskEvaluator
    min_base_pct: Decimal = Decimal("-0.50")
    max_base_pct: Decimal = Decimal("1.50")
    max_total_notional_quote: Decimal = Decimal("0")
    max_daily_turnover_x_hard: Decimal = Decimal("100")
    max_daily_loss_pct_hard: Decimal = Decimal("0.05")
    max_drawdown_pct_hard: Decimal = Decimal("0.10")
    edge_state_hold_s: int = 60

    # PriceBuffer
    ema_period: int = 20
    atr_period: int = 14
    min_warmup_bars: int = 30
    drift_alpha: Decimal = Decimal("0.15")

    # Instrument defaults
    maker_fee_pct: Decimal = Decimal("0.0002")
    is_perp: bool = True


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class BacktestRuntimeAdapter:
    """Drives a strategy through PaperDesk using the full runtime pipeline.

    One adapter per instrument per backtest run.
    """

    def __init__(
        self,
        strategy: StrategyRuntimeHooks,
        desk: PaperDesk,
        instrument_id: InstrumentId,
        instrument_spec: InstrumentSpec,
        config: RuntimeAdapterConfig,
    ) -> None:
        self._strategy = strategy
        self._desk = desk
        self._instrument_id = instrument_id
        self._instrument_spec = instrument_spec
        self._config = config

        # Instantiate runtime components (all pure, zero HB deps)
        self._regime_detector = RegimeDetector(
            specs=config.regime_specs,
            high_vol_band_pct=config.high_vol_band_pct,
            shock_drift_30s_pct=config.shock_drift_30s_pct,
            regime_hold_ticks=config.regime_hold_ticks,
        )
        self._spread_engine = SpreadEngine(
            turnover_cap_x=config.turnover_cap_x,
            spread_step_multiplier=config.spread_step_multiplier,
            vol_penalty_multiplier=config.vol_penalty_multiplier,
            slippage_est_pct=config.slippage_est_pct,
            min_net_edge_bps=config.min_net_edge_bps,
            edge_resume_bps=config.edge_resume_bps,
        )
        self._risk_evaluator = RiskEvaluator(
            min_base_pct=config.min_base_pct,
            max_base_pct=config.max_base_pct,
            max_total_notional_quote=config.max_total_notional_quote,
            max_daily_turnover_x_hard=config.max_daily_turnover_x_hard,
            max_daily_loss_pct_hard=config.max_daily_loss_pct_hard,
            max_drawdown_pct_hard=config.max_drawdown_pct_hard,
            edge_state_hold_s=config.edge_state_hold_s,
        )
        self._price_buffer = PriceBuffer(sample_interval_sec=10, max_minutes=2880)

        # Daily tracking state
        self._daily_equity_open: Decimal = _ZERO
        self._daily_equity_peak: Decimal = _ZERO
        self._traded_notional_today: Decimal = _ZERO
        self._current_day: int = -1
        self._tick_count: int = 0
        self._last_submitted_count: int = 0
        self._last_candle_ts: int = 0

    # ------------------------------------------------------------------
    # Warmup
    # ------------------------------------------------------------------

    def warmup(self, candles: list[CandleRow]) -> int:
        """Feed historical candles into PriceBuffer before the backtest loop.

        Converts candles to MinuteBar and calls seed_bars() for efficient
        bulk loading.  Returns the number of bars seeded.
        """
        if not candles:
            return 0

        bars = [
            MinuteBar(
                ts_minute=int(c.timestamp_ms // 1000 // 60) * 60,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
            )
            for c in candles
        ]
        return self._price_buffer.seed_bars(bars, reset=True)

    # ------------------------------------------------------------------
    # Per-tick execution
    # ------------------------------------------------------------------

    def tick(
        self,
        now_s: float,
        mid: Decimal,
        book: OrderBookSnapshot | None,
        equity_quote: Decimal,
        position_base: Decimal,
        candle: Any = None,
    ) -> RuntimeExecutionPlan | None:
        """Run one complete tick of the runtime pipeline.

        Returns the execution plan (or None if risk-blocked/no-data).
        Side effects: cancels old orders and submits new ones on PaperDesk.
        """
        self._tick_count += 1

        # --- Feed price buffer (prefer full OHLCV candle) ---
        if candle is not None and candle.timestamp_ms != self._last_candle_ts:
            bar = MinuteBar(
                ts_minute=int(candle.timestamp_ms // 1000 // 60) * 60,
                open=candle.open, high=candle.high,
                low=candle.low, close=candle.close,
            )
            self._price_buffer.append_bar(bar)
            self._last_candle_ts = candle.timestamp_ms
        else:
            self._price_buffer.add_sample(now_s, mid)

        # --- Daily state reset ---
        day = int(now_s // 86400)
        if day != self._current_day:
            self._current_day = day
            self._daily_equity_open = equity_quote
            self._daily_equity_peak = equity_quote
            self._traded_notional_today = _ZERO
        self._daily_equity_peak = max(self._daily_equity_peak, equity_quote)

        # --- Check buffer readiness ---
        if not self._price_buffer.ready(self._config.min_warmup_bars):
            return None

        # --- Price buffer indicators ---
        ema_val = self._price_buffer.ema(self._config.ema_period)
        band_pct = self._price_buffer.band_pct(self._config.atr_period) or _ZERO
        drift = self._price_buffer.adverse_drift_30s(now_s)
        smooth_drift = self._price_buffer.adverse_drift_smooth(
            now_s, self._config.drift_alpha,
        )

        # --- Regime detection ---
        regime_name, regime_spec = self._regime_detector.detect(
            mid=mid,
            ema_val=ema_val,
            band_pct=band_pct,
            drift=drift,
            regime_source_tag="backtest_buffer",
        )

        # --- Position metrics ---
        base_pct_gross = _ZERO
        base_pct_net = _ZERO
        target_base_pct = regime_spec.target_base_pct
        target_net_base_pct = target_base_pct
        if equity_quote > _ZERO and mid > _ZERO:
            position_value = position_base * mid
            base_pct_gross = position_value / equity_quote
            base_pct_net = base_pct_gross  # No hedging in backtest

        # --- Spread computation ---
        turnover_x = self._traded_notional_today / equity_quote if equity_quote > _ZERO else _ZERO
        spread_state, _spread_floor = self._spread_engine.compute_spread_and_edge(
            regime_name=regime_name,
            regime_spec=regime_spec,
            band_pct=band_pct,
            raw_drift=drift,
            smooth_drift=smooth_drift,
            target_base_pct=target_base_pct,
            base_pct=base_pct_gross,
            equity_quote=equity_quote,
            traded_notional_today=self._traded_notional_today,
            ob_imbalance=_ZERO,
            ob_imbalance_skew_weight=_ZERO,
            maker_fee_pct=self._config.maker_fee_pct,
            is_perp=self._config.is_perp,
            funding_rate=_ZERO,
            adverse_fill_count=0,
            fill_edge_ewma=None,
        )

        # --- Market conditions ---
        bid_p = mid * (_ONE - spread_state.spread_pct / Decimal("2"))
        ask_p = mid * (_ONE + spread_state.spread_pct / Decimal("2"))
        if book is not None and book.bids and book.asks:
            bid_p = book.bids[0].price
            ask_p = book.asks[0].price
        market_spread_pct = (ask_p - bid_p) / mid if mid > _ZERO else _ZERO
        is_high_vol = band_pct > self._config.high_vol_band_pct
        market = MarketConditions(
            is_high_vol=is_high_vol,
            bid_p=bid_p,
            ask_p=ask_p,
            market_spread_pct=market_spread_pct,
            best_bid_size=_ONE,
            best_ask_size=_ONE,
            connector_ready=True,
            order_book_stale=False,
            market_spread_too_small=False,
            side_spread_floor=_ZERO,
        )

        # --- Risk evaluation ---
        daily_loss_pct, drawdown_pct = RiskEvaluator.risk_loss_metrics(
            equity_quote=equity_quote,
            daily_equity_open=self._daily_equity_open,
            daily_equity_peak=self._daily_equity_peak,
        )
        _risk_reasons, risk_hard_stop = self._risk_evaluator.risk_policy_checks(
            base_pct=base_pct_gross,
            turnover_x=turnover_x,
            projected_total_quote=_ZERO,
            daily_loss_pct=daily_loss_pct,
            drawdown_pct=drawdown_pct,
        )

        # --- Edge gate check ---
        edge_blocked = self._risk_evaluator.edge_gate_blocked
        if risk_hard_stop or edge_blocked:
            self._cancel_all_orders()
            return None

        # --- Build RuntimeDataContext ---
        data_context = RuntimeDataContext(
            now_ts=now_s,
            mid=mid,
            regime_name=regime_name,
            regime_spec=regime_spec,
            spread_state=spread_state,
            market=market,
            equity_quote=equity_quote,
            target_base_pct=target_base_pct,
            target_net_base_pct=target_net_base_pct,
            base_pct_gross=base_pct_gross,
            base_pct_net=base_pct_net,
        )

        # --- Strategy execution plan ---
        try:
            plan = self._strategy.build_runtime_execution_plan(data_context)
        except Exception:
            logger.exception(
                "BacktestRuntimeAdapter: strategy raised on tick %d at %f",
                self._tick_count, now_s,
            )
            return None

        # --- Order lifecycle: cancel all → submit new ---
        self._cancel_all_orders()
        self._submit_orders_from_plan(plan, mid, equity_quote, regime_spec)

        return plan

    # ------------------------------------------------------------------
    # Order lifecycle helpers
    # ------------------------------------------------------------------

    def _cancel_all_orders(self) -> None:
        """Cancel all open orders for our instrument on the desk."""
        key = self._instrument_id.key
        try:
            self._desk.cancel_all(self._instrument_id)
        except Exception:
            logger.debug("BacktestRuntimeAdapter: cancel_all failed for %s", key)

    def _submit_orders_from_plan(
        self,
        plan: RuntimeExecutionPlan,
        mid: Decimal,
        equity_quote: Decimal,
        regime_spec: RegimeSpec,
    ) -> int:
        """Convert plan spreads to limit prices and submit orders to PaperDesk.

        Returns the number of orders actually submitted (after validation).
        """
        self._last_submitted_count = 0
        if mid <= _ZERO or equity_quote <= _ZERO:
            return 0

        quote_per_level = equity_quote * regime_spec.quote_size_pct * plan.size_mult
        base_per_level = quote_per_level / mid if mid > _ZERO else _ZERO

        quantity = self._instrument_spec.quantize_size(base_per_level)
        submitted = 0

        for spread_pct in plan.buy_spreads:
            price = mid * (_ONE - spread_pct)
            price = self._instrument_spec.quantize_price(price, "buy")
            rejection = self._instrument_spec.validate_order(price, quantity)
            if rejection:
                continue
            self._desk.submit_order(
                instrument_id=self._instrument_id,
                side=OrderSide.BUY,
                order_type=PaperOrderType.LIMIT,
                price=price,
                quantity=quantity,
                source_bot="backtest",
            )
            submitted += 1

        for spread_pct in plan.sell_spreads:
            price = mid * (_ONE + spread_pct)
            price = self._instrument_spec.quantize_price(price, "sell")
            rejection = self._instrument_spec.validate_order(price, quantity)
            if rejection:
                continue
            self._desk.submit_order(
                instrument_id=self._instrument_id,
                side=OrderSide.SELL,
                order_type=PaperOrderType.LIMIT,
                price=price,
                quantity=quantity,
                source_bot="backtest",
            )
            submitted += 1

        self._last_submitted_count = submitted
        return submitted

    def record_fill_notional(self, notional: Decimal) -> None:
        """Record filled notional for daily turnover tracking.

        Called by the harness when a fill event is processed, ensuring
        turnover reflects actual fills rather than submitted orders.
        """
        self._traded_notional_today += notional

    # ------------------------------------------------------------------
    # Accessors for harness / reporting
    # ------------------------------------------------------------------

    @property
    def price_buffer(self) -> PriceBuffer:
        return self._price_buffer

    @property
    def regime_name(self) -> str:
        return self._regime_detector.active_regime

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def last_submitted_count(self) -> int:
        """Number of orders actually submitted on the last tick."""
        return self._last_submitted_count

    def last_risk_decision(
        self,
        equity_quote: Decimal,
    ) -> RuntimeRiskDecision:
        """Build a RuntimeRiskDecision snapshot for reporting."""
        daily_loss_pct, drawdown_pct = RiskEvaluator.risk_loss_metrics(
            equity_quote=equity_quote,
            daily_equity_open=self._daily_equity_open,
            daily_equity_peak=self._daily_equity_peak,
        )
        return RuntimeRiskDecision(
            risk_reasons=[],
            risk_hard_stop=False,
            daily_loss_pct=daily_loss_pct,
            drawdown_pct=drawdown_pct,
            guard_state=GuardState.RUNNING,
        )
