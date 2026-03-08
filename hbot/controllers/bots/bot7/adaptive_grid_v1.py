from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Tuple

from pydantic import Field

from controllers.runtime.base import StrategyRuntimeV24Config, StrategyRuntimeV24Controller
from controllers.runtime.market_making_types import MarketConditions, RegimeSpec, SpreadEdgeState, clip
from services.common.market_data_plane import CanonicalMarketDataReader, MarketTrade
from services.common.utils import to_decimal

_ZERO = Decimal("0")
_ONE = Decimal("1")
_NEG_ONE = Decimal("-1")
_TWO = Decimal("2")
_THREE = Decimal("3")
_10K = Decimal("10000")


class Bot7AdaptiveGridV1Config(StrategyRuntimeV24Config):
    """Bot7 adaptive absorption grid strategy lane."""

    controller_name: str = "bot7_adaptive_grid_v1"
    bot7_bb_period: int = Field(default=20, ge=10, le=100)
    bot7_bb_stddev: Decimal = Field(default=Decimal("2.0"))
    bot7_rsi_period: int = Field(default=14, ge=5, le=50)
    bot7_rsi_buy_threshold: Decimal = Field(default=Decimal("32"))
    bot7_rsi_sell_threshold: Decimal = Field(default=Decimal("68"))
    bot7_adx_period: int = Field(default=14, ge=5, le=50)
    bot7_adx_activate_below: Decimal = Field(default=Decimal("20"))
    bot7_trade_window_count: int = Field(default=160, ge=20, le=600)
    bot7_trade_stale_after_ms: int = Field(default=15_000, ge=1000, le=120_000)
    bot7_absorption_min_trade_mult: Decimal = Field(default=Decimal("2.5"))
    bot7_absorption_max_price_drift_pct: Decimal = Field(default=Decimal("0.0015"))
    bot7_delta_trap_window: int = Field(default=24, ge=8, le=120)
    bot7_delta_trap_reversal_share: Decimal = Field(default=Decimal("0.30"))
    bot7_grid_spacing_atr_mult: Decimal = Field(default=Decimal("0.50"))
    bot7_grid_spacing_floor_pct: Decimal = Field(default=Decimal("0.0015"))
    bot7_grid_spacing_cap_pct: Decimal = Field(default=Decimal("0.0100"))
    bot7_max_grid_legs: int = Field(default=3, ge=1, le=6)
    bot7_per_leg_risk_pct: Decimal = Field(default=Decimal("0.003"))
    bot7_total_grid_exposure_cap_pct: Decimal = Field(default=Decimal("0.015"))
    bot7_hedge_ratio: Decimal = Field(default=Decimal("0.30"))
    bot7_funding_long_bias_threshold: Decimal = Field(default=Decimal("-0.0003"))
    bot7_funding_short_bias_threshold: Decimal = Field(default=Decimal("0.0003"))
    bot7_funding_vol_reduce_threshold: Decimal = Field(default=Decimal("0.0010"))
    bot7_trade_reader_enabled: bool = Field(default=True)


class Bot7AdaptiveGridV1Controller(StrategyRuntimeV24Controller):
    """Adaptive absorption grid wrapper over the shared runtime controller."""

    def __init__(self, config: Bot7AdaptiveGridV1Config, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self._bot7_state: Dict[str, Any] = self._empty_bot7_state()
        self._bot7_last_funding_rate: Decimal = _ZERO
        self._trade_reader = CanonicalMarketDataReader(
            connector_name=str(config.connector_name),
            trading_pair=str(config.trading_pair),
            enabled=bool(getattr(config, "bot7_trade_reader_enabled", True)),
            stale_after_ms=int(getattr(config, "bot7_trade_stale_after_ms", 15_000)),
        )

    def _empty_bot7_state(self) -> Dict[str, Any]:
        return {
            "active": False,
            "side": "off",
            "reason": "inactive",
            "bb_lower": _ZERO,
            "bb_basis": _ZERO,
            "bb_upper": _ZERO,
            "rsi": Decimal("50"),
            "adx": _ZERO,
            "atr": _ZERO,
            "grid_spacing_pct": _ZERO,
            "trade_age_ms": 0,
            "trade_flow_stale": True,
            "cvd": _ZERO,
            "delta_volume": _ZERO,
            "recent_delta": _ZERO,
            "absorption_long": False,
            "absorption_short": False,
            "delta_trap_long": False,
            "delta_trap_short": False,
            "signal_score": _ZERO,
            "grid_levels": 0,
            "target_net_base_pct": _ZERO,
            "hedge_target_base_pct": _ZERO,
            "funding_bias": "neutral",
            "funding_risk_scale": _ONE,
            "order_book_imbalance": _ZERO,
        }

    def _trade_age_ms(self, trades: List[MarketTrade]) -> int:
        if not trades:
            return 10**9
        latest_ts_ms = max(int(tr.exchange_ts_ms or tr.ingest_ts_ms or 0) for tr in trades)
        if latest_ts_ms <= 0:
            return 10**9
        provider = getattr(self, "market_data_provider", None)
        if provider is not None:
            now_ms = int(float(provider.time()) * 1000)
        else:
            import time as _time_mod

            now_ms = int(_time_mod.time() * 1000)
        return max(0, now_ms - latest_ts_ms)

    def _funding_bias(self, funding_rate: Decimal) -> str:
        if funding_rate <= to_decimal(getattr(self.config, "bot7_funding_long_bias_threshold", Decimal("-0.0003"))):
            return "long"
        if funding_rate >= to_decimal(getattr(self.config, "bot7_funding_short_bias_threshold", Decimal("0.0003"))):
            return "short"
        return "neutral"

    def _funding_risk_scale(self, funding_rate: Decimal) -> Decimal:
        vol_threshold = to_decimal(getattr(self.config, "bot7_funding_vol_reduce_threshold", Decimal("0.0010")))
        delta = abs(funding_rate - getattr(self, "_bot7_last_funding_rate", _ZERO))
        self._bot7_last_funding_rate = funding_rate
        return Decimal("0.50") if delta >= vol_threshold else _ONE

    def _detect_absorption(
        self,
        *,
        trades: List[MarketTrade],
        mid: Decimal,
        lower_band: Decimal,
        upper_band: Decimal,
    ) -> Tuple[bool, bool]:
        if len(trades) < 6 or mid <= _ZERO:
            return False, False
        recent = trades[-12:]
        avg_size = sum((trade.size for trade in recent), _ZERO) / Decimal(len(recent))
        if avg_size <= _ZERO:
            return False, False
        max_trade = max((trade.size for trade in recent), default=_ZERO)
        total_delta = sum((trade.delta for trade in recent), _ZERO)
        first_price = recent[0].price
        last_price = recent[-1].price
        if first_price <= _ZERO or last_price <= _ZERO:
            return False, False
        price_drift_pct = abs(last_price - first_price) / first_price
        drift_ok = price_drift_pct <= to_decimal(
            getattr(self.config, "bot7_absorption_max_price_drift_pct", Decimal("0.0015"))
        )
        size_ok = max_trade >= avg_size * to_decimal(
            getattr(self.config, "bot7_absorption_min_trade_mult", Decimal("2.5"))
        )
        long_absorption = drift_ok and size_ok and last_price <= lower_band and total_delta > _ZERO
        short_absorption = drift_ok and size_ok and last_price >= upper_band and total_delta < _ZERO
        return long_absorption, short_absorption

    def _detect_delta_trap(
        self,
        *,
        trades: List[MarketTrade],
        lower_band: Decimal,
        upper_band: Decimal,
    ) -> Tuple[bool, bool, Decimal]:
        window = max(8, int(getattr(self.config, "bot7_delta_trap_window", 24)))
        if len(trades) < window:
            return False, False, _ZERO
        recent = trades[-window:]
        split_idx = max(1, int(window * (Decimal("1") - to_decimal(getattr(self.config, "bot7_delta_trap_reversal_share", Decimal("0.30"))))))
        early = recent[:split_idx]
        late = recent[split_idx:]
        if not early or not late or recent[0].price <= _ZERO:
            return False, False, _ZERO
        early_delta = sum((trade.delta for trade in early), _ZERO)
        late_delta = sum((trade.delta for trade in late), _ZERO)
        total_delta = early_delta + late_delta
        price_change_pct = (recent[-1].price - recent[0].price) / recent[0].price
        bullish = recent[-1].price <= lower_band and total_delta < _ZERO and late_delta > _ZERO and price_change_pct >= Decimal("-0.0010")
        bearish = recent[-1].price >= upper_band and total_delta > _ZERO and late_delta < _ZERO and price_change_pct <= Decimal("0.0010")
        return bullish, bearish, total_delta

    def _load_recent_trades(self) -> List[MarketTrade]:
        reader = getattr(self, "_trade_reader", None)
        if reader is None:
            return []
        try:
            return reader.recent_trades(count=int(getattr(self.config, "bot7_trade_window_count", 160)))
        except Exception:
            return []

    def _update_bot7_state(self, mid: Decimal, regime_name: str) -> Dict[str, Any]:
        bb_period = int(getattr(self.config, "bot7_bb_period", 20))
        rsi_period = int(getattr(self.config, "bot7_rsi_period", 14))
        adx_period = int(getattr(self.config, "bot7_adx_period", 14))
        atr_period = int(getattr(self.config, "atr_period", 14))

        bands = self._price_buffer.bollinger_bands(
            period=bb_period,
            stddev_mult=to_decimal(getattr(self.config, "bot7_bb_stddev", Decimal("2.0"))),
        )
        rsi = self._price_buffer.rsi(rsi_period)
        adx = self._price_buffer.adx(adx_period)
        atr = self._price_buffer.atr(atr_period)
        trades = self._load_recent_trades()
        trade_age_ms = self._trade_age_ms(trades)
        trade_stale = trade_age_ms > int(getattr(self.config, "bot7_trade_stale_after_ms", 15_000))
        funding_rate = to_decimal(getattr(self, "_funding_rate", _ZERO))
        funding_bias = self._funding_bias(funding_rate)
        funding_risk_scale = self._funding_risk_scale(funding_rate)
        depth_imbalance = _ZERO
        reader = getattr(self, "_trade_reader", None)
        if reader is not None:
            try:
                depth_imbalance = clip(to_decimal(reader.get_depth_imbalance(depth=5)), _NEG_ONE, _ONE)
            except Exception:
                depth_imbalance = _ZERO

        if bands is None or rsi is None or adx is None or atr is None or mid <= _ZERO:
            self._bot7_state = self._empty_bot7_state()
            self._bot7_state.update(
                {
                    "reason": "indicator_warmup",
                    "trade_age_ms": trade_age_ms,
                    "trade_flow_stale": trade_stale,
                    "funding_bias": funding_bias,
                    "funding_risk_scale": funding_risk_scale,
                    "order_book_imbalance": depth_imbalance,
                }
            )
            return self._bot7_state

        bb_lower, bb_basis, bb_upper = bands
        absorption_long, absorption_short = self._detect_absorption(
            trades=trades,
            mid=mid,
            lower_band=bb_lower,
            upper_band=bb_upper,
        )
        delta_trap_long, delta_trap_short, cvd = self._detect_delta_trap(
            trades=trades,
            lower_band=bb_lower,
            upper_band=bb_upper,
        )
        recent_delta = sum((trade.delta for trade in trades[-12:]), _ZERO) if trades else _ZERO
        delta_volume = sum((trade.delta for trade in trades), _ZERO) if trades else _ZERO
        adx_active = adx < to_decimal(getattr(self.config, "bot7_adx_activate_below", Decimal("20")))
        regime_active = adx_active or funding_bias != "neutral"
        touch_eps = to_decimal(getattr(self.config, "bot7_grid_spacing_floor_pct", Decimal("0.0015")))
        touch_lower = mid <= bb_lower * (_ONE + touch_eps)
        touch_upper = mid >= bb_upper * (_ONE - touch_eps)
        long_signal = regime_active and not trade_stale and touch_lower and rsi <= to_decimal(
            getattr(self.config, "bot7_rsi_buy_threshold", Decimal("32"))
        ) and (absorption_long or delta_trap_long)
        short_signal = regime_active and not trade_stale and touch_upper and rsi >= to_decimal(
            getattr(self.config, "bot7_rsi_sell_threshold", Decimal("68"))
        ) and (absorption_short or delta_trap_short)

        side = "off"
        reason = "no_entry"
        if long_signal and not short_signal:
            side = "buy"
            reason = "mean_reversion_long"
        elif short_signal and not long_signal:
            side = "sell"
            reason = "mean_reversion_short"
        elif trade_stale:
            reason = "trade_flow_stale"
        elif not regime_active:
            reason = "regime_inactive"

        signal_components = sum(
            1
            for flag in (
                absorption_long if side == "buy" else absorption_short,
                delta_trap_long if side == "buy" else delta_trap_short,
                regime_active,
            )
            if flag
        )
        signal_score = clip(Decimal(signal_components) / _THREE, _ZERO, _ONE)
        spacing_pct = clip(
            (atr * to_decimal(getattr(self.config, "bot7_grid_spacing_atr_mult", Decimal("0.50"))) / mid)
            if mid > _ZERO
            else _ZERO,
            to_decimal(getattr(self.config, "bot7_grid_spacing_floor_pct", Decimal("0.0015"))),
            to_decimal(getattr(self.config, "bot7_grid_spacing_cap_pct", Decimal("0.0100"))),
        )
        grid_levels = 0
        if side != "off":
            grid_levels = min(
                int(getattr(self.config, "bot7_max_grid_legs", 3)),
                max(1, int((signal_score * Decimal(getattr(self.config, "bot7_max_grid_legs", 3))).to_integral_value(rounding="ROUND_CEILING"))),
            )
        per_leg_risk = to_decimal(getattr(self.config, "bot7_per_leg_risk_pct", Decimal("0.003")))
        target_abs = clip(
            per_leg_risk * Decimal(grid_levels) * funding_risk_scale,
            _ZERO,
            to_decimal(getattr(self.config, "bot7_total_grid_exposure_cap_pct", Decimal("0.015"))),
        )
        target_net_base_pct = target_abs if side == "buy" else (-target_abs if side == "sell" else _ZERO)
        hedge_target_base_pct = abs(target_net_base_pct) * to_decimal(
            getattr(self.config, "bot7_hedge_ratio", Decimal("0.30"))
        )
        self._bot7_state = {
            "active": side != "off",
            "side": side,
            "reason": reason,
            "bb_lower": bb_lower,
            "bb_basis": bb_basis,
            "bb_upper": bb_upper,
            "rsi": rsi,
            "adx": adx,
            "atr": atr,
            "grid_spacing_pct": spacing_pct,
            "trade_age_ms": trade_age_ms,
            "trade_flow_stale": trade_stale,
            "cvd": cvd,
            "delta_volume": delta_volume,
            "recent_delta": recent_delta,
            "absorption_long": absorption_long,
            "absorption_short": absorption_short,
            "delta_trap_long": delta_trap_long,
            "delta_trap_short": delta_trap_short,
            "signal_score": signal_score,
            "grid_levels": grid_levels,
            "target_net_base_pct": target_net_base_pct,
            "hedge_target_base_pct": hedge_target_base_pct,
            "funding_bias": funding_bias,
            "funding_risk_scale": funding_risk_scale,
            "order_book_imbalance": depth_imbalance,
        }
        return self._bot7_state

    def _resolve_regime_and_targets(self, mid: Decimal) -> Tuple[str, RegimeSpec, Decimal, Decimal, Decimal]:
        regime_name, regime_spec, target_base_pct, target_net_base_pct, band_pct = super()._resolve_regime_and_targets(mid)
        state = self._update_bot7_state(mid=mid, regime_name=regime_name)
        if bool(getattr(self, "_is_perp", False)):
            target_net_base_pct = to_decimal(state.get("target_net_base_pct", _ZERO))
        return regime_name, regime_spec, target_base_pct, target_net_base_pct, band_pct

    def _resolve_quote_side_mode(
        self,
        *,
        mid: Decimal,
        regime_name: str,
        regime_spec: RegimeSpec,
    ) -> str:
        state = getattr(self, "_bot7_state", None) or self._empty_bot7_state()
        side = str(state.get("side", "off"))
        previous_mode = str(getattr(self, "_quote_side_mode", "off") or "off")
        desired_mode = "buy_only" if side == "buy" else ("sell_only" if side == "sell" else "off")
        if previous_mode != desired_mode:
            self._pending_stale_cancel_actions.extend(
                self._cancel_stale_side_executors(previous_mode, desired_mode)
            )
        self._quote_side_mode = desired_mode
        self._quote_side_reason = f"bot7_{state.get('reason', 'inactive')}"
        return desired_mode

    def _compute_levels_and_sizing(
        self,
        regime_name: str,
        regime_spec: RegimeSpec,
        spread_state: SpreadEdgeState,
        equity_quote: Decimal,
        mid: Decimal,
        market: MarketConditions,
    ) -> Tuple[List[Decimal], List[Decimal], Decimal, Decimal]:
        state = self._update_bot7_state(mid=mid, regime_name=regime_name)
        levels = int(state.get("grid_levels", 0) or 0)
        self._runtime_levels.executor_refresh_time = int(regime_spec.refresh_s)
        if not bool(state.get("active")) or levels <= 0:
            return [], [], _ZERO, _ZERO

        spacing_pct = max(
            market.side_spread_floor,
            to_decimal(state.get("grid_spacing_pct", spread_state.spread_pct)),
            Decimal("0.000001"),
        )
        buy_spreads: List[Decimal] = []
        sell_spreads: List[Decimal] = []
        side = str(state.get("side", "off"))
        if side == "buy":
            buy_spreads = [spacing_pct * Decimal(level + 1) for level in range(levels)]
        elif side == "sell":
            sell_spreads = [spacing_pct * Decimal(level + 1) for level in range(levels)]
        size_mult = self._compute_pnl_governor_size_mult(
            equity_quote=equity_quote,
            turnover_x=spread_state.turnover_x,
        ) * to_decimal(state.get("funding_risk_scale", _ONE))
        projected_total_quote = self._project_total_amount_quote(
            equity_quote=equity_quote,
            mid=mid,
            quote_size_pct=regime_spec.quote_size_pct,
            total_levels=max(1, len(buy_spreads) + len(sell_spreads)),
            size_mult=size_mult,
        )
        return buy_spreads, sell_spreads, projected_total_quote, size_mult

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
            _t0=_t0,
            now=now,
            mid=mid,
            regime_name=regime_name,
            target_base_pct=target_base_pct,
            target_net_base_pct=target_net_base_pct,
            base_pct_gross=base_pct_gross,
            base_pct_net=base_pct_net,
            equity_quote=equity_quote,
            spread_state=spread_state,
            market=market,
            risk_hard_stop=risk_hard_stop,
            risk_reasons=risk_reasons,
            daily_loss_pct=daily_loss_pct,
            drawdown_pct=drawdown_pct,
            projected_total_quote=projected_total_quote,
            state=state,
        )
        bot7 = getattr(self, "_bot7_state", None) or self._empty_bot7_state()
        self.processed_data.update(
            {
                "bot7_active": bool(bot7.get("active", False)),
                "bot7_side": str(bot7.get("side", "off")),
                "bot7_reason": str(bot7.get("reason", "inactive")),
                "bot7_cvd": to_decimal(bot7.get("cvd", _ZERO)),
                "bot7_recent_delta": to_decimal(bot7.get("recent_delta", _ZERO)),
                "bot7_trade_age_ms": int(bot7.get("trade_age_ms", 0) or 0),
                "bot7_trade_flow_stale": bool(bot7.get("trade_flow_stale", True)),
                "bot7_rsi": to_decimal(bot7.get("rsi", Decimal("50"))),
                "bot7_adx": to_decimal(bot7.get("adx", _ZERO)),
                "bot7_bb_lower": to_decimal(bot7.get("bb_lower", _ZERO)),
                "bot7_bb_upper": to_decimal(bot7.get("bb_upper", _ZERO)),
                "bot7_grid_spacing_pct": to_decimal(bot7.get("grid_spacing_pct", _ZERO)),
                "bot7_grid_levels": int(bot7.get("grid_levels", 0) or 0),
                "bot7_hedge_target_base_pct": to_decimal(bot7.get("hedge_target_base_pct", _ZERO)),
                "bot7_funding_bias": str(bot7.get("funding_bias", "neutral")),
                "bot7_absorption_long": bool(bot7.get("absorption_long", False)),
                "bot7_absorption_short": bool(bot7.get("absorption_short", False)),
                "bot7_delta_trap_long": bool(bot7.get("delta_trap_long", False)),
                "bot7_delta_trap_short": bool(bot7.get("delta_trap_short", False)),
            }
        )

    def to_format_status(self) -> List[str]:
        lines = super().to_format_status()
        bot7 = getattr(self, "_bot7_state", None) or self._empty_bot7_state()
        lines.append(
            "bot7 "
            f"side={bot7.get('side', 'off')} reason={bot7.get('reason', 'inactive')} "
            f"levels={bot7.get('grid_levels', 0)} spacing={to_decimal(bot7.get('grid_spacing_pct', _ZERO)) * Decimal('100'):.3f}% "
            f"cvd={to_decimal(bot7.get('cvd', _ZERO)):.4f} hedge_target={to_decimal(bot7.get('hedge_target_base_pct', _ZERO)) * Decimal('100'):.3f}%"
        )
        return lines
