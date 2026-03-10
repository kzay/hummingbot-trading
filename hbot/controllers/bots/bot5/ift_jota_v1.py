from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Tuple

from pydantic import Field

from controllers.runtime.data_context import RuntimeDataContext
from controllers.runtime.directional_core import DirectionalRuntimeAdapter
from controllers.runtime.execution_context import RuntimeExecutionPlan
from controllers.runtime.base import StrategyRuntimeV24Config, StrategyRuntimeV24Controller
from controllers.runtime.market_making_types import MarketConditions, RegimeSpec, SpreadEdgeState, clip
from services.common.utils import to_decimal

_ZERO = Decimal("0")
_ONE = Decimal("1")
_NEG_ONE = Decimal("-1")
_10K = Decimal("10000")
_FLOW_EPS = Decimal("0.05")


class Bot5IftJotaV1Config(StrategyRuntimeV24Config):
    """Bot5 IFT/JOTA strategy lane over shared runtime."""

    controller_name: str = "bot5_ift_jota_v1"
    shared_edge_gate_enabled: bool = Field(default=False)
    alpha_policy_enabled: bool = Field(default=False)
    selective_quoting_enabled: bool = Field(default=False)
    adverse_fill_soft_pause_enabled: bool = Field(default=False)
    edge_confidence_soft_pause_enabled: bool = Field(default=False)
    slippage_soft_pause_enabled: bool = Field(default=False)
    bot5_flow_imbalance_threshold: Decimal = Field(
        default=Decimal("0.18"),
        description="Minimum absolute order-book imbalance needed before flow conviction is considered meaningful.",
    )
    bot5_flow_trend_threshold_pct: Decimal = Field(
        default=Decimal("0.0008"),
        description="Minimum signed mid-vs-EMA displacement used by bot5 to validate flow direction.",
    )
    bot5_flow_bias_threshold: Decimal = Field(
        default=Decimal("0.55"),
        description="Conviction threshold above which bot5 may bias its net target while staying within shared risk limits.",
    )
    bot5_flow_directional_threshold: Decimal = Field(
        default=Decimal("0.75"),
        description="Conviction threshold above which bot5 may switch from two-sided MM into one-sided directional quoting.",
    )
    bot5_directional_target_net_base_pct: Decimal = Field(
        default=Decimal("0.08"),
        description="Maximum signed net-base target used by bot5 when flow conviction is directional and aligned.",
    )
    bot5_low_conviction_extra_edge_bps: Decimal = Field(
        default=Decimal("0.60"),
        description="Additional edge floor imposed when flow conviction is weak and bot5 falls back to defensive MM.",
    )
    bot5_directional_market_floor_bps: Decimal = Field(
        default=Decimal("0.25"),
        description="Extra market-floor widening applied during directional scalping mode to avoid chasing thin prints.",
    )


class Bot5IftJotaV1Controller(StrategyRuntimeV24Controller):
    """Bot5-specific IFT/JOTA strategy wrapper over shared runtime controller."""

    def __init__(self, config: Bot5IftJotaV1Config, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self._bot5_flow_state: Dict[str, Any] = self._empty_bot5_flow_state()

    def _make_runtime_family_adapter(self):
        return DirectionalRuntimeAdapter(self)

    def _empty_bot5_flow_state(self) -> Dict[str, Any]:
        return {
            "direction": "off",
            "imbalance": _ZERO,
            "trend_displacement_pct": _ZERO,
            "signed_signal": _ZERO,
            "conviction": _ZERO,
            "bias_active": False,
            "directional_allowed": False,
            "target_net_base_pct": _ZERO,
            "low_conviction": True,
            "reason": "inactive",
        }

    def _bot5_gate_metrics(self) -> Dict[str, Any]:
        flow_state = getattr(self, "_bot5_flow_state", None) or self._empty_bot5_flow_state()
        reason = str(flow_state.get("reason", "inactive"))
        directional_allowed = bool(flow_state.get("directional_allowed", False))
        bias_active = bool(flow_state.get("bias_active", False))
        fail_closed = reason in {"selective_blocked", "fill_edge_below_cost_floor"}
        if fail_closed:
            gate_state = "blocked"
        elif directional_allowed or bias_active:
            gate_state = "active"
        else:
            gate_state = "idle"
        return {
            "state": gate_state,
            "reason": reason,
            "fail_closed": fail_closed,
            "conviction": to_decimal(flow_state.get("conviction", _ZERO)),
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
        gate = self._bot5_gate_metrics()
        conviction = to_decimal(gate["conviction"])
        metrics: Dict[str, Decimal | str | bool] = {
            "state": "bot5_strategy_gate",
            "reason": str(gate["reason"]),
            "maker_score": conviction,
            "aggressive_score": _ZERO,
            "cross_allowed": False,
        }
        self._alpha_policy_state = str(metrics["state"])
        self._alpha_policy_reason = str(metrics["reason"])
        self._alpha_maker_score = conviction
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
        gate = self._bot5_gate_metrics()
        if bool(gate["fail_closed"]):
            gate_reason = f"bot5_{gate['reason']}"
            if gate_reason not in risk_reasons:
                risk_reasons.append(gate_reason)
        return risk_reasons, risk_hard_stop, daily_loss_pct, drawdown_pct

    def _bot5_update_flow_state(self, mid: Decimal, regime_name: str, band_pct: Decimal) -> Dict[str, Any]:
        ema_val = to_decimal(getattr(self, "_regime_ema_value", _ZERO) or _ZERO)
        imbalance = clip(to_decimal(getattr(self, "_ob_imbalance", _ZERO) or _ZERO), _NEG_ONE, _ONE)
        trend_threshold = max(
            Decimal("0.0001"),
            to_decimal(getattr(self.config, "bot5_flow_trend_threshold_pct", Decimal("0.0008"))),
            to_decimal(getattr(self.config, "trend_eps_pct", Decimal("0.0001"))),
        )
        trend_displacement_pct = _ZERO
        if ema_val > _ZERO and mid > _ZERO:
            trend_displacement_pct = (mid - ema_val) / ema_val
        trend_signal = clip(trend_displacement_pct / trend_threshold, _NEG_ONE, _ONE)

        imbalance_threshold = max(
            Decimal("0.05"),
            to_decimal(getattr(self.config, "bot5_flow_imbalance_threshold", Decimal("0.18"))),
        )
        imbalance_strength = clip(abs(imbalance) / imbalance_threshold, _ZERO, _ONE)
        trend_strength = clip(abs(trend_displacement_pct) / trend_threshold, _ZERO, _ONE)
        aligned = (
            abs(imbalance) > _FLOW_EPS
            and abs(trend_signal) > _FLOW_EPS
            and (imbalance > _ZERO) == (trend_signal > _ZERO)
        )
        conviction = clip(
            imbalance_strength * Decimal("0.55")
            + trend_strength * Decimal("0.35")
            + (Decimal("0.10") if aligned else _ZERO),
            _ZERO,
            _ONE,
        )
        signed_signal = clip(
            imbalance * Decimal("0.65") + trend_signal * Decimal("0.35"),
            _NEG_ONE,
            _ONE,
        )

        direction = "off"
        if signed_signal >= _FLOW_EPS:
            direction = "buy"
        elif signed_signal <= -_FLOW_EPS:
            direction = "sell"

        selective_state = str(getattr(self, "_selective_quote_state", "inactive") or "inactive")
        fill_edge_blocked = StrategyRuntimeV24Controller._fill_edge_below_cost_floor(self)
        bias_threshold = clip(
            to_decimal(getattr(self.config, "bot5_flow_bias_threshold", Decimal("0.55"))),
            Decimal("0.25"),
            _ONE,
        )
        directional_threshold = clip(
            to_decimal(getattr(self.config, "bot5_flow_directional_threshold", Decimal("0.75"))),
            bias_threshold,
            _ONE,
        )
        directional_regime = regime_name in {"up", "down", "neutral_low_vol"}
        regime_aligned = not (
            (regime_name == "up" and direction == "sell")
            or (regime_name == "down" and direction == "buy")
        )
        high_vol_locked = regime_name == "high_vol_shock" or band_pct >= to_decimal(self.config.high_vol_band_pct)

        bias_active = (
            direction != "off"
            and conviction >= bias_threshold
            and selective_state != "blocked"
            and not fill_edge_blocked
            and not high_vol_locked
        )
        directional_allowed = (
            bias_active
            and directional_regime
            and regime_aligned
            and conviction >= directional_threshold
        )

        target_net_base_pct = _ZERO
        if bool(getattr(self, "_is_perp", False)) and bias_active:
            target_abs = (
                to_decimal(getattr(self.config, "bot5_directional_target_net_base_pct", Decimal("0.08")))
                * conviction
            )
            target_abs = clip(
                target_abs,
                _ZERO,
                to_decimal(getattr(self.config, "max_base_pct", target_abs)),
            )
            target_net_base_pct = target_abs if direction == "buy" else -target_abs

        if directional_allowed:
            reason = f"directional_{direction}"
        elif bias_active:
            reason = f"biased_{direction}"
        elif high_vol_locked:
            reason = "high_vol_lock"
        elif selective_state == "blocked":
            reason = "selective_blocked"
        elif fill_edge_blocked:
            reason = "fill_edge_below_cost_floor"
        elif direction == "off":
            reason = "no_flow_direction"
        else:
            reason = "weak_flow"

        self._bot5_flow_state = {
            "direction": direction,
            "imbalance": imbalance,
            "trend_displacement_pct": trend_displacement_pct,
            "signed_signal": signed_signal,
            "conviction": conviction,
            "bias_active": bias_active,
            "directional_allowed": directional_allowed,
            "target_net_base_pct": target_net_base_pct,
            "low_conviction": conviction < bias_threshold or direction == "off",
            "reason": reason,
        }
        return self._bot5_flow_state

    def _resolve_regime_and_targets(self, mid: Decimal) -> Tuple[str, RegimeSpec, Decimal, Decimal, Decimal]:
        regime_name, regime_spec, target_base_pct, target_net_base_pct, band_pct = super()._resolve_regime_and_targets(mid)
        flow_state = self._bot5_update_flow_state(mid=mid, regime_name=regime_name, band_pct=band_pct)
        if bool(getattr(self, "_is_perp", False)):
            flow_target = to_decimal(flow_state["target_net_base_pct"])
            if flow_target != _ZERO:
                target_net_base_pct = flow_target
        return regime_name, regime_spec, target_base_pct, target_net_base_pct, band_pct

    def _resolve_quote_side_mode(
        self,
        *,
        mid: Decimal,
        regime_name: str,
        regime_spec: RegimeSpec,
    ) -> str:
        base_mode = regime_spec.one_sided
        flow_state = getattr(self, "_bot5_flow_state", None) or self._empty_bot5_flow_state()
        if not bool(flow_state.get("directional_allowed", False)):
            self._quote_side_mode = base_mode
            self._quote_side_reason = "regime"
            return base_mode

        desired_mode = "buy_only" if str(flow_state.get("direction")) == "buy" else "sell_only"
        previous_mode = str(getattr(self, "_quote_side_mode", base_mode) or "off")
        if previous_mode != desired_mode:
            self._pending_stale_cancel_actions.extend(
                self._cancel_stale_side_executors(previous_mode, desired_mode)
            )
        self._quote_side_mode = desired_mode
        self._quote_side_reason = f"bot5_{flow_state['reason']}"
        return desired_mode

    def _compute_adaptive_spread_knobs(
        self, now_ts: float, equity_quote: Decimal, regime_name: str = "neutral_low_vol"
    ) -> Tuple[Decimal | None, Decimal | None, Decimal | None]:
        effective_min_edge_pct, market_floor_pct, vol_ratio = super()._compute_adaptive_spread_knobs(
            now_ts, equity_quote, regime_name
        )
        if effective_min_edge_pct is None or market_floor_pct is None:
            return effective_min_edge_pct, market_floor_pct, vol_ratio

        flow_state = getattr(self, "_bot5_flow_state", None) or self._empty_bot5_flow_state()
        if bool(flow_state.get("low_conviction", True)) and str(getattr(self, "_selective_quote_state", "inactive")) == "inactive":
            effective_min_edge_pct += (
                to_decimal(getattr(self.config, "bot5_low_conviction_extra_edge_bps", Decimal("0.60"))) / _10K
            )
        if bool(flow_state.get("directional_allowed", False)):
            market_floor_pct += (
                to_decimal(getattr(self.config, "bot5_directional_market_floor_bps", Decimal("0.25"))) / _10K
            )

        effective_min_edge_pct = clip(
            effective_min_edge_pct,
            to_decimal(self.config.adaptive_min_edge_bps_floor) / _10K,
            to_decimal(self.config.adaptive_min_edge_bps_cap) / _10K,
        )
        market_floor_pct = max(_ZERO, market_floor_pct)
        self._adaptive_effective_min_edge_pct = effective_min_edge_pct
        self._adaptive_market_floor_pct = market_floor_pct
        return effective_min_edge_pct, market_floor_pct, vol_ratio

    def _compute_levels_and_sizing(
        self,
        regime_name: str,
        regime_spec: RegimeSpec,
        spread_state: SpreadEdgeState,
        equity_quote: Decimal,
        mid: Decimal,
        market: MarketConditions,
    ) -> Tuple[list[Decimal], list[Decimal], Decimal, Decimal]:
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
        base_plan = super().build_runtime_execution_plan(data_context)
        flow_state = getattr(self, "_bot5_flow_state", None) or self._empty_bot5_flow_state()
        buy_spreads = list(base_plan.buy_spreads)
        sell_spreads = list(base_plan.sell_spreads)
        if bool(flow_state.get("directional_allowed", False)):
            if str(flow_state.get("direction")) == "buy":
                buy_spreads = buy_spreads[:1] or [data_context.market.side_spread_floor]
                sell_spreads = []
            elif str(flow_state.get("direction")) == "sell":
                buy_spreads = []
                sell_spreads = sell_spreads[:1] or [data_context.market.side_spread_floor]
        elif bool(flow_state.get("low_conviction", True)):
            buy_spreads = buy_spreads[:1]
            sell_spreads = sell_spreads[:1]
        active_levels = len(buy_spreads) + len(sell_spreads)
        projected_total_quote = self._project_total_amount_quote(
            equity_quote=data_context.equity_quote,
            mid=data_context.mid,
            quote_size_pct=data_context.regime_spec.quote_size_pct,
            total_levels=active_levels,
            size_mult=base_plan.size_mult,
        )
        return RuntimeExecutionPlan(
            family="directional",
            buy_spreads=buy_spreads,
            sell_spreads=sell_spreads,
            projected_total_quote=projected_total_quote,
            size_mult=base_plan.size_mult,
            metadata={
                **dict(base_plan.metadata),
                "strategy_lane": "bot5",
                "quote_side_mode": str(getattr(self, "_quote_side_mode", "off")),
                "quote_side_reason": str(getattr(self, "_quote_side_reason", "regime")),
                "directional_allowed": bool(flow_state.get("directional_allowed", False)),
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
        flow_state = getattr(self, "_bot5_flow_state", None) or self._empty_bot5_flow_state()
        gate = self._bot5_gate_metrics()
        processed_data["bot5_gate_state"] = gate["state"]
        processed_data["bot5_gate_reason"] = gate["reason"]
        processed_data["bot5_signal_side"] = flow_state["direction"]
        processed_data["bot5_signal_reason"] = flow_state["reason"]
        processed_data["bot5_signal_score"] = flow_state["conviction"]
        processed_data["bot5_flow_direction"] = flow_state["direction"]
        processed_data["bot5_flow_reason"] = flow_state["reason"]
        processed_data["bot5_flow_conviction"] = flow_state["conviction"]
