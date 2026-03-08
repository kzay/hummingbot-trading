from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Tuple

from pydantic import Field

from controllers.runtime.base import StrategyRuntimeV24Config, StrategyRuntimeV24Controller
from controllers.runtime.market_making_types import MarketConditions, RegimeSpec, SpreadEdgeState, clip
from services.common.utils import to_decimal

_ZERO = Decimal("0")
_ONE = Decimal("1")
_NEG_ONE = Decimal("-1")
_HUNDRED = Decimal("100")
_10K = Decimal("10000")


class Bot6CvdDivergenceV1Config(StrategyRuntimeV24Config):
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
    bot6_cvd_divergence_threshold_pct: Decimal = Field(default=Decimal("0.15"))
    bot6_stacked_imbalance_min: int = Field(default=3, ge=1, le=20)
    bot6_delta_spike_threshold: Decimal = Field(default=Decimal("3.0"))
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


class Bot6CvdDivergenceV1Controller(StrategyRuntimeV24Controller):
    """Directional controller lane that reuses shared runtime execution plumbing."""

    def __init__(self, config: Bot6CvdDivergenceV1Config, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self._bot6_signal_state: Dict[str, Any] = self._empty_bot6_signal_state()

    def _empty_bot6_signal_state(self) -> Dict[str, Any]:
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

    def _decimal_series(self, df: Any, column: str) -> List[Decimal]:
        if df is None:
            return []
        values = getattr(df, "__getitem__", lambda _key: [])(column)
        raw_values = getattr(values, "values", values)
        return [to_decimal(value) for value in list(raw_values)]

    def _compute_adx(self, highs: List[Decimal], lows: List[Decimal], closes: List[Decimal], period: int) -> Decimal:
        if len(highs) <= period or len(lows) <= period or len(closes) <= period:
            return _ZERO
        trs: List[Decimal] = []
        plus_dms: List[Decimal] = []
        minus_dms: List[Decimal] = []
        for idx in range(1, len(closes)):
            up_move = highs[idx] - highs[idx - 1]
            down_move = lows[idx - 1] - lows[idx]
            plus_dm = up_move if up_move > down_move and up_move > _ZERO else _ZERO
            minus_dm = down_move if down_move > up_move and down_move > _ZERO else _ZERO
            tr = max(
                highs[idx] - lows[idx],
                abs(highs[idx] - closes[idx - 1]),
                abs(lows[idx] - closes[idx - 1]),
            )
            trs.append(max(_ZERO, tr))
            plus_dms.append(plus_dm)
            minus_dms.append(minus_dm)
        if len(trs) < period:
            return _ZERO
        tr_sum = sum(trs[-period:], _ZERO)
        if tr_sum <= _ZERO:
            return _ZERO
        plus_di = _HUNDRED * sum(plus_dms[-period:], _ZERO) / tr_sum
        minus_di = _HUNDRED * sum(minus_dms[-period:], _ZERO) / tr_sum
        di_total = plus_di + minus_di
        if di_total <= _ZERO:
            return _ZERO
        return (_HUNDRED * abs(plus_di - minus_di) / di_total).quantize(Decimal("0.0001"))

    def _get_bot6_candle_signal(self) -> Dict[str, Decimal]:
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

    def _bot6_update_signal_state(self, mid: Decimal) -> Dict[str, Any]:
        candles = self._get_bot6_candle_signal()
        trade_features = self._runtime_adapter.get_directional_trade_features(
            spot_connector_name=str(self.config.bot6_spot_connector_name),
            spot_trading_pair=str(self.config.bot6_spot_trading_pair),
            futures_count=int(self.config.bot6_trade_window_count),
            spot_count=int(self.config.bot6_spot_trade_window_count),
            divergence_threshold_pct=to_decimal(self.config.bot6_cvd_divergence_threshold_pct),
            stacked_imbalance_min=int(self.config.bot6_stacked_imbalance_min),
            delta_spike_threshold=to_decimal(self.config.bot6_delta_spike_threshold),
            funding_rate=to_decimal(getattr(self, "_funding_rate", _ZERO)),
            long_funding_max=to_decimal(self.config.bot6_long_funding_max),
            short_funding_min=to_decimal(self.config.bot6_short_funding_min),
        )
        sma_fast = to_decimal(candles["sma_fast"])
        sma_slow = to_decimal(candles["sma_slow"])
        adx = to_decimal(candles["adx"])
        trend_direction = "flat"
        if sma_fast > sma_slow:
            trend_direction = "long"
        elif sma_fast < sma_slow:
            trend_direction = "short"

        long_score = int(trade_features.long_score)
        short_score = int(trade_features.short_score)
        if adx >= to_decimal(self.config.bot6_adx_threshold):
            if trend_direction == "long":
                long_score += 1
            elif trend_direction == "short":
                short_score += 1

        direction = "off"
        reason = "score_below_threshold"
        score_threshold = max(1, int(self.config.bot6_signal_score_threshold))
        if (
            trend_direction == "long"
            and long_score >= score_threshold
            and not trade_features.stale
        ):
            direction = "buy"
            reason = "bullish_cvd_divergence"
        elif (
            trend_direction == "short"
            and short_score >= score_threshold
            and not trade_features.stale
        ):
            direction = "sell"
            reason = "bearish_cvd_divergence"
        elif trade_features.stale:
            reason = "trade_features_stale"
        elif trend_direction == "flat":
            reason = "trend_filter_flat"

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
        }
        return self._bot6_signal_state

    def _resolve_regime_and_targets(self, mid: Decimal) -> Tuple[str, RegimeSpec, Decimal, Decimal, Decimal]:
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
        base_mode = super()._resolve_quote_side_mode(mid=mid, regime_name=regime_name, regime_spec=regime_spec)
        signal_state = getattr(self, "_bot6_signal_state", None) or self._empty_bot6_signal_state()
        if not bool(signal_state.get("directional_allowed", False)):
            return base_mode
        desired_mode = "buy_only" if str(signal_state.get("direction")) == "buy" else "sell_only"
        previous_mode = str(getattr(self, "_quote_side_mode", base_mode) or "off")
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
    ) -> Tuple[Decimal | None, Decimal | None, Decimal | None]:
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
    ) -> Tuple[list[Decimal], list[Decimal], Decimal, Decimal]:
        buy_spreads, sell_spreads, projected_total_quote, size_mult = super()._compute_levels_and_sizing(
            regime_name, regime_spec, spread_state, equity_quote, mid, market
        )
        signal_state = getattr(self, "_bot6_signal_state", None) or self._empty_bot6_signal_state()
        signal_mult = to_decimal(signal_state.get("size_mult", _ONE))
        if bool(signal_state.get("directional_allowed", False)):
            if str(signal_state.get("direction")) == "buy":
                buy_spreads = buy_spreads[:1]
                sell_spreads = []
            elif str(signal_state.get("direction")) == "sell":
                buy_spreads = []
                sell_spreads = sell_spreads[:1]
        active_levels = max(1, len(buy_spreads) + len(sell_spreads))
        applied_size_mult = max(size_mult, signal_mult)
        projected_total_quote = self._project_total_amount_quote(
            equity_quote=equity_quote,
            mid=mid,
            quote_size_pct=regime_spec.quote_size_pct,
            total_levels=active_levels,
            size_mult=applied_size_mult,
        )
        return buy_spreads, sell_spreads, projected_total_quote, applied_size_mult

    def _emit_tick_output(
        self,
        _t0: float,
        now: float,
        mid: Decimal,
        regime_name: str,
        target_base_pct: Decimal,
        target_net_base_pct: Decimal,
        base_pct_gross: Decimal,
        base_pct_net: Decimal,
        equity_quote: Decimal,
        spread_state: SpreadEdgeState,
        market: MarketConditions,
        risk_hard_stop: bool,
        risk_reasons: List[str],
        daily_loss_pct: Decimal,
        drawdown_pct: Decimal,
        projected_total_quote: Decimal,
        state: Any,
    ) -> None:
        super()._emit_tick_output(
            _t0,
            now,
            mid,
            regime_name,
            target_base_pct,
            target_net_base_pct,
            base_pct_gross,
            base_pct_net,
            equity_quote,
            spread_state,
            market,
            risk_hard_stop,
            risk_reasons,
            daily_loss_pct,
            drawdown_pct,
            projected_total_quote,
            state,
        )
        signal_state = getattr(self, "_bot6_signal_state", None) or self._empty_bot6_signal_state()
        self.processed_data["bot6_signal_side"] = signal_state["direction"]
        self.processed_data["bot6_signal_reason"] = signal_state["reason"]
        self.processed_data["bot6_signal_score_long"] = signal_state["long_score"]
        self.processed_data["bot6_signal_score_short"] = signal_state["short_score"]
        self.processed_data["bot6_signal_score_active"] = signal_state["active_score"]
        self.processed_data["bot6_sma_fast"] = signal_state["sma_fast"]
        self.processed_data["bot6_sma_slow"] = signal_state["sma_slow"]
        self.processed_data["bot6_adx"] = signal_state["adx"]
        self.processed_data["bot6_funding_bias"] = signal_state["funding_bias"]
        self.processed_data["bot6_futures_cvd"] = signal_state["futures_cvd"]
        self.processed_data["bot6_spot_cvd"] = signal_state["spot_cvd"]
        self.processed_data["bot6_cvd_divergence_ratio"] = signal_state["cvd_divergence_ratio"]
        self.processed_data["bot6_stacked_buy_count"] = signal_state["stacked_buy_count"]
        self.processed_data["bot6_stacked_sell_count"] = signal_state["stacked_sell_count"]
        self.processed_data["bot6_delta_spike_ratio"] = signal_state["delta_spike_ratio"]
        self.processed_data["bot6_hedge_state"] = signal_state["hedge_state"]
        self.processed_data["bot6_partial_exit_ratio"] = signal_state["partial_exit_ratio"]
