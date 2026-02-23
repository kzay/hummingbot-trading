from __future__ import annotations

import logging
import time as _time_mod
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from hummingbot.core.data_type.common import PriceType, TradeType
from hummingbot.core.event.events import MarketOrderFailureEvent, OrderCancelledEvent, OrderFilledEvent
from hummingbot.strategy_v2.controllers.market_making_controller_base import (
    MarketMakingControllerBase,
    MarketMakingControllerConfigBase,
)
from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig

from controllers.connector_runtime_adapter import ConnectorRuntimeAdapter
from controllers.epp_logging import CsvSplitLogger
from controllers.ops_guard import GuardState, OpsGuard, OpsSnapshot
from controllers.price_buffer import MidPriceBuffer
from services.common.fee_provider import FeeResolver
from services.common.utils import to_decimal

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("2")
_100 = Decimal("100")
_10K = Decimal("10000")
_NEG_ONE = Decimal("-1")
_MIN_SPREAD = Decimal("0.0001")
_MIN_SKEW_CAP = Decimal("0.0005")
_FILL_FACTOR_LO = Decimal("0.05")
_BALANCE_EPSILON = Decimal("1e-8")


def _clip(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return min(high, max(low, value))


@dataclass(frozen=True)
class RegimeSpec:
    spread_min: Decimal
    spread_max: Decimal
    levels_min: int
    levels_max: int
    refresh_s: int
    target_base_pct: Decimal
    quote_size_pct_min: Decimal
    quote_size_pct_max: Decimal
    one_sided: str  # "off" | "buy_only" | "sell_only"


@dataclass
class RuntimeLevelState:
    buy_spreads: List[Decimal]
    sell_spreads: List[Decimal]
    buy_amounts_pct: List[Decimal]
    sell_amounts_pct: List[Decimal]
    total_amount_quote: Decimal
    executor_refresh_time: int
    cooldown_time: int


class EppV24Config(MarketMakingControllerConfigBase):
    """Configuration for EPP v2.4 controller.

    Variants: a = live trading, b/c = disabled stubs, d = no-trade observation.
    """

    controller_name: str = "epp_v2_4"

    variant: str = Field(default="a", description="Controller variant: a=live, b/c=disabled, d=no-trade", json_schema_extra={"prompt": "Variant a/b/c/d: ", "prompt_on_new": True})
    enabled: bool = Field(default=True, description="Master enable switch for this controller", json_schema_extra={"prompt": "Enabled (true/false): ", "prompt_on_new": True})
    no_trade: bool = Field(default=False, description="When True, run all logic but place zero orders", json_schema_extra={"prompt": "No-trade mode: ", "prompt_on_new": True})
    instance_name: str = Field(default="bot1", description="Bot instance identifier for logging and multi-bot policies", json_schema_extra={"prompt": "Instance name: ", "prompt_on_new": True})
    log_dir: str = Field(default="/home/hummingbot/logs", description="Root directory for CSV logs")
    candles_connector: Optional[str] = Field(default=None, description="Override connector for candle data")
    candles_trading_pair: Optional[str] = Field(default=None, description="Override trading pair for candle data")

    # Exchange profile (VIP0)
    fee_mode: str = Field(default="auto", description="Fee resolution strategy: auto (API first) | project (profile file) | manual (spot_fee_pct)")
    fee_profile: str = Field(default="vip0", description="Fee profile key in fee_profiles.json")
    require_fee_resolution: bool = Field(default=True, description="HARD_STOP if fee resolution fails when True")
    fee_refresh_s: int = Field(default=300, ge=10, le=3600, description="Seconds between fee resolution attempts")
    spot_fee_pct: Decimal = Field(default=Decimal("0.0010"), description="Manual/fallback fee rate as decimal (0.001 = 0.1%)")
    slippage_est_pct: Decimal = Field(default=Decimal("0.0005"), description="Estimated slippage deducted from edge calculation")
    fill_factor: Decimal = Field(default=Decimal("0.4"), description="Expected spread capture fraction [0.05..1]. Lower = more conservative edge gating")
    turnover_cap_x: Decimal = Field(default=Decimal("3.0"), description="Daily turnover multiple before spread/level widening kicks in")
    turnover_penalty_step: Decimal = Field(default=Decimal("0.0010"), description="Additional spread cost per 1x turnover beyond cap")

    # Regime detection
    high_vol_band_pct: Decimal = Field(default=Decimal("0.0080"), description="ATR/price ratio threshold for high-vol regime")
    shock_drift_30s_pct: Decimal = Field(default=Decimal("0.0100"), description="30-second price drift threshold for shock regime (absolute fallback)")
    shock_drift_atr_multiplier: Decimal = Field(default=Decimal("1.25"), description="Shock fires when 30s drift > ATR_band * this multiplier (vol-adaptive)")
    trend_eps_pct: Decimal = Field(default=Decimal("0.0010"), description="Mid vs EMA threshold for up/down trend detection")

    # Runtime controls
    sample_interval_s: int = Field(default=10, ge=5, le=30)
    spread_floor_recalc_s: int = Field(default=30, description="Seconds between spread floor recalculations")
    daily_rollover_hour_utc: int = Field(default=0, ge=0, le=23)
    cancel_budget_per_min: int = Field(default=50)
    min_net_edge_bps: int = Field(default=2)
    cancel_pause_cooldown_s: int = Field(default=120)
    edge_resume_bps: int = Field(default=3)
    edge_state_hold_s: int = Field(default=60, ge=5, le=3600)
    min_market_spread_bps: int = Field(default=0, ge=0, le=100)
    inventory_skew_cap_pct: Decimal = Field(default=Decimal("0.0030"))
    inventory_skew_vol_multiplier: Decimal = Field(default=Decimal("1.0"))

    # Regime / spread tuning (previously hardcoded magic numbers)
    ema_period: int = Field(default=50, ge=5, le=500, description="EMA lookback for trend regime detection")
    atr_period: int = Field(default=14, ge=2, le=100, description="ATR lookback for volatility band and spread floor")
    trend_skew_factor: Decimal = Field(default=Decimal("0.8"), description="Inventory skew multiplier in trend regimes")
    neutral_skew_factor: Decimal = Field(default=Decimal("0.5"), description="Inventory skew multiplier in neutral regime")
    spread_step_multiplier: Decimal = Field(default=Decimal("0.4"), description="Per-level spread step as fraction of half-spread")
    vol_penalty_multiplier: Decimal = Field(default=Decimal("0.5"), description="ATR-based volatility penalty on spread floor")
    regime_hold_ticks: int = Field(default=3, ge=1, le=30, description="Regime must be detected for N consecutive ticks before switching")
    funding_rate_refresh_s: int = Field(default=300, ge=30, le=3600, description="Seconds between funding rate queries (perps only)")

    # Desk-style hard risk limits
    min_base_pct: Decimal = Field(default=Decimal("0.15"))
    max_base_pct: Decimal = Field(default=Decimal("0.90"))
    max_order_notional_quote: Decimal = Field(default=Decimal("250"))
    max_total_notional_quote: Decimal = Field(default=Decimal("1000"))
    max_daily_turnover_x_hard: Decimal = Field(default=Decimal("6.0"))
    max_daily_loss_pct_hard: Decimal = Field(default=Decimal("0.03"))
    max_drawdown_pct_hard: Decimal = Field(default=Decimal("0.05"))
    max_leverage: int = Field(default=5, ge=1, le=125, description="Maximum allowed leverage — startup rejects if config.leverage exceeds this")
    margin_ratio_soft_pause_pct: Decimal = Field(default=Decimal("0.20"), description="Margin ratio below this triggers SOFT_PAUSE (perps only)")
    margin_ratio_hard_stop_pct: Decimal = Field(default=Decimal("0.10"), description="Margin ratio below this triggers HARD_STOP (perps only)")
    position_recon_interval_s: int = Field(default=300, ge=30, le=3600, description="Seconds between position reconciliation checks")
    position_drift_soft_pause_pct: Decimal = Field(default=Decimal("0.05"), description="Position drift > this triggers SOFT_PAUSE")
    order_ack_timeout_s: int = Field(default=30, ge=5, le=120, description="Seconds before an unacked order is considered stuck")
    max_active_executors: int = Field(default=10, ge=1, le=50, description="Maximum concurrent active executors")
    # Internal paper engine (Level 2 realism)
    internal_paper_enabled: bool = Field(default=True)
    paper_seed: int = Field(default=7, ge=0)
    paper_latency_ms: int = Field(default=150, ge=0, le=5000)
    paper_queue_participation: Decimal = Field(default=Decimal("0.35"))
    paper_slippage_bps: Decimal = Field(default=Decimal("1.0"))
    paper_adverse_selection_bps: Decimal = Field(default=Decimal("1.5"))
    paper_partial_fill_min_ratio: Decimal = Field(default=Decimal("0.15"))
    paper_partial_fill_max_ratio: Decimal = Field(default=Decimal("0.85"))

    @field_validator("variant", mode="before")
    @classmethod
    def _validate_variant(cls, v: str) -> str:
        low = (v or "a").lower()
        if low not in {"a", "b", "c", "d"}:
            raise ValueError("variant must be one of a/b/c/d")
        return low

    @field_validator("fee_mode", mode="before")
    @classmethod
    def _validate_fee_mode(cls, v: str) -> str:
        low = (v or "auto").lower().strip()
        if low not in {"auto", "project", "manual"}:
            raise ValueError("fee_mode must be one of auto/project/manual")
        return low

    @field_validator("candles_connector", mode="before")
    @classmethod
    def _set_candles_connector(cls, v: Optional[str], info: ValidationInfo) -> str:
        if v in (None, ""):
            return str(info.data.get("connector_name", ""))
        return str(v)

    @field_validator("candles_trading_pair", mode="before")
    @classmethod
    def _set_candles_pair(cls, v: Optional[str], info: ValidationInfo) -> str:
        if v in (None, ""):
            return str(info.data.get("trading_pair", ""))
        return str(v)

    @field_validator("paper_queue_participation", "paper_partial_fill_min_ratio", "paper_partial_fill_max_ratio")
    @classmethod
    def _clip_unit_interval(cls, v: Decimal) -> Decimal:
        return _clip(to_decimal(v), Decimal("0"), Decimal("1"))


class EppV24Controller(MarketMakingControllerBase):
    """EPP v2.4 — VIP0 Survival Yield Engine.

    A regime-aware market-making controller that dynamically adjusts spread,
    inventory skew, and order sizing based on detected market conditions.

    Key mechanisms:
    - **Regime detection** (neutral / up / down / high_vol_shock) via EMA trend
      and ATR volatility band.
    - **Edge gating** — pauses quoting when estimated net edge (after fees,
      slippage, adverse drift) drops below a configurable threshold.
    - **Spread floor** — computes a minimum spread that is mathematically
      capable of clearing the edge gate given the current cost structure.
    - **Risk policy** — enforces hard limits on daily loss, drawdown, and
      turnover.  Breaching a hard limit triggers ``HARD_STOP``.
    - **OpsGuard state machine** — RUNNING / SOFT_PAUSE / HARD_STOP lifecycle
      with automatic transition and external intent support.

    The controller's tick output is stored in ``self.processed_data``
    (typed as ``ProcessedState``) and consumed by the CSV logger, Prometheus
    exporter, and Redis bus publisher.
    """

    PHASE0_SPECS: Dict[str, RegimeSpec] = {
        "neutral_low_vol": RegimeSpec(
            spread_min=Decimal("0.0025"),
            spread_max=Decimal("0.0045"),
            levels_min=2,
            levels_max=4,
            refresh_s=90,
            target_base_pct=Decimal("0.50"),
            quote_size_pct_min=Decimal("0.0008"),
            quote_size_pct_max=Decimal("0.0012"),
            one_sided="off",
        ),
        "up": RegimeSpec(
            spread_min=Decimal("0.0030"),
            spread_max=Decimal("0.0055"),
            levels_min=2,
            levels_max=3,
            refresh_s=70,
            target_base_pct=Decimal("0.65"),
            quote_size_pct_min=Decimal("0.0006"),
            quote_size_pct_max=Decimal("0.0010"),
            one_sided="buy_only",
        ),
        "down": RegimeSpec(
            spread_min=Decimal("0.0035"),
            spread_max=Decimal("0.0080"),
            levels_min=2,
            levels_max=3,
            refresh_s=60,
            target_base_pct=Decimal("0.25"),
            quote_size_pct_min=Decimal("0.0005"),
            quote_size_pct_max=Decimal("0.0008"),
            one_sided="sell_only",
        ),
        "high_vol_shock": RegimeSpec(
            spread_min=Decimal("0.0080"),
            spread_max=Decimal("0.0200"),
            levels_min=1,
            levels_max=2,
            refresh_s=120,
            target_base_pct=Decimal("0.40"),
            quote_size_pct_min=Decimal("0.0003"),
            quote_size_pct_max=Decimal("0.0005"),
            one_sided="sell_only",
        ),
    }

    def __init__(self, config: EppV24Config, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self.config = config
        self._is_perp = "_perpetual" in str(config.connector_name)
        if int(config.leverage) > config.max_leverage:
            raise ValueError(
                f"leverage={config.leverage} exceeds max_leverage={config.max_leverage}. "
                f"Increase max_leverage in config if intentional."
            )
        self._runtime_adapter = ConnectorRuntimeAdapter(self)
        self._runtime_levels = RuntimeLevelState(
            buy_spreads=[to_decimal(x) for x in config.buy_spreads],
            sell_spreads=[to_decimal(x) for x in config.sell_spreads],
            buy_amounts_pct=[to_decimal(x) for x in config.buy_amounts_pct],
            sell_amounts_pct=[to_decimal(x) for x in config.sell_amounts_pct],
            total_amount_quote=to_decimal(config.total_amount_quote),
            executor_refresh_time=int(config.executor_refresh_time),
            cooldown_time=int(config.cooldown_time),
        )
        self._price_buffer = MidPriceBuffer(sample_interval_sec=config.sample_interval_s)
        self._ops_guard = OpsGuard()
        self._csv = CsvSplitLogger(config.log_dir, config.instance_name, config.variant)
        self._last_floor_recalc_ts: float = 0
        self._spread_floor_pct: Decimal = Decimal("0.0025")
        self._traded_notional_today: Decimal = Decimal("0")
        self._fills_count_today: int = 0
        self._daily_equity_open: Optional[Decimal] = None
        self._daily_key: Optional[str] = None
        self._cancel_events_ts: List[float] = []
        self._cancel_fail_streak: int = 0
        self._soft_pause_edge: bool = False
        self._last_minute_key: Optional[int] = None
        self._external_soft_pause: bool = False
        self._external_pause_reason: str = ""
        self._external_target_base_pct_override: Optional[Decimal] = None
        self._last_external_model_version: str = ""
        self._last_external_intent_reason: str = ""
        self._cancel_pause_until: float = 0
        self._fee_source: str = "manual"
        self._fee_resolved: bool = False
        self._fee_resolution_error: str = ""
        self._maker_fee_pct: Decimal = to_decimal(self.config.spot_fee_pct)
        self._taker_fee_pct: Decimal = to_decimal(self.config.spot_fee_pct)
        self._last_fee_resolve_ts: float = 0.0
        self._edge_gate_blocked: bool = False
        self._edge_gate_changed_ts: float = 0.0
        self._daily_equity_peak: Optional[Decimal] = None
        self._fees_paid_today_quote: Decimal = Decimal("0")
        self._paper_fill_count: int = 0
        self._paper_reject_count: int = 0
        self._paper_avg_queue_delay_ms: Decimal = Decimal("0")
        self._tick_duration_ms: float = 0.0
        self._indicator_duration_ms: float = 0.0
        self._connector_io_duration_ms: float = 0.0
        self._active_regime: str = "neutral_low_vol"
        self._pending_regime: str = "neutral_low_vol"
        self._regime_hold_counter: int = 0
        self._pending_stale_cancel_actions: List[Any] = []
        self._funding_rate: Decimal = _ZERO
        self._funding_cost_today_quote: Decimal = _ZERO
        self._last_funding_rate_ts: float = 0.0
        self._margin_ratio: Decimal = _ONE
        self._cancel_budget_breach_count: int = 0
        self._avg_entry_price: Decimal = _ZERO
        self._position_base: Decimal = _ZERO
        self._realized_pnl_today: Decimal = _ZERO
        self._last_position_recon_ts: float = 0.0
        self._position_drift_pct: Decimal = _ZERO
        self._last_book_bid: Decimal = _ZERO
        self._last_book_ask: Decimal = _ZERO
        self._book_stale_since_ts: float = 0.0
        self._ws_reconnect_count: int = 0
        self._last_connector_ready: bool = True
        self._load_daily_state()

    async def update_processed_data(self):
        _t0 = _time_mod.perf_counter()
        now = float(self.market_data_provider.time())
        self._runtime_adapter.refresh_connector_cache()
        self._ensure_fee_config(now)
        self._refresh_funding_rate(now)
        self._check_position_reconciliation(now)
        if self.config.require_fee_resolution and self._fee_resolution_error:
            self._ops_guard.force_hard_stop("fee_unresolved")
            return

        _t_conn_start = _time_mod.perf_counter()
        mid = self._get_mid_price()
        if mid <= 0:
            return
        self._price_buffer.add_sample(now, mid)

        self._maybe_roll_day(now)
        equity_quote, base_pct = self._compute_equity_and_base_pct(mid)
        if self._daily_equity_open is None and equity_quote > 0:
            self._daily_equity_open = equity_quote
        if self._daily_equity_peak is None:
            self._daily_equity_peak = equity_quote
        if equity_quote > (self._daily_equity_peak or _ZERO):
            self._daily_equity_peak = equity_quote

        _t_ind_start = _time_mod.perf_counter()
        regime_name, regime_spec = self._detect_regime(mid)
        target_base_pct = regime_spec.target_base_pct
        if self._external_target_base_pct_override is not None:
            target_base_pct = _clip(self._external_target_base_pct_override, _ZERO, _ONE)

        band_pct = self._price_buffer.band_pct(self.config.atr_period) or _ZERO
        vol_ratio = _clip(
            band_pct / max(self.config.high_vol_band_pct, _MIN_SPREAD),
            _ZERO,
            _ONE,
        )
        skew_factor = self.config.trend_skew_factor if regime_name in {"up", "down"} else self.config.neutral_skew_factor
        inv_error = target_base_pct - base_pct
        skew_scale = _ONE + self.config.inventory_skew_vol_multiplier * vol_ratio
        skew_cap = max(_MIN_SKEW_CAP, self.config.inventory_skew_cap_pct)
        skew = _clip(inv_error * skew_factor * skew_scale, -skew_cap, skew_cap)

        adverse_drift = self._price_buffer.adverse_drift_30s(now)
        turnover_x = self._traded_notional_today / equity_quote if equity_quote > 0 else _ZERO
        turnover_penalty = max(_ZERO, turnover_x - self.config.turnover_cap_x) * self.config.turnover_penalty_step

        vol_penalty = band_pct * self.config.vol_penalty_multiplier
        min_edge_threshold = Decimal(self.config.min_net_edge_bps) / _10K
        edge_resume_threshold = Decimal(self.config.edge_resume_bps) / _10K
        fill_factor = _clip(self.config.fill_factor, _FILL_FACTOR_LO, _ONE)
        if now - self._last_floor_recalc_ts >= self.config.spread_floor_recalc_s:
            # Compute a floor that is capable of clearing the edge gate given our own net edge model:
            #   net_edge = fill_factor*spread - costs
            # ⇒ spread >= (costs + min_edge_threshold) / fill_factor
            # Add a volatility buffer on top (vol_penalty) for additional safety.
            funding_cost_est = _ZERO
            if self._is_perp and self._funding_rate != _ZERO:
                refresh_s = Decimal(max(30, int(self._runtime_levels.executor_refresh_time)))
                funding_cost_est = abs(self._funding_rate) * refresh_s / Decimal("28800")
            base_costs = (
                self._maker_fee_pct
                + self.config.slippage_est_pct
                + max(_ZERO, adverse_drift)
                + turnover_penalty
                + funding_cost_est
            )
            self._spread_floor_pct = (base_costs + min_edge_threshold) / fill_factor + vol_penalty
            self._last_floor_recalc_ts = now

        funding_cost_est_edge = _ZERO
        if self._is_perp and self._funding_rate != _ZERO:
            refresh_s_edge = Decimal(max(30, int(self._runtime_levels.executor_refresh_time)))
            funding_cost_est_edge = abs(self._funding_rate) * refresh_s_edge / Decimal("28800")

        spread_pct = self._pick_spread_pct(regime_spec, turnover_x)
        spread_pct = max(spread_pct, self._spread_floor_pct)
        net_edge = (
            fill_factor * spread_pct
            - self._maker_fee_pct
            - self.config.slippage_est_pct
            - max(_ZERO, adverse_drift)
            - turnover_penalty
            - funding_cost_est_edge
        )
        self._edge_gate_update(now, net_edge, min_edge_threshold, edge_resume_threshold)
        self._soft_pause_edge = self._edge_gate_blocked

        self._indicator_duration_ms = (_time_mod.perf_counter() - _t_ind_start) * 1000.0

        is_high_vol = band_pct >= self.config.high_vol_band_pct
        bid_p, ask_p, market_spread_pct, best_bid_size, best_ask_size = self._get_top_of_book()

        connector_ready_now = self._connector_ready()
        if not self._last_connector_ready and connector_ready_now:
            self._ws_reconnect_count += 1
            logger.info("Connector reconnected (count=%d)", self._ws_reconnect_count)
        self._last_connector_ready = connector_ready_now

        if bid_p > _ZERO and ask_p > _ZERO:
            if bid_p == self._last_book_bid and ask_p == self._last_book_ask:
                if self._book_stale_since_ts <= 0:
                    self._book_stale_since_ts = now
            else:
                self._book_stale_since_ts = 0.0
                self._last_book_bid = bid_p
                self._last_book_ask = ask_p
        order_book_stale = self._book_stale_since_ts > 0 and (now - self._book_stale_since_ts) > 30.0
        market_spread_threshold = Decimal(self.config.min_market_spread_bps) / _10K
        market_spread_too_small = (
            self.config.min_market_spread_bps > 0 and market_spread_pct > 0 and market_spread_pct < market_spread_threshold
        )

        side_spread_floor = _MIN_SPREAD
        if market_spread_pct > 0:
            half_market = market_spread_pct / _TWO + Decimal("0.0001")
            if half_market > side_spread_floor:
                side_spread_floor = half_market

        levels = self._pick_levels(regime_spec, turnover_x)
        self._runtime_levels.executor_refresh_time = int(regime_spec.refresh_s)
        buy_spreads, sell_spreads = self._build_side_spreads(
            spread_pct,
            skew,
            levels,
            regime_spec.one_sided,
            side_spread_floor,
        )
        projected_total_quote = self._project_total_amount_quote(
            equity_quote=equity_quote,
            mid=mid,
            quote_size_pct=(regime_spec.quote_size_pct_min + regime_spec.quote_size_pct_max) / Decimal("2"),
            total_levels=max(1, len(buy_spreads) + len(sell_spreads)),
        )
        daily_loss_pct, drawdown_pct = self._risk_loss_metrics(equity_quote)
        risk_reasons, risk_hard_stop = self._risk_policy_checks(
            base_pct=base_pct,
            turnover_x=turnover_x,
            projected_total_quote=projected_total_quote,
            daily_loss_pct=daily_loss_pct,
            drawdown_pct=drawdown_pct,
        )
        if self._is_perp:
            if self._margin_ratio < self.config.margin_ratio_hard_stop_pct:
                risk_reasons.append("margin_ratio_critical")
                risk_hard_stop = True
                logger.error("Margin ratio %.4f below hard stop threshold %.4f", self._margin_ratio, self.config.margin_ratio_hard_stop_pct)
            elif self._margin_ratio < self.config.margin_ratio_soft_pause_pct:
                risk_reasons.append("margin_ratio_warning")
        if self._position_drift_pct > self.config.position_drift_soft_pause_pct:
            risk_reasons.append("position_drift_high")
        if order_book_stale:
            risk_reasons.append("order_book_stale")

        connector_ready = self._connector_ready()
        balance_ok = self._balances_consistent()
        self._connector_io_duration_ms = (_time_mod.perf_counter() - _t_conn_start) * 1000.0
        if self._runtime_adapter.balance_read_failed:
            balance_ok = False
        state = self._ops_guard.update(
            OpsSnapshot(
                connector_ready=connector_ready,
                balances_consistent=balance_ok,
                cancel_fail_streak=self._cancel_fail_streak,
                edge_gate_blocked=self._soft_pause_edge,
                high_vol=is_high_vol,
                market_spread_too_small=market_spread_too_small,
                risk_reasons=risk_reasons,
                risk_hard_stop=risk_hard_stop,
            )
        )

        if not self.config.enabled or self.config.variant in {"b", "c"}:
            state = self._ops_guard.force_hard_stop("phase0_stub_disabled")
        if self.config.no_trade or self.config.variant == "d":
            state = GuardState.SOFT_PAUSE
        if self._external_soft_pause:
            state = GuardState.SOFT_PAUSE

        cancel_rate = self._cancel_per_min(now)
        if cancel_rate > self.config.cancel_budget_per_min:
            self._cancel_budget_breach_count += 1
            self._cancel_pause_until = now + self.config.cancel_pause_cooldown_s
            if self._cancel_budget_breach_count >= 3:
                state = self._ops_guard.force_hard_stop("cancel_budget_repeated_breach")
                logger.error("Cancel budget breached %d times — escalating to HARD_STOP", self._cancel_budget_breach_count)
        if now < self._cancel_pause_until and state != GuardState.HARD_STOP:
            state = GuardState.SOFT_PAUSE
        if cancel_rate <= self.config.cancel_budget_per_min and now >= self._cancel_pause_until:
            self._cancel_budget_breach_count = 0

        self._apply_runtime_spreads_and_sizing(
            buy_spreads=buy_spreads,
            sell_spreads=sell_spreads,
            levels=levels,
            equity_quote=equity_quote,
            mid=mid,
            quote_size_pct=(regime_spec.quote_size_pct_min + regime_spec.quote_size_pct_max) / Decimal("2"),
        )

        adapter_stats = {}
        connector = self._connector()
        if connector is not None and hasattr(connector, "paper_stats"):
            try:
                adapter_stats = dict(connector.paper_stats)
            except Exception:
                adapter_stats = {}
        self._paper_fill_count = int(adapter_stats.get("paper_fill_count", Decimal("0")))
        self._paper_reject_count = int(adapter_stats.get("paper_reject_count", Decimal("0")))
        self._paper_avg_queue_delay_ms = to_decimal(adapter_stats.get("paper_avg_queue_delay_ms", Decimal("0")))

        base_bal, quote_bal = self._get_balances()
        self.processed_data = {
            "reference_price": mid,
            "spread_multiplier": Decimal("1"),
            "regime": regime_name,
            "target_base_pct": target_base_pct,
            "base_pct": base_pct,
            "state": state.value,
            "spread_pct": spread_pct,
            "spread_floor_pct": self._spread_floor_pct,
            "net_edge_pct": net_edge,
            "turnover_x": turnover_x,
            "skew": skew,
            "adverse_drift_30s": adverse_drift,
            "market_spread_pct": market_spread_pct,
            "market_spread_bps": market_spread_pct * Decimal("10000"),
            "best_bid_size": best_bid_size,
            "best_ask_size": best_ask_size,
            "equity_quote": equity_quote,
            "mid": mid,
            "base_balance": base_bal,
            "quote_balance": quote_bal,
            "soft_pause_edge": self._soft_pause_edge,
            "edge_gate_blocked": self._edge_gate_blocked,
            "edge_pause_threshold_pct": min_edge_threshold,
            "edge_resume_threshold_pct": edge_resume_threshold,
            "risk_hard_stop": risk_hard_stop,
            "risk_reasons": "|".join(risk_reasons),
            "daily_loss_pct": daily_loss_pct,
            "drawdown_pct": drawdown_pct,
            "projected_total_quote": projected_total_quote,
            "fills_count_today": self._fills_count_today,
            "fees_paid_today_quote": self._fees_paid_today_quote,
            "paper_fill_count": self._paper_fill_count,
            "paper_reject_count": self._paper_reject_count,
            "paper_avg_queue_delay_ms": self._paper_avg_queue_delay_ms,
            "spread_capture_est_quote": self._traded_notional_today * spread_pct * fill_factor,
            "pnl_quote": equity_quote - (self._daily_equity_open or equity_quote),
            "external_soft_pause": self._external_soft_pause,
            "external_pause_reason": self._external_pause_reason,
            "external_model_version": self._last_external_model_version,
            "external_intent_reason": self._last_external_intent_reason,
            "fee_source": self._fee_source,
            "maker_fee_pct": self._maker_fee_pct,
            "taker_fee_pct": self._taker_fee_pct,
            "balance_read_failed": self._runtime_adapter.balance_read_failed,
            "funding_rate": self._funding_rate,
            "funding_cost_today_quote": self._funding_cost_today_quote,
            "margin_ratio": self._margin_ratio,
            "is_perpetual": self._is_perp,
            "realized_pnl_today_quote": self._realized_pnl_today,
            "avg_entry_price": self._avg_entry_price,
            "position_base": self._position_base,
            "position_drift_pct": self._position_drift_pct,
            "order_book_stale": order_book_stale,
            "ws_reconnect_count": self._ws_reconnect_count,
            "connector_status": self._runtime_adapter.status_summary(),
            "_tick_duration_ms": 0.0,
            "_indicator_duration_ms": self._indicator_duration_ms,
            "_connector_io_duration_ms": self._connector_io_duration_ms,
        }

        self._tick_duration_ms = (_time_mod.perf_counter() - _t0) * 1000.0
        self.processed_data["_tick_duration_ms"] = self._tick_duration_ms

        if state != GuardState.RUNNING:
            self._runtime_levels.buy_spreads = []
            self._runtime_levels.sell_spreads = []
            self._runtime_levels.buy_amounts_pct = []
            self._runtime_levels.sell_amounts_pct = []
            self._runtime_levels.total_amount_quote = Decimal("0")

        # ext1: pass event timestamp, not log time
        event_ts = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        self._log_minute(now, event_ts, mid, equity_quote, base_pct, base_bal, quote_bal,
                         target_base_pct, spread_pct, net_edge, turnover_x, state,
                         regime_name, adverse_drift, skew, market_spread_pct, best_bid_size, best_ask_size,
                         daily_loss_pct, drawdown_pct, risk_reasons)

    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal):
        side = self.get_trade_type_from_level_id(level_id)
        q_price = self._quantize_price(price, side)
        q_amount = self._quantize_amount(amount)
        min_notional_quote = self._min_notional_quote()
        if min_notional_quote > 0 and q_price > 0 and (q_amount * q_price) < min_notional_quote:
            # Ensure order survives exchange min-notional checks after amount quantization.
            q_amount = self._quantize_amount_up(min_notional_quote / q_price)
        return PositionExecutorConfig(
            timestamp=self.market_data_provider.time(),
            level_id=level_id,
            connector_name=self.config.connector_name,
            trading_pair=self.config.trading_pair,
            entry_price=q_price,
            amount=q_amount,
            triple_barrier_config=self.config.triple_barrier_config,
            leverage=self.config.leverage,
            side=side,
        )

    def did_fill_order(self, event: OrderFilledEvent):
        notional = to_decimal(event.amount) * to_decimal(event.price)
        self._traded_notional_today += notional
        self._fills_count_today += 1
        fee_quote = Decimal("0")
        quote_asset = self.config.trading_pair.split("-")[1]
        try:
            fee_quote = to_decimal(event.trade_fee.fee_amount_in_token(quote_asset, event.price, event.amount))
        except Exception:
            fee_quote = notional * self._taker_fee_pct
            logger.warning("Fee extraction failed for order %s, using estimate %.6f", event.order_id, fee_quote)
        self._fees_paid_today_quote += fee_quote
        expected_spread = to_decimal(self.processed_data.get("spread_pct", Decimal("0")))
        mid_ref = to_decimal(self.processed_data.get("mid", event.price))
        adverse_ref = to_decimal(self.processed_data.get("adverse_drift_30s", Decimal("0")))
        fill_price = to_decimal(event.price)
        is_maker = False
        if event.trade_type.name.lower() == "buy" and fill_price < mid_ref:
            is_maker = True
        elif event.trade_type.name.lower() == "sell" and fill_price > mid_ref:
            is_maker = True
        try:
            trade_fee_is_maker = getattr(event.trade_fee, "is_maker", None)
            if trade_fee_is_maker is not None:
                is_maker = bool(trade_fee_is_maker)
        except Exception:
            pass

        fill_amount = to_decimal(event.amount)
        realized_pnl = _ZERO
        if event.trade_type.name.lower() == "buy":
            if self._position_base < _ZERO and self._avg_entry_price > _ZERO:
                close_amount = min(fill_amount, abs(self._position_base))
                realized_pnl = (self._avg_entry_price - fill_price) * close_amount - fee_quote
            new_pos = self._position_base + fill_amount
            if new_pos > _ZERO and fill_amount > _ZERO:
                old_cost = self._avg_entry_price * max(_ZERO, self._position_base)
                new_cost = fill_price * fill_amount
                self._avg_entry_price = (old_cost + new_cost) / new_pos if new_pos > _ZERO else fill_price
            self._position_base = new_pos
        else:
            if self._position_base > _ZERO and self._avg_entry_price > _ZERO:
                close_amount = min(fill_amount, self._position_base)
                realized_pnl = (fill_price - self._avg_entry_price) * close_amount - fee_quote
            new_pos = self._position_base - fill_amount
            if new_pos < _ZERO and fill_amount > _ZERO:
                old_cost = self._avg_entry_price * max(_ZERO, -self._position_base)
                new_cost = fill_price * fill_amount
                self._avg_entry_price = (old_cost + new_cost) / abs(new_pos) if abs(new_pos) > _ZERO else fill_price
            self._position_base = new_pos
        self._realized_pnl_today += realized_pnl

        if mid_ref > _ZERO:
            price_deviation_pct = abs(fill_price - mid_ref) / mid_ref
            if price_deviation_pct > Decimal("0.01"):
                logger.warning("Fill price deviation %.4f%% for order %s (fill=%.2f mid=%.2f)",
                               float(price_deviation_pct * _100), event.order_id, float(fill_price), float(mid_ref))

        event_ts = datetime.fromtimestamp(event.timestamp, tz=timezone.utc).isoformat()
        self._csv.log_fill(
            {
                "bot_variant": self.config.variant,
                "exchange": self.config.connector_name,
                "trading_pair": self.config.trading_pair,
                "side": event.trade_type.name.lower(),
                "price": str(event.price),
                "amount_base": str(event.amount),
                "notional_quote": str(notional),
                "fee_quote": str(fee_quote),
                "order_id": event.order_id,
                "state": self._ops_guard.state.value,
                "mid_ref": str(mid_ref),
                "expected_spread_pct": str(expected_spread),
                "adverse_drift_30s": str(adverse_ref),
                "fee_source": self._fee_source,
                "is_maker": str(is_maker),
                "realized_pnl_quote": str(realized_pnl),
            },
            ts=event_ts,
        )
        self._save_daily_state()

    def did_cancel_order(self, cancelled_event: OrderCancelledEvent):
        self._cancel_events_ts.append(float(self.market_data_provider.time()))
        self._cancel_fail_streak = 0

    def did_fail_order(self, order_failed_event: MarketOrderFailureEvent):
        msg = (order_failed_event.error_message or "").lower()
        if "cancel" in msg:
            self._cancel_fail_streak += 1
        else:
            self._cancel_fail_streak = 0

    def to_format_status(self) -> List[str]:
        return [
            "EPP v2.4 - VIP0 Survival Yield Engine",
            f"variant={self.config.variant} state={self._ops_guard.state.value}",
            f"regime={self.processed_data.get('regime', 'n/a')}",
            f"spread={self.processed_data.get('spread_pct', Decimal('0')) * Decimal('100'):.3f}%",
            f"net_edge={self.processed_data.get('net_edge_pct', Decimal('0')) * Decimal('100'):.4f}%",
            f"base_pct={self.processed_data.get('base_pct', Decimal('0')) * Decimal('100'):.2f}%",
            f"target_base={self.processed_data.get('target_base_pct', Decimal('0')) * Decimal('100'):.2f}%",
            f"turnover_today={self.processed_data.get('turnover_x', Decimal('0')):.3f}x",
            f"mkt_spread={self.processed_data.get('market_spread_bps', Decimal('0')):.2f}bps",
            f"drawdown={self.processed_data.get('drawdown_pct', Decimal('0')) * Decimal('100'):.2f}%",
            f"paper fills={self.processed_data.get('paper_fill_count', 0)} rejects={self.processed_data.get('paper_reject_count', 0)} avg_qdelay_ms={self.processed_data.get('paper_avg_queue_delay_ms', Decimal('0')):.1f}",
            f"fees maker={self._maker_fee_pct * Decimal('100'):.4f}% taker={self._taker_fee_pct * Decimal('100'):.4f}% source={self._fee_source}",
            f"guard_reasons={','.join(self._ops_guard.reasons) if self._ops_guard.reasons else 'none'}",
        ]

    def get_custom_info(self) -> dict:
        return dict(self.processed_data)

    def set_external_soft_pause(self, active: bool, reason: str) -> None:
        self._external_soft_pause = bool(active)
        self._external_pause_reason = reason

    def apply_execution_intent(self, intent: Dict[str, object]) -> Tuple[bool, str]:
        action = str(intent.get("action", "")).strip()
        metadata = intent.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        self._last_external_model_version = str(metadata.get("model_version", ""))
        self._last_external_intent_reason = str(metadata.get("reason", ""))
        if action == "soft_pause":
            reason = str(metadata.get("reason", "external_intent"))
            self.set_external_soft_pause(True, reason)
            return True, "ok"
        if action == "resume":
            self.set_external_soft_pause(False, "resume")
            return True, "ok"
        if action == "kill_switch":
            self._ops_guard.force_hard_stop("external_kill_switch")
            return True, "ok"
        if action == "set_target_base_pct":
            value = intent.get("target_base_pct")
            if value is None:
                return False, "missing_target_base_pct"
            try:
                candidate = to_decimal(value)
                if candidate < Decimal("0") or candidate > Decimal("1"):
                    return False, "target_base_pct_out_of_range"
                self._external_target_base_pct_override = _clip(candidate, Decimal("0"), Decimal("1"))
                return True, "ok"
            except Exception:
                return False, "invalid_target_base_pct"
        return False, "unsupported_action"

    def _detect_regime(self, mid: Decimal) -> Tuple[str, RegimeSpec]:
        ema50 = self._price_buffer.ema(self.config.ema_period)
        band_pct = self._price_buffer.band_pct(self.config.atr_period) or _ZERO
        drift = self._price_buffer.adverse_drift_30s(float(self.market_data_provider.time()))

        vol_adaptive_shock = band_pct * self.config.shock_drift_atr_multiplier if band_pct > _ZERO else self.config.shock_drift_30s_pct
        shock_threshold = min(self.config.shock_drift_30s_pct, vol_adaptive_shock)
        if band_pct >= self.config.high_vol_band_pct or drift >= shock_threshold:
            raw_regime = "high_vol_shock"
        elif ema50 is None:
            raw_regime = "neutral_low_vol"
        elif mid > ema50 * (_ONE + self.config.trend_eps_pct):
            raw_regime = "up"
        elif mid < ema50 * (_ONE - self.config.trend_eps_pct):
            raw_regime = "down"
        else:
            raw_regime = "neutral_low_vol"

        if raw_regime == self._pending_regime:
            self._regime_hold_counter += 1
        else:
            self._pending_regime = raw_regime
            self._regime_hold_counter = 1

        if raw_regime != self._active_regime and self._regime_hold_counter >= self.config.regime_hold_ticks:
            old_one_sided = self.PHASE0_SPECS[self._active_regime].one_sided
            new_one_sided = self.PHASE0_SPECS[raw_regime].one_sided
            self._active_regime = raw_regime
            if old_one_sided != new_one_sided:
                self._pending_stale_cancel_actions = self._cancel_stale_side_executors(old_one_sided, new_one_sided)

        return self._active_regime, self.PHASE0_SPECS[self._active_regime]

    def _cancel_stale_side_executors(self, old_one_sided: str, new_one_sided: str) -> List[Any]:
        """Return StopExecutorActions for active executors on a side the new regime disabled."""
        from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction

        cancel_buy = (new_one_sided == "sell_only" and old_one_sided != "sell_only")
        cancel_sell = (new_one_sided == "buy_only" and old_one_sided != "buy_only")
        if not cancel_buy and not cancel_sell:
            return []
        actions: List[Any] = []
        for executor in self.executors_info:
            if not executor.is_active:
                continue
            level_id = executor.custom_info.get("level_id", "")
            if cancel_buy and level_id.startswith("buy"):
                actions.append(StopExecutorAction(controller_id=self.config.id, executor_id=executor.id))
            elif cancel_sell and level_id.startswith("sell"):
                actions.append(StopExecutorAction(controller_id=self.config.id, executor_id=executor.id))
        if actions:
            logger.info("Regime transition %s→%s: canceling %d stale-side executors", old_one_sided, new_one_sided, len(actions))
        return actions

    def _pick_spread_pct(self, regime_spec: RegimeSpec, turnover_x: Decimal) -> Decimal:
        ratio = _clip(turnover_x / max(self.config.turnover_cap_x, Decimal("0.0001")), Decimal("0"), Decimal("1"))
        return regime_spec.spread_min + (regime_spec.spread_max - regime_spec.spread_min) * ratio

    def _pick_levels(self, regime_spec: RegimeSpec, turnover_x: Decimal) -> int:
        if regime_spec.levels_min == regime_spec.levels_max:
            return regime_spec.levels_min
        ratio = _clip(turnover_x / max(self.config.turnover_cap_x, Decimal("0.0001")), Decimal("0"), Decimal("1"))
        span = regime_spec.levels_max - regime_spec.levels_min
        return max(regime_spec.levels_min, int(regime_spec.levels_max - int(round(float(ratio) * span))))

    def _build_side_spreads(
        self, spread_pct: Decimal, skew: Decimal, levels: int, one_sided: str, min_side_spread: Decimal
    ) -> Tuple[List[Decimal], List[Decimal]]:
        half = spread_pct / Decimal("2")
        step = half * self.config.spread_step_multiplier
        buy: List[Decimal] = []
        sell: List[Decimal] = []
        for i in range(levels):
            level_offset = half + step * Decimal(i)
            buy_spread = max(min_side_spread, level_offset - skew)
            sell_spread = max(min_side_spread, level_offset + skew)
            buy.append(buy_spread)
            sell.append(sell_spread)
        if one_sided == "buy_only":
            sell = []
        elif one_sided == "sell_only":
            buy = []
        return buy, sell

    def _apply_runtime_spreads_and_sizing(
        self,
        buy_spreads: List[Decimal],
        sell_spreads: List[Decimal],
        levels: int,
        equity_quote: Decimal,
        mid: Decimal,
        quote_size_pct: Decimal,
    ) -> None:
        if self.config.no_trade or self.config.variant == "d":
            self._runtime_levels.buy_spreads = []
            self._runtime_levels.sell_spreads = []
            self._runtime_levels.buy_amounts_pct = []
            self._runtime_levels.sell_amounts_pct = []
            self._runtime_levels.total_amount_quote = Decimal("0")
            return
        if self.config.variant in {"b", "c"} or not self.config.enabled:
            self._runtime_levels.buy_spreads = []
            self._runtime_levels.sell_spreads = []
            self._runtime_levels.buy_amounts_pct = []
            self._runtime_levels.sell_amounts_pct = []
            self._runtime_levels.total_amount_quote = Decimal("0")
            return

        self._runtime_levels.buy_spreads = list(buy_spreads)
        self._runtime_levels.sell_spreads = list(sell_spreads)
        self._runtime_levels.buy_amounts_pct = self._equal_split_pct_values(len(buy_spreads))
        self._runtime_levels.sell_amounts_pct = self._equal_split_pct_values(len(sell_spreads))

        per_order_quote = max(self._min_notional_quote(), equity_quote * quote_size_pct)
        side_levels = max(1, len(buy_spreads) + len(sell_spreads))
        total_amount_quote = per_order_quote * Decimal(side_levels)

        min_base = self._min_base_amount(mid)
        if min_base > 0 and total_amount_quote > 0:
            base_for_total = total_amount_quote / mid
            if base_for_total < min_base:
                total_amount_quote = min_base * mid

        self._runtime_levels.executor_refresh_time = max(30, int(self._runtime_levels.executor_refresh_time))
        self._runtime_levels.cooldown_time = max(5, int(self.config.cooldown_time))
        if self.config.max_total_notional_quote > 0:
            total_amount_quote = min(total_amount_quote, self.config.max_total_notional_quote)
        self._runtime_levels.total_amount_quote = total_amount_quote

    @staticmethod
    def _equal_split_pct(level_count: int) -> str:
        if level_count <= 0:
            return ""
        unit = Decimal("100") / Decimal(level_count)
        return ",".join(str(unit) for _ in range(level_count))

    def _equal_split_pct_values(self, level_count: int) -> List[Decimal]:
        if level_count <= 0:
            return []
        unit = Decimal("100") / Decimal(level_count)
        return [unit for _ in range(level_count)]

    def _connector(self):
        return self._runtime_adapter.get_connector()

    def _trading_rule(self):
        return self._runtime_adapter.get_trading_rule()

    def get_levels_to_execute(self) -> List[str]:
        cooldown = max(1, int(self._runtime_levels.cooldown_time))
        now = self.market_data_provider.time()
        active_count = 0
        working_levels = self.filter_executors(
            executors=self.executors_info,
            filter_func=lambda x: x.is_active
            or (str(getattr(x, "close_type", "")) == "CloseType.STOP_LOSS" and now - x.close_timestamp < cooldown),
        )
        stopping_level_ids = set()
        for ex in self.executors_info:
            if ex.is_active:
                active_count += 1
            if getattr(ex, "close_type", None) is not None and ex.is_active:
                lid = ex.custom_info.get("level_id", "")
                if lid:
                    stopping_level_ids.add(lid)
        if active_count >= self.config.max_active_executors:
            return []
        working_levels_ids = [executor.custom_info["level_id"] for executor in working_levels]
        working_levels_ids.extend(stopping_level_ids)
        return self.get_not_active_levels_ids(working_levels_ids)

    def executors_to_refresh(self) -> List[Any]:
        refresh_s = max(1, int(self._runtime_levels.executor_refresh_time))
        ack_timeout_s = max(5, self.config.order_ack_timeout_s)
        now = self.market_data_provider.time()

        stale_executors = self.filter_executors(
            executors=self.executors_info,
            filter_func=lambda x: not x.is_trading and x.is_active and now - x.timestamp > refresh_s,
        )
        stuck_executors = self.filter_executors(
            executors=self.executors_info,
            filter_func=lambda x: not x.is_trading and x.is_active and now - x.timestamp > ack_timeout_s and now - x.timestamp <= refresh_s,
        )
        if stuck_executors:
            logger.warning("Order ack timeout: %d executor(s) stuck in placing state for >%ds",
                           len(stuck_executors), ack_timeout_s)

        from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction

        actions = [StopExecutorAction(controller_id=self.config.id, executor_id=executor.id)
                   for executor in stale_executors + stuck_executors]
        if self._pending_stale_cancel_actions:
            actions.extend(self._pending_stale_cancel_actions)
            self._pending_stale_cancel_actions = []
        return actions

    def get_not_active_levels_ids(self, active_levels_ids: List[str]) -> List[str]:
        buy_ids_missing = [
            self.get_level_id_from_side(TradeType.BUY, level)
            for level in range(len(self._runtime_levels.buy_spreads))
            if self.get_level_id_from_side(TradeType.BUY, level) not in active_levels_ids
        ]
        sell_ids_missing = [
            self.get_level_id_from_side(TradeType.SELL, level)
            for level in range(len(self._runtime_levels.sell_spreads))
            if self.get_level_id_from_side(TradeType.SELL, level) not in active_levels_ids
        ]
        return buy_ids_missing + sell_ids_missing

    def get_price_and_amount(self, level_id: str) -> Tuple[Decimal, Decimal]:
        level = self.get_level_from_level_id(level_id)
        trade_type = self.get_trade_type_from_level_id(level_id)
        spreads, amounts_quote = self._runtime_spreads_and_amounts_in_quote(trade_type)
        reference_price = to_decimal(self.processed_data["reference_price"])
        spread_in_pct = spreads[int(level)] * to_decimal(self.processed_data["spread_multiplier"])
        side_multiplier = Decimal("-1") if trade_type == TradeType.BUY else Decimal("1")
        order_price = reference_price * (1 + side_multiplier * spread_in_pct)
        return order_price, amounts_quote[int(level)] / order_price

    def _runtime_spreads_and_amounts_in_quote(self, trade_type: TradeType) -> Tuple[List[Decimal], List[Decimal]]:
        buy_amounts_pct = self._runtime_levels.buy_amounts_pct
        sell_amounts_pct = self._runtime_levels.sell_amounts_pct
        total_pct = sum(buy_amounts_pct) + sum(sell_amounts_pct)
        if total_pct <= 0:
            return [], []
        if trade_type == TradeType.BUY:
            normalized = [amt_pct / total_pct for amt_pct in buy_amounts_pct]
            spreads = self._runtime_levels.buy_spreads
        else:
            normalized = [amt_pct / total_pct for amt_pct in sell_amounts_pct]
            spreads = self._runtime_levels.sell_spreads
        amounts = [amt_pct * self._runtime_levels.total_amount_quote for amt_pct in normalized]
        return spreads, amounts

    def _runtime_required_base_amount(self, reference_price: Decimal) -> Decimal:
        if reference_price <= 0:
            return Decimal("0")
        _, sell_amounts_quote = self._runtime_spreads_and_amounts_in_quote(TradeType.SELL)
        total_sell_amount_quote = sum(sell_amounts_quote)
        return total_sell_amount_quote / reference_price

    def check_position_rebalance(self):
        if "_perpetual" in self.config.connector_name or "reference_price" not in self.processed_data or self.config.skip_rebalance:
            return None
        active_rebalance = self.filter_executors(
            executors=self.executors_info,
            filter_func=lambda x: x.is_active and x.custom_info.get("level_id") == "position_rebalance",
        )
        if len(active_rebalance) > 0:
            return None
        required_base_amount = self._runtime_required_base_amount(to_decimal(self.processed_data["reference_price"]))
        current_base_amount = self.get_current_base_position()
        base_amount_diff = required_base_amount - current_base_amount
        threshold_amount = required_base_amount * self.config.position_rebalance_threshold_pct
        if abs(base_amount_diff) > threshold_amount:
            if base_amount_diff > 0:
                return self.create_position_rebalance_order(TradeType.BUY, abs(base_amount_diff))
            return self.create_position_rebalance_order(TradeType.SELL, abs(base_amount_diff))
        return None

    def _quantize_price(self, price: Decimal, side: TradeType) -> Decimal:
        rule = self._trading_rule()
        if rule is None or price <= 0:
            return price
        step = Decimal("0")
        for attr in ("min_price_increment", "min_price_tick_size", "price_step", "min_price_step"):
            value = getattr(rule, attr, None)
            if value is not None:
                step = to_decimal(value)
                break
        if step <= 0:
            return price
        rounding = ROUND_DOWN if side == TradeType.BUY else ROUND_UP
        steps = (price / step).to_integral_value(rounding=rounding)
        return max(step, steps * step)

    def _quantize_amount(self, amount: Decimal) -> Decimal:
        rule = self._trading_rule()
        if rule is None or amount <= 0:
            return amount
        min_amount = Decimal("0")
        step = Decimal("0")
        for attr in ("min_order_size", "min_base_amount", "min_amount"):
            value = getattr(rule, attr, None)
            if value is not None:
                min_amount = max(min_amount, to_decimal(value))
        for attr in ("min_base_amount_increment", "min_order_size_increment", "amount_step"):
            value = getattr(rule, attr, None)
            if value is not None:
                step = to_decimal(value)
                break
        q_amount = max(amount, min_amount)
        if step > 0:
            units = (q_amount / step).to_integral_value(rounding=ROUND_DOWN)
            q_amount = max(min_amount, units * step)
        return q_amount

    def _quantize_amount_up(self, amount: Decimal) -> Decimal:
        rule = self._trading_rule()
        if rule is None or amount <= 0:
            return amount
        min_amount = Decimal("0")
        step = Decimal("0")
        for attr in ("min_order_size", "min_base_amount", "min_amount"):
            value = getattr(rule, attr, None)
            if value is not None:
                min_amount = max(min_amount, to_decimal(value))
        for attr in ("min_base_amount_increment", "min_order_size_increment", "amount_step"):
            value = getattr(rule, attr, None)
            if value is not None:
                step = to_decimal(value)
                break
        q_amount = max(amount, min_amount)
        if step > 0:
            units = (q_amount / step).to_integral_value(rounding=ROUND_UP)
            q_amount = max(min_amount, units * step)
        return q_amount

    def _ensure_fee_config(self, now_ts: float) -> None:
        mode = self.config.fee_mode
        connector = self._connector()
        canonical_name = (
            self.config.connector_name[:-12]
            if str(self.config.connector_name).endswith("_paper_trade")
            else self.config.connector_name
        )

        # Manual/project modes are static after first successful resolution.
        if mode in {"manual", "project"} and self._fee_resolved:
            return
        # In auto mode, allow periodic refresh attempts until API source is obtained.
        if mode == "auto" and self._fee_resolved and self._fee_source.startswith("api:"):
            return
        if self._last_fee_resolve_ts > 0 and (now_ts - self._last_fee_resolve_ts) < self.config.fee_refresh_s:
            return
        self._last_fee_resolve_ts = now_ts

        if mode == "manual":
            self._fee_source = "manual:spot_fee_pct"
            self._maker_fee_pct = to_decimal(self.config.spot_fee_pct)
            self._taker_fee_pct = to_decimal(self.config.spot_fee_pct)
            self._fee_resolved = self._maker_fee_pct > 0
            if not self._fee_resolved:
                self._fee_resolution_error = "manual_fee_non_positive"
            else:
                self._fee_resolution_error = ""
            return

        if mode == "auto":
            live_api = FeeResolver.from_exchange_api(connector, self.config.connector_name, self.config.trading_pair)
            # For framework paper connectors, credentials may only exist on the base connector.
            if live_api is None and self.config.connector_name.endswith("_paper_trade"):
                try:
                    base_connector = self.market_data_provider.get_connector(canonical_name)
                except Exception:
                    base_connector = None
                live_api = FeeResolver.from_exchange_api(base_connector, canonical_name, self.config.trading_pair)
            if live_api is not None:
                self._maker_fee_pct = live_api.maker
                self._taker_fee_pct = live_api.taker
                self._fee_source = live_api.source
                self._fee_resolved = True
                self._fee_resolution_error = ""
                return
            runtime = FeeResolver.from_connector_runtime(connector, self.config.trading_pair)
            if runtime is not None:
                self._maker_fee_pct = runtime.maker
                self._taker_fee_pct = runtime.taker
                self._fee_source = runtime.source
                self._fee_resolved = True
                self._fee_resolution_error = ""
                return

        profile = FeeResolver.from_project_profile(self.config.connector_name, self.config.fee_profile)
        if profile is not None:
            self._maker_fee_pct = profile.maker
            self._taker_fee_pct = profile.taker
            self._fee_source = profile.source
            self._fee_resolved = True
            self._fee_resolution_error = ""
            return

        if self._maker_fee_pct > 0:
            self._fee_source = "manual_fallback:spot_fee_pct"
            self._taker_fee_pct = self._maker_fee_pct
            self._fee_resolved = not self.config.require_fee_resolution
            if self.config.require_fee_resolution:
                self._fee_resolution_error = "resolver_failed_with_require_true"
            else:
                self._fee_resolution_error = ""
        else:
            self._fee_resolution_error = "no_fee_available"
        return

    def _refresh_funding_rate(self, now_ts: float) -> None:
        """Fetch funding rate for perpetual connectors."""
        if "_perpetual" not in self.config.connector_name:
            return
        if now_ts - self._last_funding_rate_ts < self.config.funding_rate_refresh_s:
            return
        self._last_funding_rate_ts = now_ts
        connector = self._connector()
        if connector is None:
            return
        try:
            funding_info = getattr(connector, "get_funding_info", None)
            if callable(funding_info):
                info = funding_info(self.config.trading_pair)
                rate = getattr(info, "rate", None) or getattr(info, "funding_rate", None)
                if rate is not None:
                    self._funding_rate = to_decimal(rate)
                    return
            funding_rates = getattr(connector, "funding_rates", None)
            if isinstance(funding_rates, dict):
                rate = funding_rates.get(self.config.trading_pair)
                if rate is not None:
                    self._funding_rate = to_decimal(rate)
                    return
        except Exception:
            logger.debug("Funding rate fetch failed for %s", self.config.trading_pair)

    def _check_position_reconciliation(self, now_ts: float) -> None:
        """Periodically compare local position with exchange-reported position."""
        if now_ts - self._last_position_recon_ts < self.config.position_recon_interval_s:
            return
        self._last_position_recon_ts = now_ts
        connector = self._connector()
        if connector is None:
            return
        try:
            if self._is_perp:
                pos_fn = getattr(connector, "get_position", None) or getattr(connector, "account_positions", None)
                if callable(pos_fn):
                    pos = pos_fn(self.config.trading_pair) if "trading_pair" in str(getattr(pos_fn, "__code__", "")) else pos_fn()
                    if hasattr(pos, "amount"):
                        exchange_pos = to_decimal(pos.amount)
                    elif isinstance(pos, dict):
                        exchange_pos = to_decimal(pos.get(self.config.trading_pair, {}).get("amount", 0))
                    else:
                        return
                else:
                    return
            else:
                exchange_pos = to_decimal(connector.get_balance(self._runtime_adapter._base_asset))
            local_pos = self._position_base
            if exchange_pos == _ZERO and local_pos == _ZERO:
                self._position_drift_pct = _ZERO
                return
            ref = max(abs(exchange_pos), abs(local_pos), _MIN_SPREAD)
            self._position_drift_pct = abs(exchange_pos - local_pos) / ref
            if self._position_drift_pct > self.config.position_drift_soft_pause_pct:
                logger.warning(
                    "Position drift %.4f%% (local=%.8f exchange=%.8f) exceeds threshold",
                    float(self._position_drift_pct * _100), float(local_pos), float(exchange_pos),
                )
        except Exception:
            logger.debug("Position reconciliation failed for %s", self.config.trading_pair, exc_info=True)

    def _get_mid_price(self) -> Decimal:
        return self._runtime_adapter.get_mid_price()

    def _get_balances(self) -> Tuple[Decimal, Decimal]:
        return self._runtime_adapter.get_balances()

    def _compute_equity_and_base_pct(self, mid: Decimal) -> Tuple[Decimal, Decimal]:
        base_bal, quote_bal = self._get_balances()
        if self._is_perp:
            # For perpetual connectors, quote_bal is the margin balance
            # (already includes unrealized PnL on most exchanges).
            # base_bal is the position size. Equity = margin balance.
            equity = quote_bal if quote_bal > _ZERO else abs(base_bal) * mid
            position_value = abs(base_bal) * mid
            base_pct = position_value / equity if equity > _ZERO else _ZERO
            self._refresh_margin_ratio(mid, base_bal, quote_bal)
        else:
            equity = quote_bal + base_bal * mid
            base_pct = (base_bal * mid) / equity if equity > _ZERO else _ZERO
        if equity <= _ZERO:
            return _ZERO, _ZERO
        return equity, base_pct

    def _refresh_margin_ratio(self, mid: Decimal, base_bal: Decimal, quote_bal: Decimal) -> None:
        """Update margin ratio for perp connectors."""
        if not self._is_perp:
            return
        connector = self._connector()
        if connector is None:
            return
        try:
            margin_info = getattr(connector, "get_margin_info", None)
            if callable(margin_info):
                info = margin_info(self.config.trading_pair)
                ratio = getattr(info, "margin_ratio", None)
                if ratio is not None:
                    self._margin_ratio = to_decimal(ratio)
                    return
        except Exception:
            pass
        position_notional = abs(base_bal) * mid
        if position_notional > _ZERO and quote_bal > _ZERO:
            self._margin_ratio = quote_bal / position_notional
        else:
            self._margin_ratio = _ONE

    def _connector_ready(self) -> bool:
        return self._runtime_adapter.ready()

    def _balances_consistent(self) -> bool:
        return self._runtime_adapter.balances_consistent()

    def _cancel_per_min(self, now: float) -> int:
        self._cancel_events_ts = [ts for ts in self._cancel_events_ts if now - ts <= 60.0]
        return len(self._cancel_events_ts)

    def _min_notional_quote(self) -> Decimal:
        rule = self._trading_rule()
        if rule is None:
            return Decimal("0")
        for attr in ("min_notional_size", "min_notional", "min_order_value"):
            value = getattr(rule, attr, None)
            if value is not None:
                return to_decimal(value)
        return Decimal("0")

    def _min_base_amount(self, ref_price: Decimal) -> Decimal:
        quote_min = self._min_notional_quote()
        if quote_min <= 0 or ref_price <= 0:
            return Decimal("0")
        return quote_min / ref_price

    def _project_total_amount_quote(
        self,
        equity_quote: Decimal,
        mid: Decimal,
        quote_size_pct: Decimal,
        total_levels: int,
    ) -> Decimal:
        per_order_quote = max(self._min_notional_quote(), equity_quote * quote_size_pct)
        if self.config.max_order_notional_quote > 0:
            per_order_quote = min(per_order_quote, self.config.max_order_notional_quote)
        projected = per_order_quote * Decimal(max(1, total_levels))
        if self.config.max_total_notional_quote > 0:
            projected = min(projected, self.config.max_total_notional_quote)
        min_base = self._min_base_amount(mid)
        if min_base > 0 and mid > 0 and projected > 0 and (projected / mid) < min_base:
            projected = min_base * mid
        return projected

    def _risk_loss_metrics(self, equity_quote: Decimal) -> Tuple[Decimal, Decimal]:
        open_equity = self._daily_equity_open or equity_quote
        peak_equity = self._daily_equity_peak or equity_quote
        daily_loss_pct = Decimal("0")
        drawdown_pct = Decimal("0")
        if open_equity > 0:
            daily_loss_pct = max(Decimal("0"), (open_equity - equity_quote) / open_equity)
        if peak_equity > 0:
            drawdown_pct = max(Decimal("0"), (peak_equity - equity_quote) / peak_equity)
        return daily_loss_pct, drawdown_pct

    def _risk_policy_checks(
        self,
        base_pct: Decimal,
        turnover_x: Decimal,
        projected_total_quote: Decimal,
        daily_loss_pct: Decimal,
        drawdown_pct: Decimal,
    ) -> Tuple[List[str], bool]:
        reasons: List[str] = []
        hard = False
        if base_pct < self.config.min_base_pct:
            reasons.append("base_pct_below_min")
        if base_pct > self.config.max_base_pct:
            reasons.append("base_pct_above_max")
        if self.config.max_total_notional_quote > 0 and projected_total_quote > self.config.max_total_notional_quote:
            reasons.append("projected_total_quote_above_cap")
        if turnover_x > self.config.max_daily_turnover_x_hard:
            reasons.append("daily_turnover_hard_limit")
            hard = True
        if daily_loss_pct > self.config.max_daily_loss_pct_hard:
            reasons.append("daily_loss_hard_limit")
            hard = True
        if drawdown_pct > self.config.max_drawdown_pct_hard:
            reasons.append("drawdown_hard_limit")
            hard = True
        return reasons, hard

    def _edge_gate_update(
        self,
        now_ts: float,
        net_edge: Decimal,
        pause_threshold: Decimal,
        resume_threshold: Decimal,
    ) -> None:
        hold_sec = max(5, int(self.config.edge_state_hold_s))
        if self._edge_gate_changed_ts <= 0:
            self._edge_gate_changed_ts = now_ts
        elapsed = now_ts - self._edge_gate_changed_ts
        if self._edge_gate_blocked:
            if net_edge > resume_threshold and elapsed >= hold_sec:
                self._edge_gate_blocked = False
                self._edge_gate_changed_ts = now_ts
            return
        if net_edge < pause_threshold and elapsed >= hold_sec:
            self._edge_gate_blocked = True
            self._edge_gate_changed_ts = now_ts

    def _get_top_of_book(self) -> Tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
        connector = self._connector()
        if connector is None:
            return Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")
        try:
            book = connector.get_order_book(self.config.trading_pair)
        except Exception:
            logger.warning("Order book read failed for %s", self.config.trading_pair, exc_info=True)
            return Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")
        bid_p = Decimal("0")
        ask_p = Decimal("0")
        bid_sz = Decimal("0")
        ask_sz = Decimal("0")
        try:
            best_bid = book.bid_entries()[0]
            bid_p = to_decimal(getattr(best_bid, "price", 0))
            bid_sz = to_decimal(getattr(best_bid, "amount", 0))
        except (IndexError, AttributeError):
            pass
        try:
            best_ask = book.ask_entries()[0]
            ask_p = to_decimal(getattr(best_ask, "price", 0))
            ask_sz = to_decimal(getattr(best_ask, "amount", 0))
        except (IndexError, AttributeError):
            pass
        spread_pct = Decimal("0")
        mid = (bid_p + ask_p) / Decimal("2") if bid_p > 0 and ask_p > 0 else Decimal("0")
        if mid > 0 and ask_p >= bid_p:
            spread_pct = (ask_p - bid_p) / mid
        return bid_p, ask_p, spread_pct, bid_sz, ask_sz

    # ext10: roll on day change only, remove hour condition
    def _maybe_roll_day(self, now_ts: float) -> None:
        dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
        day_key = dt.strftime("%Y-%m-%d")
        if self._daily_key is None:
            self._daily_key = day_key
            return
        if day_key != self._daily_key:
            mid = self._get_mid_price()
            equity_now, _ = self._compute_equity_and_base_pct(mid)
            equity_open = self._daily_equity_open or equity_now
            pnl = equity_now - equity_open
            pnl_pct = (pnl / equity_open) if equity_open > 0 else Decimal("0")
            event_ts = datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()
            self._csv.log_daily(
                {
                    "bot_variant": self.config.variant,
                    "exchange": self.config.connector_name,
                    "trading_pair": self.config.trading_pair,
                    "state": self._ops_guard.state.value,
                    "equity_open_quote": str(equity_open),
                    "equity_now_quote": str(equity_now),
                    "pnl_quote": str(pnl),
                    "pnl_pct": str(pnl_pct),
                    "turnover_x": str(self._traded_notional_today / equity_now) if equity_now > 0 else "0",
                    "fills_count": self._fills_count_today,
                    "ops_events": "|".join(self._ops_guard.reasons),
                },
                ts=event_ts,
            )
            self._daily_key = day_key
            self._daily_equity_open = equity_now
            self._daily_equity_peak = equity_now
            self._traded_notional_today = Decimal("0")
            self._fills_count_today = 0
            self._fees_paid_today_quote = Decimal("0")
            self._funding_cost_today_quote = _ZERO
            self._realized_pnl_today = _ZERO
            self._cancel_events_ts = []
            self._save_daily_state()

    def _daily_state_path(self) -> str:
        from pathlib import Path
        return str(Path(self.config.log_dir) / "epp_v24" / f"{self.config.instance_name}_{self.config.variant}" / "daily_state.json")

    def _load_daily_state(self) -> None:
        """Restore daily state from disk if the day matches."""
        import json
        from pathlib import Path
        path = Path(self._daily_state_path())
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if data.get("day_key") != today:
                return
            self._daily_key = data.get("day_key")
            self._daily_equity_open = to_decimal(data["equity_open"]) if data.get("equity_open") else None
            self._daily_equity_peak = to_decimal(data["equity_peak"]) if data.get("equity_peak") else None
            self._traded_notional_today = to_decimal(data.get("traded_notional", "0"))
            self._fills_count_today = int(data.get("fills_count", 0))
            self._fees_paid_today_quote = to_decimal(data.get("fees_paid", "0"))
            self._funding_cost_today_quote = to_decimal(data.get("funding_cost", "0"))
            self._realized_pnl_today = to_decimal(data.get("realized_pnl", "0"))
            logger.info("Restored daily state for %s (fills=%d, traded=%.2f)", today, self._fills_count_today, self._traded_notional_today)
        except Exception:
            logger.warning("Failed to load daily state from %s", path, exc_info=True)

    def _save_daily_state(self) -> None:
        """Persist daily state to disk for restart recovery."""
        import json
        from pathlib import Path
        path = Path(self._daily_state_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "day_key": self._daily_key,
            "equity_open": str(self._daily_equity_open) if self._daily_equity_open else None,
            "equity_peak": str(self._daily_equity_peak) if self._daily_equity_peak else None,
            "traded_notional": str(self._traded_notional_today),
            "fills_count": self._fills_count_today,
            "fees_paid": str(self._fees_paid_today_quote),
            "funding_cost": str(self._funding_cost_today_quote),
            "realized_pnl": str(self._realized_pnl_today),
            "ts_utc": datetime.now(timezone.utc).isoformat(),
        }
        try:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            logger.warning("Failed to save daily state to %s", path, exc_info=True)

    # ext2: enriched minute.csv with all debug signals
    def _log_minute(
        self,
        now_ts: float,
        event_ts: str,
        mid: Decimal,
        equity_quote: Decimal,
        base_pct: Decimal,
        base_balance: Decimal,
        quote_balance: Decimal,
        target_base_pct: Decimal,
        spread_pct: Decimal,
        net_edge: Decimal,
        turnover_x: Decimal,
        state: GuardState,
        regime: str,
        adverse_drift: Decimal,
        skew: Decimal,
        market_spread_pct: Decimal,
        best_bid_size: Decimal,
        best_ask_size: Decimal,
        daily_loss_pct: Decimal,
        drawdown_pct: Decimal,
        risk_reasons: List[str],
    ) -> None:
        minute_key = int(now_ts // 60)
        if self._last_minute_key == minute_key:
            return
        self._last_minute_key = minute_key
        self._csv.log_minute(
            {
                "bot_variant": self.config.variant,
                "exchange": self.config.connector_name,
                "trading_pair": self.config.trading_pair,
                "state": state.value,
                "regime": regime,
                "mid": str(mid),
                "equity_quote": str(equity_quote),
                "base_pct": str(base_pct),
                "target_base_pct": str(target_base_pct),
                "spread_pct": str(spread_pct),
                "spread_floor_pct": str(self._spread_floor_pct),
                "net_edge_pct": str(net_edge),
                "skew": str(skew),
                "adverse_drift_30s": str(adverse_drift),
                "soft_pause_edge": str(self._soft_pause_edge),
                "base_balance": str(base_balance),
                "quote_balance": str(quote_balance),
                "market_spread_pct": str(market_spread_pct),
                "market_spread_bps": str(market_spread_pct * Decimal("10000")),
                "best_bid_size": str(best_bid_size),
                "best_ask_size": str(best_ask_size),
                "turnover_today_x": str(turnover_x),
                "cancel_per_min": self._cancel_per_min(now_ts),
                "orders_active": len(self.executors_info),
                "fills_count_today": self._fills_count_today,
                "fees_paid_today_quote": str(self._fees_paid_today_quote),
                "daily_loss_pct": str(daily_loss_pct),
                "drawdown_pct": str(drawdown_pct),
                "risk_reasons": "|".join(risk_reasons),
                "fee_source": self._fee_source,
                "maker_fee_pct": str(self._maker_fee_pct),
                "taker_fee_pct": str(self._taker_fee_pct),
            },
            ts=event_ts,
        )
        self._save_daily_state()
