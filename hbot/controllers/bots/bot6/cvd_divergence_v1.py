from __future__ import annotations

import logging
import math
from collections import deque
from decimal import Decimal
from typing import Any

from pydantic import Field

from controllers.common import indicators as _ind
from controllers.runtime.base import DirectionalStrategyRuntimeV24Config, DirectionalStrategyRuntimeV24Controller
from controllers.runtime.data_context import RuntimeDataContext
from controllers.runtime.execution_context import RuntimeExecutionPlan
from controllers.runtime.runtime_types import MarketConditions, RegimeSpec, SpreadEdgeState, clip
from platform_lib.core.utils import to_decimal

_ZERO = Decimal("0")
_ONE = Decimal("1")
_NEG_ONE = Decimal("-1")
_HUNDRED = Decimal("100")
_10K = Decimal("10000")
_TREND_EPSILON_REL = Decimal("0.0001")

_logger = logging.getLogger(__name__)


class Bot6CvdDivergenceV1Config(DirectionalStrategyRuntimeV24Config):
    """Directional Bitget lane driven by spot-vs-perp CVD divergence."""

    controller_name: str = "bot6_cvd_divergence_v1"
    bot6_spot_connector_name: str = Field(
        default="bitget",
        description="Spot connector used as the reference stream for CVD divergence.",
    )
    bot6_spot_trading_pair: str = Field(
        default="BTC-USDT",
        description="Spot trading pair used for divergence and spot CVD confirmation.",
    )
    bot6_candle_interval: str = Field(default="15m", description="Primary signal timeframe.")
    bot6_sma_fast_period: int = Field(default=50, ge=5, le=400)
    bot6_sma_slow_period: int = Field(default=200, ge=20, le=800)
    bot6_adx_period: int = Field(default=14, ge=5, le=100)
    bot6_adx_threshold: Decimal = Field(default=Decimal("25"), description="Minimum ADX needed for trend activation.")
    bot6_trade_window_count: int = Field(default=120, ge=20, le=500)
    bot6_spot_trade_window_count: int = Field(default=120, ge=20, le=500)
    bot6_trade_features_stale_after_ms: int = Field(
        default=90000,
        ge=5000,
        le=300000,
        description="How long bot6 tolerates trade-flow silence before treating directional features as stale.",
    )
    bot6_cvd_divergence_threshold_pct: Decimal = Field(default=Decimal("0.15"))
    bot6_stacked_imbalance_min: int = Field(default=3, ge=1, le=20)
    bot6_delta_spike_threshold: Decimal = Field(default=Decimal("3.0"))
    bot6_delta_spike_min_baseline: int = Field(
        default=20,
        ge=5,
        le=200,
        description="Minimum number of trades required as baseline for delta spike detection.",
    )
    bot6_signal_score_threshold: int = Field(default=7, ge=1, le=10)
    bot6_directional_target_net_base_pct: Decimal = Field(
        default=Decimal("0.12"),
        description="Maximum signed net-base target when bot6 conviction is active.",
    )
    bot6_dynamic_size_floor_mult: Decimal = Field(default=Decimal("0.80"))
    bot6_dynamic_size_cap_mult: Decimal = Field(default=Decimal("1.50"))
    bot6_long_funding_max: Decimal = Field(default=Decimal("0.0005"))
    bot6_short_funding_min: Decimal = Field(default=Decimal("-0.0003"))
    bot6_partial_exit_on_flip_ratio: Decimal = Field(default=Decimal("0.50"))
    bot6_enable_hedge_bias: bool = Field(default=True)
    bot6_cvd_zscore_window: int = Field(
        default=100,
        ge=0,
        le=1000,
        description="Rolling window for z-score normalization of CVD divergence. 0 disables z-score (legacy raw-divergence mode).",
    )
    bot6_cvd_zscore_threshold: Decimal = Field(
        default=Decimal("2.0"),
        description="Z-score threshold for divergence strength (replaces raw threshold when z-score available).",
    )
    bot6_spot_max_staleness_s: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Maximum age in seconds for spot data before skipping signal generation.",
    )


class Bot6CvdDivergenceV1Controller(DirectionalStrategyRuntimeV24Controller):
    """Directional controller lane that reuses shared runtime execution plumbing."""

    def __init__(self, config: Bot6CvdDivergenceV1Config, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self._bot6_signal_state: dict[str, Any] = self._empty_bot6_signal_state()
        zscore_window = int(config.bot6_cvd_zscore_window)
        self._cvd_divergence_history: deque[float] = deque(maxlen=zscore_window if zscore_window > 0 else 1)
        self._bot6_last_spot_fresh_ts: float = 0.0
        self._bot6_spot_stale_warned: bool = False

    def _empty_bot6_signal_state(self) -> dict[str, Any]:
        return {
            "direction": "off",
            "trend_direction": "flat",
            "directional_allowed": False,
            "long_score": 0,
            "short_score": 0,
            "active_score": 0,
            "reason": "inactive",
            "target_net_base_pct": _ZERO,
            "size_mult": _ONE,
            "sma_fast": _ZERO,
            "sma_slow": _ZERO,
            "adx": _ZERO,
            "funding_rate": _ZERO,
            "funding_bias": "neutral",
            "futures_cvd": _ZERO,
            "spot_cvd": _ZERO,
            "cvd_divergence_ratio": _ZERO,
            "stacked_buy_count": 0,
            "stacked_sell_count": 0,
            "delta_spike_ratio": _ZERO,
            "hedge_state": "inactive",
            "partial_exit_ratio": _ZERO,
        }

    def _bot6_gate_metrics(self) -> dict[str, Any]:
        signal_state = getattr(self, "_bot6_signal_state", None) or self._empty_bot6_signal_state()
        reason = str(signal_state.get("reason", "inactive"))
        directional_allowed = bool(signal_state.get("directional_allowed", False))
        fail_closed = reason == "trade_features_warmup"
        if fail_closed:
            gate_state = "blocked"
        elif directional_allowed:
            gate_state = "active"
        else:
            gate_state = "idle"
        threshold = max(1, int(getattr(self.config, "bot6_signal_score_threshold", 7)))
        score = to_decimal(signal_state.get("active_score", 0))
        score_ratio = clip(score / Decimal(threshold), _ZERO, _ONE)
        return {
            "state": gate_state,
            "reason": reason,
            "fail_closed": fail_closed,
            "score_ratio": score_ratio,
        }

    def _compute_alpha_policy(
        self,
        *,
        regime_name: str,
        spread_state: SpreadEdgeState,
        market: MarketConditions,
        target_net_base_pct: Decimal,
        base_pct_net: Decimal,
    ) -> dict[str, Decimal | str | bool]:
        gate = self._bot6_gate_metrics()
        score_ratio = to_decimal(gate["score_ratio"])
        metrics: dict[str, Decimal | str | bool] = {
            "state": "bot6_strategy_gate",
            "reason": str(gate["reason"]),
            "maker_score": score_ratio,
            "aggressive_score": _ZERO,
            "cross_allowed": False,
        }
        self._alpha_policy_state = str(metrics["state"])
        self._alpha_policy_reason = str(metrics["reason"])
        self._alpha_maker_score = score_ratio
        self._alpha_aggressive_score = _ZERO
        self._alpha_cross_allowed = False
        return metrics

    def _evaluate_all_risk(
        self,
        spread_state: SpreadEdgeState,
        base_pct_gross: Decimal,
        equity_quote: Decimal,
        projected_total_quote: Decimal,
        market: MarketConditions,
    ) -> tuple[list[str], bool, Decimal, Decimal]:
        risk_reasons, risk_hard_stop, daily_loss_pct, drawdown_pct = super()._evaluate_all_risk(
            spread_state=spread_state,
            base_pct_gross=base_pct_gross,
            equity_quote=equity_quote,
            projected_total_quote=projected_total_quote,
            market=market,
        )
        gate = self._bot6_gate_metrics()
        if bool(gate["fail_closed"]):
            gate_reason = f"bot6_{gate['reason']}"
            if gate_reason not in risk_reasons:
                risk_reasons.append(gate_reason)
        return risk_reasons, risk_hard_stop, daily_loss_pct, drawdown_pct

    def _decimal_series(self, df: Any, column: str) -> list[Decimal]:
        if df is None:
            return []
        values = getattr(df, "__getitem__", lambda _key: [])(column)
        raw_values = getattr(values, "values", values)
        return [to_decimal(value) for value in list(raw_values)]

    def _compute_adx(self, highs: list[Decimal], lows: list[Decimal], closes: list[Decimal], period: int) -> Decimal:
        """Compute ADX via the shared Wilder implementation in controllers.common.indicators."""
        bars_hlc = list(zip(highs, lows, closes, strict=True))
        result = _ind.adx(bars_hlc, period)
        return result if result is not None else _ZERO

    def _get_bot6_candle_signal(self) -> dict[str, Decimal]:
        needed = max(
            int(self.config.bot6_sma_slow_period) + 5,
            int(self.config.bot6_adx_period) + 5,
        )
        try:
            df = self.market_data_provider.get_candles_df(
                self.config.candles_connector or self.config.connector_name,
                self.config.candles_trading_pair or self.config.trading_pair,
                self.config.bot6_candle_interval,
                needed,
            )
        except Exception:
            return {"sma_fast": _ZERO, "sma_slow": _ZERO, "adx": _ZERO}
        if df is None or len(df) < needed:
            return {"sma_fast": _ZERO, "sma_slow": _ZERO, "adx": _ZERO}
        closes = self._decimal_series(df, "close")
        highs = self._decimal_series(df, "high")
        lows = self._decimal_series(df, "low")
        fast_period = int(self.config.bot6_sma_fast_period)
        slow_period = int(self.config.bot6_sma_slow_period)
        if len(closes) < slow_period or len(highs) < slow_period or len(lows) < slow_period:
            return {"sma_fast": _ZERO, "sma_slow": _ZERO, "adx": _ZERO}
        sma_fast = sum(closes[-fast_period:], _ZERO) / Decimal(fast_period)
        sma_slow = sum(closes[-slow_period:], _ZERO) / Decimal(slow_period)
        adx = self._compute_adx(highs, lows, closes, int(self.config.bot6_adx_period))
        return {"sma_fast": sma_fast, "sma_slow": sma_slow, "adx": adx}

    def _bot6_update_signal_state(self, mid: Decimal) -> dict[str, Any]:
        candles = self._get_bot6_candle_signal()
        trade_features = self._runtime_adapter.get_directional_trade_features(
            spot_connector_name=str(self.config.bot6_spot_connector_name),
            spot_trading_pair=str(self.config.bot6_spot_trading_pair),
            futures_count=int(self.config.bot6_trade_window_count),
            spot_count=int(self.config.bot6_spot_trade_window_count),
            stale_after_ms=int(getattr(self.config, "bot6_trade_features_stale_after_ms", 90000)),
            divergence_threshold_pct=to_decimal(self.config.bot6_cvd_divergence_threshold_pct),
            stacked_imbalance_min=int(self.config.bot6_stacked_imbalance_min),
            delta_spike_threshold=to_decimal(self.config.bot6_delta_spike_threshold),
            delta_spike_min_baseline=int(self.config.bot6_delta_spike_min_baseline),
            funding_rate=to_decimal(getattr(self, "_funding_rate", _ZERO)),
            long_funding_max=to_decimal(self.config.bot6_long_funding_max),
            short_funding_min=to_decimal(self.config.bot6_short_funding_min),
        )
        sma_fast = to_decimal(candles["sma_fast"])
        sma_slow = to_decimal(candles["sma_slow"])
        adx = to_decimal(candles["adx"])
        trend_direction = "flat"
        sma_epsilon = sma_slow * _TREND_EPSILON_REL if sma_slow > _ZERO else Decimal("0.01")
        if sma_fast > sma_slow + sma_epsilon:
            trend_direction = "long"
        elif sma_fast < sma_slow - sma_epsilon:
            trend_direction = "short"

        long_score = int(trade_features.long_score)
        short_score = int(trade_features.short_score)
        if adx >= to_decimal(self.config.bot6_adx_threshold):
            if trend_direction == "long":
                long_score += 1
            elif trend_direction == "short":
                short_score += 1
        if trend_direction == "flat":
            if long_score > short_score:
                trend_direction = "long"
            elif short_score > long_score:
                trend_direction = "short"

        futures_stale = bool(trade_features.futures.stale)
        spot_stale = bool(trade_features.spot.stale)

        now_ts = float(self.market_data_provider.time())
        if not spot_stale:
            self._bot6_last_spot_fresh_ts = now_ts
            self._bot6_spot_stale_warned = False
        if self._bot6_last_spot_fresh_ts > 0:
            spot_age_s = now_ts - self._bot6_last_spot_fresh_ts
            if spot_age_s > float(self.config.bot6_spot_max_staleness_s):
                spot_stale = True
                if not self._bot6_spot_stale_warned:
                    _logger.warning(
                        "bot6 spot data stale for %.1fs (threshold=%ds), skipping signal generation",
                        spot_age_s,
                        self.config.bot6_spot_max_staleness_s,
                    )
                    self._bot6_spot_stale_warned = True

        direction = "off"
        reason = "score_below_threshold"
        score_threshold = max(1, int(self.config.bot6_signal_score_threshold))
        if futures_stale:
            reason = "trade_features_warmup"
        elif spot_stale:
            reason = "spot_data_stale"
        elif (
            trend_direction == "long"
            and long_score >= score_threshold
        ):
            direction = "buy"
            reason = "bullish_cvd_divergence" if not spot_stale else "bullish_futures_only"
        elif (
            trend_direction == "short"
            and short_score >= score_threshold
        ):
            direction = "sell"
            reason = "bearish_cvd_divergence" if not spot_stale else "bearish_futures_only"
        elif trend_direction == "flat":
            reason = "trend_filter_flat"

        raw_divergence = float(to_decimal(trade_features.cvd_divergence_ratio))
        zscore_window = int(self.config.bot6_cvd_zscore_window)
        if zscore_window > 0:
            self._cvd_divergence_history.append(raw_divergence)
            if len(self._cvd_divergence_history) >= zscore_window:
                hist = list(self._cvd_divergence_history)
                mean_d = sum(hist) / len(hist)
                var_d = sum((x - mean_d) ** 2 for x in hist) / len(hist)
                std_d = math.sqrt(var_d) if var_d > 0 else 0.0
                if std_d > 1e-12:
                    zscore = abs((raw_divergence - mean_d) / std_d)
                    zscore_threshold = max(0.5, float(self.config.bot6_cvd_zscore_threshold))
                    divergence_strength = clip(Decimal(str(zscore / zscore_threshold)), _ZERO, _ONE)
                else:
                    divergence_strength = _ZERO
            else:
                divergence_strength = clip(
                    abs(to_decimal(trade_features.cvd_divergence_ratio))
                    / max(Decimal("0.0001"), abs(to_decimal(self.config.bot6_cvd_divergence_threshold_pct))),
                    _ZERO,
                    _ONE,
                )
        else:
            divergence_strength = clip(
                abs(to_decimal(trade_features.cvd_divergence_ratio))
                / max(Decimal("0.0001"), abs(to_decimal(self.config.bot6_cvd_divergence_threshold_pct))),
                _ZERO,
                _ONE,
            )
        size_mult = clip(
            to_decimal(self.config.bot6_dynamic_size_floor_mult)
            + divergence_strength
            * (to_decimal(self.config.bot6_dynamic_size_cap_mult) - to_decimal(self.config.bot6_dynamic_size_floor_mult)),
            to_decimal(self.config.bot6_dynamic_size_floor_mult),
            to_decimal(self.config.bot6_dynamic_size_cap_mult),
        )
        target_abs = clip(
            to_decimal(self.config.bot6_directional_target_net_base_pct) * size_mult,
            _ZERO,
            to_decimal(getattr(self.config, "max_base_pct", self.config.bot6_directional_target_net_base_pct)),
        )
        target_net_base_pct = _ZERO
        if direction == "buy":
            target_net_base_pct = target_abs
        elif direction == "sell":
            target_net_base_pct = -target_abs

        hedge_state = "inactive"
        partial_exit_ratio = _ZERO
        current_position = to_decimal(getattr(self, "_position_base", _ZERO))
        if bool(self.config.bot6_enable_hedge_bias) and current_position > _ZERO and direction == "sell":
            hedge_state = "candidate_short_hedge"
            partial_exit_ratio = to_decimal(self.config.bot6_partial_exit_on_flip_ratio)
        elif bool(self.config.bot6_enable_hedge_bias) and current_position < _ZERO and direction == "buy":
            hedge_state = "candidate_long_hedge"
            partial_exit_ratio = to_decimal(self.config.bot6_partial_exit_on_flip_ratio)

        self._bot6_signal_state = {
            "direction": direction,
            "trend_direction": trend_direction,
            "directional_allowed": direction in {"buy", "sell"},
            "long_score": long_score,
            "short_score": short_score,
            "active_score": max(long_score, short_score),
            "reason": reason,
            "target_net_base_pct": target_net_base_pct,
            "size_mult": size_mult,
            "sma_fast": sma_fast,
            "sma_slow": sma_slow,
            "adx": adx,
            "funding_rate": to_decimal(trade_features.funding_rate),
            "funding_bias": str(trade_features.funding_bias),
            "futures_cvd": to_decimal(trade_features.futures.cvd),
            "spot_cvd": to_decimal(trade_features.spot.cvd),
            "cvd_divergence_ratio": to_decimal(trade_features.cvd_divergence_ratio),
            "stacked_buy_count": int(trade_features.futures.stacked_buy_count),
            "stacked_sell_count": int(trade_features.futures.stacked_sell_count),
            "delta_spike_ratio": to_decimal(trade_features.futures.delta_spike_ratio),
            "hedge_state": hedge_state,
            "partial_exit_ratio": partial_exit_ratio,
            "futures_stale": futures_stale,
            "spot_stale": spot_stale,
        }
        return self._bot6_signal_state

    def _resolve_regime_and_targets(self, mid: Decimal) -> tuple[str, RegimeSpec, Decimal, Decimal, Decimal]:
        regime_name, regime_spec, target_base_pct, target_net_base_pct, band_pct = super()._resolve_regime_and_targets(mid)
        signal_state = self._bot6_update_signal_state(mid=mid)
        if bool(getattr(self, "_is_perp", False)) and bool(signal_state.get("directional_allowed", False)):
            target_net_base_pct = to_decimal(signal_state["target_net_base_pct"])
        return regime_name, regime_spec, target_base_pct, target_net_base_pct, band_pct

    def _resolve_quote_side_mode(
        self,
        *,
        mid: Decimal,
        regime_name: str,
        regime_spec: RegimeSpec,
    ) -> str:
        signal_state = getattr(self, "_bot6_signal_state", None) or self._empty_bot6_signal_state()
        gate = self._bot6_gate_metrics()

        if gate["fail_closed"]:
            self._pending_stale_cancel_actions.extend(self._cancel_active_quote_executors())
            self._cancel_alpha_no_trade_orders()
            self._quote_side_mode = "off"
            self._quote_side_reason = f"bot6_{gate['reason']}"
            return "off"

        if not bool(signal_state.get("directional_allowed", False)):
            self._pending_stale_cancel_actions.extend(self._cancel_active_quote_executors())
            self._cancel_alpha_no_trade_orders()
            self._quote_side_mode = "off"
            self._quote_side_reason = "bot6_no_signal"
            return "off"
        desired_mode = "buy_only" if str(signal_state.get("direction")) == "buy" else "sell_only"
        previous_mode = str(getattr(self, "_quote_side_mode", "off") or "off")
        if previous_mode != desired_mode:
            self._pending_stale_cancel_actions.extend(
                self._cancel_stale_side_executors(previous_mode, desired_mode)
            )
        self._quote_side_mode = desired_mode
        self._quote_side_reason = f"bot6_{signal_state['reason']}"
        return desired_mode

    def _compute_adaptive_spread_knobs(
        self,
        now_ts: float,
        equity_quote: Decimal,
        regime_name: str = "neutral_low_vol",
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
        effective_min_edge_pct, market_floor_pct, vol_ratio = super()._compute_adaptive_spread_knobs(
            now_ts, equity_quote, regime_name
        )
        if effective_min_edge_pct is None or market_floor_pct is None:
            return effective_min_edge_pct, market_floor_pct, vol_ratio
        signal_state = getattr(self, "_bot6_signal_state", None) or self._empty_bot6_signal_state()
        if bool(signal_state.get("directional_allowed", False)):
            market_floor_pct += Decimal("0.25") / _10K
        self._adaptive_market_floor_pct = max(_ZERO, market_floor_pct)
        return effective_min_edge_pct, max(_ZERO, market_floor_pct), vol_ratio

    def _compute_levels_and_sizing(
        self,
        regime_name: str,
        regime_spec: RegimeSpec,
        spread_state: SpreadEdgeState,
        equity_quote: Decimal,
        mid: Decimal,
        market: MarketConditions,
    ) -> tuple[list[Decimal], list[Decimal], Decimal, Decimal]:
        plan = self.build_runtime_execution_plan(
            RuntimeDataContext(
                now_ts=float(self.market_data_provider.time()),
                mid=mid,
                regime_name=regime_name,
                regime_spec=regime_spec,
                spread_state=spread_state,
                market=market,
                equity_quote=equity_quote,
                target_base_pct=regime_spec.target_base_pct,
                target_net_base_pct=to_decimal(getattr(self, "processed_data", {}).get("target_net_base_pct", regime_spec.target_base_pct)),
                base_pct_gross=to_decimal(getattr(self, "processed_data", {}).get("base_pct", _ZERO)),
                base_pct_net=to_decimal(getattr(self, "processed_data", {}).get("net_base_pct", _ZERO)),
            )
        )
        return plan.buy_spreads, plan.sell_spreads, plan.projected_total_quote, plan.size_mult

    def build_runtime_execution_plan(self, data_context: RuntimeDataContext) -> RuntimeExecutionPlan:
        signal_state = getattr(self, "_bot6_signal_state", None) or self._empty_bot6_signal_state()

        if not bool(signal_state.get("directional_allowed", False)):
            return RuntimeExecutionPlan(
                family="directional",
                buy_spreads=[],
                sell_spreads=[],
                projected_total_quote=_ZERO,
                size_mult=_ZERO,
                metadata={
                    "strategy_lane": "bot6",
                    "quote_side_mode": str(getattr(self, "_quote_side_mode", "off")),
                    "quote_side_reason": str(getattr(self, "_quote_side_reason", "bot6_no_signal")),
                    "directional_allowed": False,
                },
            )

        base_plan = super().build_runtime_execution_plan(data_context)
        signal_mult = to_decimal(signal_state.get("size_mult", _ONE))
        buy_spreads = list(base_plan.buy_spreads)
        sell_spreads = list(base_plan.sell_spreads)
        if str(signal_state.get("direction")) == "buy":
            buy_spreads = buy_spreads[:1] or [data_context.market.side_spread_floor]
            sell_spreads = []
        elif str(signal_state.get("direction")) == "sell":
            buy_spreads = []
            sell_spreads = sell_spreads[:1] or [data_context.market.side_spread_floor]
        active_levels = len(buy_spreads) + len(sell_spreads)
        applied_size_mult = max(base_plan.size_mult, signal_mult)
        projected_total_quote = self._project_total_amount_quote(
            equity_quote=data_context.equity_quote,
            mid=data_context.mid,
            quote_size_pct=data_context.regime_spec.quote_size_pct,
            total_levels=active_levels,
            size_mult=applied_size_mult,
        )
        return RuntimeExecutionPlan(
            family="directional",
            buy_spreads=buy_spreads,
            sell_spreads=sell_spreads,
            projected_total_quote=projected_total_quote,
            size_mult=applied_size_mult,
            metadata={
                **dict(base_plan.metadata),
                "strategy_lane": "bot6",
                "quote_side_mode": str(getattr(self, "_quote_side_mode", "off")),
                "quote_side_reason": str(getattr(self, "_quote_side_reason", "regime")),
                "directional_allowed": True,
            },
        )

    def _extend_processed_data_before_log(
        self,
        *,
        processed_data: dict[str, Any],
        snapshot: dict[str, Any],
        state: Any,
        regime_name: str,
        market: MarketConditions,
        projected_total_quote: Decimal,
    ) -> None:
        signal_state = getattr(self, "_bot6_signal_state", None) or self._empty_bot6_signal_state()
        processed_data["bot6_signal_side"] = signal_state["direction"]
        processed_data["bot6_signal_reason"] = signal_state["reason"]
        processed_data["bot6_gate_state"] = self._bot6_gate_metrics()["state"]
        processed_data["bot6_gate_reason"] = self._bot6_gate_metrics()["reason"]
        processed_data["bot6_signal_score"] = signal_state["active_score"]
        processed_data["bot6_signal_score_long"] = signal_state["long_score"]
        processed_data["bot6_signal_score_short"] = signal_state["short_score"]
        processed_data["bot6_signal_score_active"] = signal_state["active_score"]
        processed_data["bot6_sma_fast"] = signal_state["sma_fast"]
        processed_data["bot6_sma_slow"] = signal_state["sma_slow"]
        processed_data["bot6_adx"] = signal_state["adx"]
        processed_data["bot6_funding_bias"] = signal_state["funding_bias"]
        processed_data["bot6_futures_cvd"] = signal_state["futures_cvd"]
        processed_data["bot6_spot_cvd"] = signal_state["spot_cvd"]
        processed_data["bot6_cvd_divergence_ratio"] = signal_state["cvd_divergence_ratio"]
        processed_data["bot6_stacked_buy_count"] = signal_state["stacked_buy_count"]
        processed_data["bot6_stacked_sell_count"] = signal_state["stacked_sell_count"]
        processed_data["bot6_delta_spike_ratio"] = signal_state["delta_spike_ratio"]
        processed_data["bot6_hedge_state"] = signal_state["hedge_state"]
        processed_data["bot6_partial_exit_ratio"] = signal_state["partial_exit_ratio"]
        processed_data["bot6_futures_stale"] = signal_state.get("futures_stale", True)
        processed_data["bot6_spot_stale"] = signal_state.get("spot_stale", True)

    def telemetry_fields(self) -> tuple[tuple[str, str, Any], ...]:
        return (
            ("bot6_signal_side", "bot6_signal_side", "off"),
            ("bot6_signal_reason", "bot6_signal_reason", "inactive"),
            ("bot6_gate_state", "bot6_gate_state", "idle"),
            ("bot6_gate_reason", "bot6_gate_reason", "inactive"),
            ("bot6_signal_score", "bot6_signal_score", 0),
            ("bot6_signal_score_long", "bot6_signal_score_long", 0),
            ("bot6_signal_score_short", "bot6_signal_score_short", 0),
            ("bot6_signal_score_active", "bot6_signal_score_active", 0),
            ("bot6_sma_fast", "bot6_sma_fast", _ZERO),
            ("bot6_sma_slow", "bot6_sma_slow", _ZERO),
            ("bot6_adx", "bot6_adx", _ZERO),
            ("bot6_funding_bias", "bot6_funding_bias", "neutral"),
            ("bot6_futures_cvd", "bot6_futures_cvd", _ZERO),
            ("bot6_spot_cvd", "bot6_spot_cvd", _ZERO),
            ("bot6_cvd_divergence_ratio", "bot6_cvd_divergence_ratio", _ZERO),
            ("bot6_stacked_buy_count", "bot6_stacked_buy_count", 0),
            ("bot6_stacked_sell_count", "bot6_stacked_sell_count", 0),
            ("bot6_delta_spike_ratio", "bot6_delta_spike_ratio", _ZERO),
            ("bot6_hedge_state", "bot6_hedge_state", "inactive"),
            ("bot6_partial_exit_ratio", "bot6_partial_exit_ratio", _ZERO),
        )
