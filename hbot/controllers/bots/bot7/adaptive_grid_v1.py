from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Tuple

from pydantic import Field

from controllers.runtime.data_context import RuntimeDataContext
from controllers.runtime.directional_core import DirectionalRuntimeAdapter
from controllers.runtime.execution_context import RuntimeExecutionPlan
from controllers.runtime.base import StrategyRuntimeV24Config, StrategyRuntimeV24Controller
from controllers.runtime.market_making_types import MarketConditions, RegimeSpec, SpreadEdgeState, clip
from controllers.runtime.risk_context import RuntimeRiskDecision
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
    shared_edge_gate_enabled: bool = Field(default=False)
    alpha_policy_enabled: bool = Field(default=False)
    selective_quoting_enabled: bool = Field(default=False)
    adverse_fill_soft_pause_enabled: bool = Field(default=False)
    edge_confidence_soft_pause_enabled: bool = Field(default=False)
    slippage_soft_pause_enabled: bool = Field(default=False)
    bot7_bb_period: int = Field(default=20, ge=10, le=100)
    bot7_bb_stddev: Decimal = Field(default=Decimal("2.0"))
    bot7_rsi_period: int = Field(default=14, ge=5, le=50)
    bot7_rsi_buy_threshold: Decimal = Field(default=Decimal("32"))
    bot7_rsi_sell_threshold: Decimal = Field(default=Decimal("68"))
    bot7_rsi_probe_buy_threshold: Decimal = Field(default=Decimal("38"))
    bot7_rsi_probe_sell_threshold: Decimal = Field(default=Decimal("62"))
    bot7_adx_period: int = Field(default=14, ge=5, le=50)
    bot7_adx_activate_below: Decimal = Field(default=Decimal("20"))
    bot7_adx_neutral_fallback_below: Decimal = Field(default=Decimal("28"))
    bot7_trade_window_count: int = Field(default=160, ge=20, le=600)
    bot7_trade_stale_after_ms: int = Field(default=15_000, ge=1000, le=120_000)
    bot7_absorption_min_trade_mult: Decimal = Field(default=Decimal("2.5"))
    bot7_absorption_max_price_drift_pct: Decimal = Field(default=Decimal("0.0015"))
    bot7_delta_trap_window: int = Field(default=24, ge=8, le=120)
    bot7_delta_trap_reversal_share: Decimal = Field(default=Decimal("0.30"))
    bot7_grid_spacing_atr_mult: Decimal = Field(default=Decimal("0.50"))
    bot7_grid_spacing_floor_pct: Decimal = Field(default=Decimal("0.0015"))
    bot7_grid_spacing_cap_pct: Decimal = Field(default=Decimal("0.0100"))
    bot7_touch_tolerance_pct: Decimal = Field(default=Decimal("0.0015"))
    bot7_depth_imbalance_reversal_threshold: Decimal = Field(default=Decimal("0.12"))
    bot7_max_grid_legs: int = Field(default=3, ge=1, le=6)
    bot7_per_leg_risk_pct: Decimal = Field(default=Decimal("0.003"))
    bot7_total_grid_exposure_cap_pct: Decimal = Field(default=Decimal("0.015"))
    bot7_hedge_ratio: Decimal = Field(default=Decimal("0.30"))
    bot7_funding_long_bias_threshold: Decimal = Field(default=Decimal("-0.0003"))
    bot7_funding_short_bias_threshold: Decimal = Field(default=Decimal("0.0003"))
    bot7_funding_vol_reduce_threshold: Decimal = Field(default=Decimal("0.0010"))
    bot7_trade_reader_enabled: bool = Field(default=True)
    bot7_warmup_quote_levels: int = Field(default=1, ge=0, le=2)
    bot7_warmup_quote_max_bars: int = Field(default=3, ge=0, le=20)
    bot7_probe_enabled: bool = Field(default=True)
    bot7_probe_grid_legs: int = Field(default=1, ge=1, le=2)
    bot7_probe_size_mult: Decimal = Field(default=Decimal("0.50"))


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

    def _make_runtime_family_adapter(self):
        return DirectionalRuntimeAdapter(self)

    def _empty_bot7_state(self) -> Dict[str, Any]:
        return {
            "active": False,
            "probe_mode": False,
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
            "indicator_ready": False,
            "indicator_missing": "",
            "price_buffer_bars": 0,
        }

    def _bot7_gate_metrics(self) -> Dict[str, Any]:
        state = getattr(self, "_bot7_state", None) or self._empty_bot7_state()
        reason = str(state.get("reason", "inactive"))
        fail_closed = False
        if bool(state.get("active", False)):
            gate_state = "active"
            gate_reason = reason
        else:
            gate_state = "idle"
            gate_reason = reason
        return {
            "state": gate_state,
            "reason": gate_reason,
            "fail_closed": fail_closed,
        }

    def _compute_alpha_policy(
        self,
        *,
        regime_name: str,
        spread_state: SpreadEdgeState,
        market: MarketConditions,
        target_net_base_pct: Decimal,
        base_pct_net: Decimal,
    ) -> Dict[str, Decimal | str | bool]:
        gate = self._bot7_gate_metrics()
        signal_score = to_decimal((getattr(self, "_bot7_state", None) or {}).get("signal_score", _ZERO))
        metrics: Dict[str, Decimal | str | bool] = {
            "state": "bot7_strategy_gate",
            "reason": str(gate["reason"]),
            "maker_score": signal_score,
            "aggressive_score": _ZERO,
            "cross_allowed": False,
        }
        self._alpha_policy_state = str(metrics["state"])
        self._alpha_policy_reason = str(metrics["reason"])
        self._alpha_maker_score = signal_score
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
    ) -> Tuple[List[str], bool, Decimal, Decimal]:
        risk_reasons, risk_hard_stop, daily_loss_pct, drawdown_pct = super()._evaluate_all_risk(
            spread_state=spread_state,
            base_pct_gross=base_pct_gross,
            equity_quote=equity_quote,
            projected_total_quote=projected_total_quote,
            market=market,
        )
        gate = self._bot7_gate_metrics()
        if bool(gate["fail_closed"]):
            gate_reason = f"bot7_{gate['reason']}"
            if gate_reason not in risk_reasons:
                risk_reasons.append(gate_reason)
        return risk_reasons, risk_hard_stop, daily_loss_pct, drawdown_pct

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
        price_buffer = getattr(self, "_price_buffer", None)
        bar_count = len(getattr(price_buffer, "bars", []) or [])

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

        if mid <= _ZERO:
            self._bot7_state = self._empty_bot7_state()
            self._bot7_state.update(
                {
                    "reason": "indicator_warmup",
                    "trade_age_ms": trade_age_ms,
                    "trade_flow_stale": trade_stale,
                    "funding_bias": funding_bias,
                    "funding_risk_scale": funding_risk_scale,
                    "order_book_imbalance": depth_imbalance,
                    "indicator_ready": False,
                    "indicator_missing": "mid",
                    "price_buffer_bars": bar_count,
                }
            )
            return self._bot7_state

        indicator_missing: List[str] = []
        if bands is None:
            indicator_missing.append("bands")
        if rsi is None:
            indicator_missing.append("rsi")
        if adx is None:
            indicator_missing.append("adx")
        indicator_ready = len(indicator_missing) == 0
        atr_ready = atr is not None

        if not indicator_ready:
            self._bot7_state = self._empty_bot7_state()
            self._bot7_state.update(
                {
                    "reason": "indicator_warmup",
                    "trade_age_ms": trade_age_ms,
                    "trade_flow_stale": trade_stale,
                    "funding_bias": funding_bias,
                    "funding_risk_scale": funding_risk_scale,
                    "order_book_imbalance": depth_imbalance,
                    "indicator_ready": False,
                    "indicator_missing": ",".join(indicator_missing),
                    "price_buffer_bars": bar_count,
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
        neutral_regime = str(regime_name).startswith("neutral")
        regime_active = (
            adx_active
            or (neutral_regime and adx <= to_decimal(getattr(self.config, "bot7_adx_neutral_fallback_below", Decimal("28"))))
            or funding_bias != "neutral"
        )
        touch_eps = to_decimal(getattr(self.config, "bot7_touch_tolerance_pct", Decimal("0.0015")))
        touch_lower = mid <= bb_lower * (_ONE + touch_eps)
        touch_upper = mid >= bb_upper * (_ONE - touch_eps)
        rsi_buy_threshold = to_decimal(getattr(self.config, "bot7_rsi_buy_threshold", Decimal("32")))
        rsi_sell_threshold = to_decimal(getattr(self.config, "bot7_rsi_sell_threshold", Decimal("68")))
        rsi_probe_buy_threshold = max(
            rsi_buy_threshold,
            to_decimal(getattr(self.config, "bot7_rsi_probe_buy_threshold", Decimal("38"))),
        )
        rsi_probe_sell_threshold = min(
            rsi_sell_threshold,
            to_decimal(getattr(self.config, "bot7_rsi_probe_sell_threshold", Decimal("62"))),
        )
        imbalance_threshold = to_decimal(
            getattr(self.config, "bot7_depth_imbalance_reversal_threshold", Decimal("0.12"))
        )
        primary_long = absorption_long or delta_trap_long
        primary_short = absorption_short or delta_trap_short
        secondary_long = depth_imbalance >= imbalance_threshold and recent_delta >= _ZERO
        secondary_short = depth_imbalance <= -imbalance_threshold and recent_delta <= _ZERO
        long_signal = regime_active and not trade_stale and touch_lower and rsi <= rsi_buy_threshold and primary_long
        short_signal = regime_active and not trade_stale and touch_upper and rsi >= rsi_sell_threshold and primary_short
        probe_enabled = bool(getattr(self.config, "bot7_probe_enabled", True))
        long_probe = (
            probe_enabled
            and regime_active
            and not trade_stale
            and touch_lower
            and rsi <= rsi_probe_buy_threshold
            and (primary_long or secondary_long)
        )
        short_probe = (
            probe_enabled
            and regime_active
            and not trade_stale
            and touch_upper
            and rsi >= rsi_probe_sell_threshold
            and (primary_short or secondary_short)
        )

        side = "off"
        probe_mode = False
        reason = "no_entry"
        if long_signal and not short_signal:
            side = "buy"
            reason = "mean_reversion_long"
        elif short_signal and not long_signal:
            side = "sell"
            reason = "mean_reversion_short"
        elif long_probe and not short_probe:
            side = "buy"
            reason = "probe_long"
            probe_mode = True
        elif short_probe and not long_probe:
            side = "sell"
            reason = "probe_short"
            probe_mode = True
        elif trade_stale:
            reason = "trade_flow_stale"
        elif not regime_active:
            reason = "regime_inactive"

        if side == "buy":
            signal_components = sum(1 for flag in (primary_long, secondary_long, regime_active) if flag)
        elif side == "sell":
            signal_components = sum(1 for flag in (primary_short, secondary_short, regime_active) if flag)
        else:
            signal_components = int(regime_active)
        signal_score = clip(Decimal(signal_components) / _THREE, _ZERO, _ONE)
        spacing_pct = clip(
            (atr * to_decimal(getattr(self.config, "bot7_grid_spacing_atr_mult", Decimal("0.50"))) / mid)
            if atr is not None and mid > _ZERO
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
            if probe_mode:
                grid_levels = min(
                    grid_levels,
                    max(1, int(getattr(self.config, "bot7_probe_grid_legs", 1))),
                )
        per_leg_risk = to_decimal(getattr(self.config, "bot7_per_leg_risk_pct", Decimal("0.003")))
        target_abs = clip(
            per_leg_risk * Decimal(grid_levels) * funding_risk_scale,
            _ZERO,
            to_decimal(getattr(self.config, "bot7_total_grid_exposure_cap_pct", Decimal("0.015"))),
        )
        if probe_mode:
            target_abs *= clip(to_decimal(getattr(self.config, "bot7_probe_size_mult", Decimal("0.50"))), _ZERO, _ONE)
        target_net_base_pct = target_abs if side == "buy" else (-target_abs if side == "sell" else _ZERO)
        hedge_target_base_pct = abs(target_net_base_pct) * to_decimal(
            getattr(self.config, "bot7_hedge_ratio", Decimal("0.30"))
        )
        self._bot7_state = {
            "active": side != "off",
            "probe_mode": probe_mode,
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
            "indicator_ready": True,
            "indicator_missing": "" if atr_ready else "atr",
            "price_buffer_bars": bar_count,
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
        reason = str(state.get("reason", "inactive"))
        warmup_quote_max_bars = max(0, int(getattr(self.config, "bot7_warmup_quote_max_bars", 3)))
        warmup_price_buffer_bars = int(state.get("price_buffer_bars", 0) or 0)
        previous_mode = str(getattr(self, "_quote_side_mode", "off") or "off")
        desired_mode = "buy_only" if side == "buy" else ("sell_only" if side == "sell" else "off")
        if previous_mode != desired_mode:
            self._pending_stale_cancel_actions.extend(
                self._cancel_stale_side_executors(previous_mode, desired_mode)
            )
        cancel_active_when_off = reason in {"trade_flow_stale", "regime_inactive", "no_entry"} or (
            reason == "indicator_warmup" and warmup_price_buffer_bars > warmup_quote_max_bars
        )
        if desired_mode == "off" and cancel_active_when_off:
            self._pending_stale_cancel_actions.extend(self._cancel_active_quote_executors())
            cancel_paper_orders = getattr(self, "_cancel_alpha_no_trade_paper_orders", None)
            if callable(cancel_paper_orders):
                cancel_paper_orders()
        self._quote_side_mode = desired_mode
        self._quote_side_reason = f"bot7_{reason}"
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
        state = getattr(self, "_bot7_state", None) or self._update_bot7_state(
            mid=data_context.mid,
            regime_name=data_context.regime_name,
        )
        levels = int(state.get("grid_levels", 0) or 0)
        self._runtime_levels.executor_refresh_time = int(data_context.regime_spec.refresh_s)
        self._resolve_quote_side_mode(
            mid=data_context.mid,
            regime_name=data_context.regime_name,
            regime_spec=data_context.regime_spec,
        )
        if not bool(state.get("active")) or levels <= 0:
            warmup_levels = max(0, int(getattr(self.config, "bot7_warmup_quote_levels", 1)))
            warmup_quote_max_bars = max(0, int(getattr(self.config, "bot7_warmup_quote_max_bars", 3)))
            warmup_price_buffer_bars = int(state.get("price_buffer_bars", 0) or 0)
            if warmup_levels <= 0:
                return RuntimeExecutionPlan(
                    family="directional",
                    buy_spreads=[],
                    sell_spreads=[],
                    projected_total_quote=_ZERO,
                    size_mult=_ZERO,
                    metadata={"strategy_lane": "bot7", "quote_side_mode": self._quote_side_mode},
                )
            warmup_reason = str(state.get("reason", "inactive"))
            if warmup_reason != "indicator_warmup" or warmup_price_buffer_bars > warmup_quote_max_bars:
                return RuntimeExecutionPlan(
                    family="directional",
                    buy_spreads=[],
                    sell_spreads=[],
                    projected_total_quote=_ZERO,
                    size_mult=_ZERO,
                    metadata={"strategy_lane": "bot7", "quote_side_mode": self._quote_side_mode},
                )
            spacing_pct = max(
                data_context.market.side_spread_floor,
                to_decimal(getattr(self.config, "bot7_grid_spacing_floor_pct", Decimal("0.0015"))),
                Decimal("0.000001"),
            )
            buy_spreads = [spacing_pct * Decimal(level + 1) for level in range(warmup_levels)]
            sell_spreads = [spacing_pct * Decimal(level + 1) for level in range(warmup_levels)]
            size_mult = self._compute_pnl_governor_size_mult(
                equity_quote=data_context.equity_quote,
                turnover_x=data_context.spread_state.turnover_x,
            ) * to_decimal(state.get("funding_risk_scale", _ONE))
            projected_total_quote = self._project_total_amount_quote(
                equity_quote=data_context.equity_quote,
                mid=data_context.mid,
                quote_size_pct=data_context.regime_spec.quote_size_pct,
                total_levels=len(buy_spreads) + len(sell_spreads),
                size_mult=size_mult,
            )
            return RuntimeExecutionPlan(
                family="directional",
                buy_spreads=buy_spreads,
                sell_spreads=sell_spreads,
                projected_total_quote=projected_total_quote,
                size_mult=size_mult,
                metadata={
                    "strategy_lane": "bot7",
                    "quote_side_mode": self._quote_side_mode,
                    "quote_side_reason": self._quote_side_reason,
                    "grid_levels": warmup_levels,
                    "warmup_quote_excluded_from_viability": True,
                },
            )

        spacing_pct = max(
            data_context.market.side_spread_floor,
            to_decimal(state.get("grid_spacing_pct", data_context.spread_state.spread_pct)),
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
            equity_quote=data_context.equity_quote,
            turnover_x=data_context.spread_state.turnover_x,
        ) * to_decimal(state.get("funding_risk_scale", _ONE))
        projected_total_quote = self._project_total_amount_quote(
            equity_quote=data_context.equity_quote,
            mid=data_context.mid,
            quote_size_pct=data_context.regime_spec.quote_size_pct,
            total_levels=len(buy_spreads) + len(sell_spreads),
            size_mult=size_mult,
        )
        return RuntimeExecutionPlan(
            family="directional",
            buy_spreads=buy_spreads,
            sell_spreads=sell_spreads,
            projected_total_quote=projected_total_quote,
            size_mult=size_mult,
            metadata={
                "strategy_lane": "bot7",
                "quote_side_mode": self._quote_side_mode,
                "quote_side_reason": self._quote_side_reason,
                "grid_levels": levels,
            },
        )

    def _extend_processed_data_before_log(
        self,
        *,
        processed_data: Dict[str, Any],
        snapshot: Dict[str, Any],
        state: Any,
        regime_name: str,
        market: MarketConditions,
        projected_total_quote: Decimal,
    ) -> None:
        bot7 = getattr(self, "_bot7_state", None) or self._empty_bot7_state()
        gate = self._bot7_gate_metrics()
        processed_data.update(
            {
                "bot7_gate_state": str(gate["state"]),
                "bot7_gate_reason": str(gate["reason"]),
                "bot7_active": bool(bot7.get("active", False)),
                "bot7_probe_mode": bool(bot7.get("probe_mode", False)),
                "bot7_signal_side": str(bot7.get("side", "off")),
                "bot7_signal_reason": str(bot7.get("reason", "inactive")),
                "bot7_signal_score": to_decimal(bot7.get("signal_score", _ZERO)),
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
                "bot7_indicator_ready": bool(bot7.get("indicator_ready", False)),
                "bot7_indicator_missing": str(bot7.get("indicator_missing", "")),
                "bot7_price_buffer_bars": int(bot7.get("price_buffer_bars", 0) or 0),
            }
        )

    def extend_runtime_processed_data(
        self,
        *,
        processed_data: Dict[str, Any],
        data_context: RuntimeDataContext,
        risk_decision: RuntimeRiskDecision,
        execution_plan: RuntimeExecutionPlan,
        snapshot: Dict[str, Any],
    ) -> None:
        self._extend_processed_data_before_log(
            processed_data=processed_data,
            snapshot=snapshot,
            state=risk_decision.guard_state,
            regime_name=data_context.regime_name,
            market=data_context.market,
            projected_total_quote=execution_plan.projected_total_quote,
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
        if not bool(bot7.get("indicator_ready", False)):
            lines.append(
                "bot7 "
                f"warmup_missing={bot7.get('indicator_missing', '') or 'unknown'} "
                f"price_buffer_bars={int(bot7.get('price_buffer_bars', 0) or 0)}"
            )
        return lines
