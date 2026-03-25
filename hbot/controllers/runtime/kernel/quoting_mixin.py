from __future__ import annotations

import logging
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from typing import Any

from hummingbot.core.data_type.common import TradeType

from controllers.runtime.contracts import RuntimeFamilyAdapter
from controllers.runtime.kernel.config import (
    _ZERO, _ONE, _TWO, _10K, _MIN_SPREAD, _MIN_SKEW_CAP, _FILL_FACTOR_LO,
    _runtime_family_adapter,
    _clip,
)
from controllers.runtime.data_context import RuntimeDataContext
from controllers.runtime.execution_context import RuntimeExecutionPlan
from controllers.runtime.market_making_core import MarketMakingRuntimeAdapter
from controllers.runtime.risk_context import RuntimeRiskDecision
from controllers.runtime.runtime_types import MarketConditions, RegimeSpec, SpreadEdgeState
from controllers.tick_types import TickSnapshot
from controllers.types import ProcessedState
from controllers.ops_guard import GuardState
from platform_lib.core.utils import to_decimal

logger = logging.getLogger(__name__)


class QuotingMixin:

    # ------------------------------------------------------------------
    # Levels & sizing
    # ------------------------------------------------------------------

    def _compute_levels_and_sizing(
        self, regime_name: str, regime_spec: RegimeSpec, spread_state: SpreadEdgeState,
        equity_quote: Decimal, mid: Decimal, market: MarketConditions,
    ) -> tuple[list[Decimal], list[Decimal], Decimal, Decimal]:
        """Compatibility wrapper over the neutral runtime execution-plan hook."""
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
                target_net_base_pct=regime_spec.target_base_pct,
                base_pct_gross=to_decimal(self.processed_data.get("base_pct", _ZERO)) if isinstance(self.processed_data, dict) else _ZERO,
                base_pct_net=to_decimal(self.processed_data.get("net_base_pct", _ZERO)) if isinstance(self.processed_data, dict) else _ZERO,
            )
        )
        return plan.buy_spreads, plan.sell_spreads, plan.projected_total_quote, plan.size_mult

    def build_runtime_execution_plan(self, data_context: RuntimeDataContext) -> RuntimeExecutionPlan:
        """Neutral lane hook that resolves into the active execution-family adapter."""
        return _runtime_family_adapter(self).build_execution_plan(data_context)

    def _apply_runtime_execution_plan(self, data_context: RuntimeDataContext, execution_plan: RuntimeExecutionPlan) -> None:
        _runtime_family_adapter(self).apply_execution_plan(
            execution_plan,
            equity_quote=data_context.equity_quote,
            mid=data_context.mid,
            quote_size_pct=data_context.regime_spec.quote_size_pct,
        )

    def _make_runtime_family_adapter(self) -> RuntimeFamilyAdapter:
        return MarketMakingRuntimeAdapter(self)

    # ------------------------------------------------------------------
    # Quote-side mode resolution
    # ------------------------------------------------------------------

    def _resolve_quote_side_mode(
        self,
        *,
        mid: Decimal,
        regime_name: str,
        regime_spec: RegimeSpec,
    ) -> str:
        """Resolve effective quote side mode, including neutral pre-trend filtering."""
        one_sided = regime_spec.one_sided
        reason = "regime"
        alpha_state = str(getattr(self, "_alpha_policy_state", "maker_two_sided"))
        if alpha_state == "no_trade":
            one_sided = "off"
            reason = "alpha_no_trade"
        elif alpha_state in {"maker_bias_buy", "aggressive_buy"}:
            one_sided = "buy_only"
            reason = "alpha_buy_bias"
        elif alpha_state in {"maker_bias_sell", "aggressive_sell"}:
            one_sided = "sell_only"
            reason = "alpha_sell_bias"

        neutral_guard_pct = max(_ZERO, to_decimal(getattr(self.config, "neutral_trend_guard_pct", _ZERO)))
        ema_val = getattr(self, "_regime_ema_value", None)
        ema_val = None if ema_val is None else to_decimal(ema_val)

        if (
            regime_name == "neutral_low_vol"
            and one_sided == "off"
            and alpha_state not in {"no_trade", "maker_bias_buy", "maker_bias_sell", "aggressive_buy", "aggressive_sell"}
            and neutral_guard_pct > _ZERO
            and ema_val is not None
            and ema_val > _ZERO
            and mid > _ZERO
        ):
            displacement_pct = (mid - ema_val) / ema_val
            if displacement_pct >= neutral_guard_pct:
                one_sided = "buy_only"
                reason = "neutral_trend_guard_up"
            elif displacement_pct <= -neutral_guard_pct:
                one_sided = "sell_only"
                reason = "neutral_trend_guard_down"
        if (
            regime_name == "neutral_low_vol"
            and one_sided == "off"
            and alpha_state not in {"no_trade", "maker_bias_buy", "maker_bias_sell", "aggressive_buy", "aggressive_sell"}
            and str(getattr(self, "_selective_quote_state", "inactive")) == "reduced"
            and ema_val is not None
            and ema_val > _ZERO
            and mid > _ZERO
        ):
            selective_bias_pct = max(
                neutral_guard_pct,
                to_decimal(getattr(self.config, "selective_side_bias_pct", neutral_guard_pct)),
            )
            displacement_pct = (mid - ema_val) / ema_val
            if displacement_pct >= selective_bias_pct:
                one_sided = "buy_only"
                reason = "selective_with_trend_up"
            elif displacement_pct <= -selective_bias_pct:
                one_sided = "sell_only"
                reason = "selective_with_trend_down"

        previous_mode = str(getattr(self, "_quote_side_mode", "off") or "off")
        if previous_mode != one_sided:
            self.enqueue_stale_cancels(
                self._cancel_stale_side_executors(previous_mode, one_sided)
            )
        if alpha_state == "no_trade":
            self.enqueue_stale_cancels(
                self._cancel_active_quote_executors()
            )
            self._cancel_alpha_no_trade_orders()
        else:
            requested_ids = getattr(self, "_alpha_no_trade_cancel_requested_ids", None)
            if isinstance(requested_ids, set):
                requested_ids.clear()
            self._alpha_no_trade_last_paper_cancel_ts = 0.0
        self._quote_side_mode = one_sided
        self._quote_side_reason = reason
        return one_sided

    # ------------------------------------------------------------------
    # Spread competitiveness cap
    # ------------------------------------------------------------------

    def _apply_spread_competitiveness_cap(
        self,
        buy_spreads: list[Decimal],
        sell_spreads: list[Decimal],
        market: MarketConditions,
    ) -> tuple[list[Decimal], list[Decimal]]:
        cap_mult = max(_ZERO, to_decimal(self.config.max_quote_to_market_spread_mult))
        market_spread = max(_ZERO, to_decimal(market.market_spread_pct))
        if cap_mult <= _ZERO or market_spread <= _ZERO:
            self._spread_competitiveness_cap_active = False
            self._spread_competitiveness_cap_side_pct = _ZERO
            return buy_spreads, sell_spreads
        cap_side = max(to_decimal(market.side_spread_floor), (market_spread * cap_mult) / _TWO)
        buy = [min(max(to_decimal(v), to_decimal(market.side_spread_floor)), cap_side) for v in buy_spreads]
        sell = [min(max(to_decimal(v), to_decimal(market.side_spread_floor)), cap_side) for v in sell_spreads]
        self._spread_competitiveness_cap_side_pct = cap_side
        self._spread_competitiveness_cap_active = (buy != buy_spreads) or (sell != sell_spreads)
        return buy, sell

    # ------------------------------------------------------------------
    # Selective quote quality
    # ------------------------------------------------------------------

    def _compute_selective_quote_quality(self, regime_name: str) -> dict[str, Decimal | str]:
        if not bool(getattr(self.config, "selective_quoting_enabled", False)):
            metrics: dict[str, Decimal | str] = {
                "score": _ZERO,
                "state": "inactive",
                "reason": "disabled",
                "adverse_ratio": _ZERO,
                "slippage_p95_bps": _ZERO,
            }
        else:
            min_fills = max(1, int(getattr(self.config, "selective_quality_min_fills", 40)))
            fill_count = max(0, int(getattr(self, "_fill_count_for_kelly", 0)))
            if fill_count < min_fills:
                metrics = {
                    "score": _ZERO,
                    "state": "inactive",
                    "reason": "insufficient_history",
                    "adverse_ratio": _ZERO,
                    "slippage_p95_bps": _ZERO,
                }
            else:
                cost_floor_bps = (
                    max(_ZERO, to_decimal(getattr(self, "_maker_fee_pct", _ZERO)))
                    + max(_ZERO, to_decimal(getattr(self.config, "slippage_est_pct", _ZERO)))
                ) * _10K
                fill_edge_ewma = getattr(self, "_fill_edge_ewma", None)
                fill_edge_ewma = None if fill_edge_ewma is None else to_decimal(fill_edge_ewma)
                negative_edge_ratio = _ZERO
                if (
                    fill_edge_ewma is not None
                    and cost_floor_bps > _ZERO
                    and fill_edge_ewma < -cost_floor_bps
                ):
                    negative_edge_ratio = _clip(
                        ((-fill_edge_ewma) - cost_floor_bps) / cost_floor_bps,
                        _ZERO,
                        _ONE,
                    )

                adverse_threshold = max(1, int(getattr(self.config, "adverse_fill_count_threshold", 20)))
                adverse_ratio = _clip(
                    Decimal(int(getattr(self, "_adverse_fill_count", 0))) / Decimal(adverse_threshold),
                    _ZERO,
                    _ONE,
                )
                slippage_p95_bps = self._recent_positive_slippage_p95_bps(
                    min_fills=min_fills,
                )
                slippage_trigger_bps = max(
                    Decimal("0.1"),
                    to_decimal(getattr(self.config, "slippage_soft_pause_p95_bps", Decimal("25"))),
                )
                slippage_ratio = _clip(slippage_p95_bps / slippage_trigger_bps, _ZERO, _ONE)

                score = (
                    negative_edge_ratio * Decimal("0.50")
                    + adverse_ratio * Decimal("0.25")
                    + slippage_ratio * Decimal("0.25")
                )
                if regime_name == "neutral_low_vol" and fill_edge_ewma is not None and fill_edge_ewma < _ZERO:
                    score += Decimal("0.10")
                score = _clip(score, _ZERO, _ONE)

                reduce_threshold = _clip(
                    to_decimal(getattr(self.config, "selective_quality_reduce_threshold", Decimal("0.45"))),
                    _ZERO,
                    _ONE,
                )
                block_threshold = _clip(
                    to_decimal(getattr(self.config, "selective_quality_block_threshold", Decimal("0.85"))),
                    reduce_threshold,
                    _ONE,
                )
                state = "inactive"
                if score >= block_threshold:
                    state = "blocked"
                elif score >= reduce_threshold:
                    state = "reduced"

                reason = "healthy"
                if state != "inactive":
                    if slippage_ratio >= max(negative_edge_ratio, adverse_ratio) and slippage_ratio > _ZERO:
                        reason = "slippage_shock"
                    elif negative_edge_ratio >= adverse_ratio and negative_edge_ratio > _ZERO:
                        reason = "negative_fill_edge"
                    elif adverse_ratio > _ZERO:
                        reason = "adverse_fill_streak"
                    elif regime_name == "neutral_low_vol":
                        reason = "neutral_low_vol_filter"

                metrics = {
                    "score": score,
                    "state": state,
                    "reason": reason,
                    "adverse_ratio": adverse_ratio,
                    "slippage_p95_bps": slippage_p95_bps,
                }

        self._selective_quote_score = to_decimal(metrics["score"])
        self._selective_quote_state = str(metrics["state"])
        self._selective_quote_reason = str(metrics["reason"])
        self._selective_quote_adverse_ratio = to_decimal(metrics["adverse_ratio"])
        self._selective_quote_slippage_p95_bps = to_decimal(metrics["slippage_p95_bps"])
        return metrics

    # ------------------------------------------------------------------
    # Alpha policy
    # ------------------------------------------------------------------

    def _compute_alpha_policy(
        self,
        *,
        regime_name: str,
        spread_state: SpreadEdgeState,
        market: MarketConditions,
        target_net_base_pct: Decimal,
        base_pct_net: Decimal,
    ) -> dict[str, Decimal | str | bool]:
        if not bool(getattr(self.config, "alpha_policy_enabled", True)):
            metrics: dict[str, Decimal | str | bool] = {
                "state": "maker_two_sided",
                "reason": "disabled",
                "maker_score": _ONE,
                "aggressive_score": _ZERO,
                "cross_allowed": False,
            }
            self._inventory_urgency_score = _ZERO
        else:
            scores = self._compute_alpha_scores(
                spread_state=spread_state,
                target_net_base_pct=target_net_base_pct,
                base_pct_net=base_pct_net,
            )
            metrics = self._resolve_alpha_state(
                regime_name=regime_name,
                spread_state=spread_state,
                market=market,
                scores=scores,
            )

        self._alpha_policy_state = str(metrics["state"])
        self._alpha_policy_reason = str(metrics["reason"])
        self._alpha_maker_score = to_decimal(metrics["maker_score"])
        self._alpha_aggressive_score = to_decimal(metrics["aggressive_score"])
        self._alpha_cross_allowed = bool(metrics["cross_allowed"])
        return metrics

    def _compute_alpha_scores(
        self,
        *,
        spread_state: SpreadEdgeState,
        target_net_base_pct: Decimal,
        base_pct_net: Decimal,
    ) -> dict:
        """Compute inventory urgency, maker score, aggressive score and sub-signals."""
        inv_error = target_net_base_pct - base_pct_net
        max_base = max(
            Decimal("0.05"),
            to_decimal(getattr(self.config, "max_base_pct", Decimal("0.45"))),
        )
        inventory_urgency = _clip(abs(inv_error) / max_base, _ZERO, _ONE)
        self._inventory_urgency_score = inventory_urgency

        edge_buffer = max(_ZERO, spread_state.net_edge - spread_state.min_edge_threshold)
        edge_buffer_score = _clip(
            edge_buffer / max(Decimal("0.0001"), spread_state.min_edge_threshold),
            _ZERO,
            _ONE,
        )
        drift_penalty = _clip(
            max(_ZERO, spread_state.adverse_drift - spread_state.smooth_drift) * Decimal("4000"),
            _ZERO,
            _ONE,
        )
        market_health = _ONE - drift_penalty
        imbalance_abs = _clip(abs(getattr(self, "_ob_imbalance", _ZERO)), _ZERO, _ONE)
        imbalance_alignment = _ZERO
        if inv_error > _ZERO:
            imbalance_alignment = _clip(max(_ZERO, to_decimal(getattr(self, "_ob_imbalance", _ZERO))), _ZERO, _ONE)
        elif inv_error < _ZERO:
            imbalance_alignment = _clip(max(_ZERO, -to_decimal(getattr(self, "_ob_imbalance", _ZERO))), _ZERO, _ONE)

        selective_penalty = _clip(to_decimal(getattr(self, "_selective_quote_score", _ZERO)), _ZERO, _ONE)
        maker_score = _clip(
            edge_buffer_score * Decimal("0.45")
            + market_health * Decimal("0.25")
            + imbalance_abs * Decimal("0.10")
            + imbalance_alignment * Decimal("0.10")
            + inventory_urgency * Decimal("0.10")
            - selective_penalty * Decimal("0.25"),
            _ZERO,
            _ONE,
        )
        aggressive_score = _clip(
            maker_score * Decimal("0.55")
            + imbalance_alignment * Decimal("0.20")
            + inventory_urgency * Decimal("0.25"),
            _ZERO,
            _ONE,
        )
        return {
            "inv_error": inv_error,
            "inventory_urgency": inventory_urgency,
            "maker_score": maker_score,
            "aggressive_score": aggressive_score,
            "imbalance_alignment": imbalance_alignment,
        }

    def _resolve_alpha_state(
        self,
        *,
        regime_name: str,
        spread_state: SpreadEdgeState,
        market: MarketConditions,
        scores: dict,
    ) -> dict[str, Decimal | str | bool]:
        """Determine final alpha policy state based on scores, thresholds, and market."""
        inv_error = scores["inv_error"]
        inventory_urgency = scores["inventory_urgency"]
        maker_score = scores["maker_score"]
        aggressive_score = scores["aggressive_score"]
        imbalance_alignment = scores["imbalance_alignment"]

        state = "maker_two_sided"
        reason = "maker_baseline"
        cross_allowed = False
        urgency_threshold = _clip(
            to_decimal(getattr(self.config, "alpha_policy_inventory_relief_threshold", Decimal("0.55"))),
            _ZERO, _ONE,
        )
        no_trade_threshold = _clip(
            to_decimal(getattr(self.config, "alpha_policy_no_trade_threshold", Decimal("0.35"))),
            _ZERO, _ONE,
        )
        aggressive_threshold = _clip(
            to_decimal(getattr(self.config, "alpha_policy_aggressive_threshold", Decimal("0.78"))),
            no_trade_threshold, _ONE,
        )
        bias_state = ""
        if inv_error > _ZERO and inventory_urgency >= urgency_threshold:
            bias_state = "buy"
        elif inv_error < _ZERO and inventory_urgency >= urgency_threshold:
            bias_state = "sell"
        else:
            imbalance = to_decimal(getattr(self, "_ob_imbalance", _ZERO))
            if imbalance >= Decimal("0.25"):
                bias_state = "buy"
            elif imbalance <= Decimal("-0.25"):
                bias_state = "sell"

        if market.order_book_stale:
            state = "no_trade"
            reason = "order_book_stale"
        elif market.market_spread_too_small:
            state = "no_trade"
            reason = "market_spread_too_small"
        elif (
            regime_name == "neutral_low_vol"
            and maker_score < no_trade_threshold
            and spread_state.net_edge < spread_state.edge_resume_threshold
        ):
            state = "no_trade"
            reason = "neutral_low_edge"
        elif aggressive_score >= aggressive_threshold and bias_state:
            state = f"aggressive_{bias_state}"
            reason = "inventory_relief" if inventory_urgency >= urgency_threshold else "imbalance_alignment"
            cross_allowed = True
        elif bias_state:
            state = f"maker_bias_{bias_state}"
            reason = "inventory_relief" if inventory_urgency >= urgency_threshold else "imbalance_alignment"

        return {
            "state": state,
            "reason": reason,
            "maker_score": maker_score,
            "aggressive_score": aggressive_score,
            "cross_allowed": cross_allowed,
        }

    # ------------------------------------------------------------------
    # Processed-data extension hooks
    # ------------------------------------------------------------------

    def _extend_processed_data_before_log(
        self,
        *,
        processed_data: ProcessedState,
        snapshot: dict[str, Any],
        state: GuardState,
        regime_name: str,
        market: MarketConditions,
        projected_total_quote: Decimal,
    ) -> None:
        """Subclass hook for injecting extra processed-data fields before minute logging."""
        return None

    def extend_runtime_processed_data(
        self,
        *,
        processed_data: ProcessedState,
        data_context: RuntimeDataContext,
        risk_decision: RuntimeRiskDecision,
        execution_plan: RuntimeExecutionPlan,
        snapshot: TickSnapshot,
    ) -> None:
        """Neutral runtime hook that preserves the legacy processed-data extension point."""
        self._extend_processed_data_before_log(
            processed_data=processed_data,
            snapshot=snapshot,
            state=risk_decision.guard_state,
            regime_name=data_context.regime_name,
            market=data_context.market,
            projected_total_quote=execution_plan.projected_total_quote,
        )

    # ------------------------------------------------------------------
    # Executor config / price+amount
    # ------------------------------------------------------------------

    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal) -> Any:
        return _runtime_family_adapter(self).get_executor_config(level_id, price, amount)

    def get_price_and_amount(self, level_id: str) -> tuple[Decimal, Decimal]:
        return _runtime_family_adapter(self).get_price_and_amount(level_id)

    # ------------------------------------------------------------------
    # Kelly sizing
    # ------------------------------------------------------------------

    def _get_kelly_order_quote(self, equity_quote: Decimal) -> Decimal:
        """Compute Kelly-fractional order size. Returns 0 when insufficient history."""
        if (
            not self.config.use_kelly_sizing
            or self._fill_count_for_kelly < self.config.kelly_min_observations
            or self._fill_edge_ewma is None
            or self._fill_edge_variance is None
            or self._fill_edge_variance <= _ZERO
        ):
            return _ZERO
        kelly_size = (self._fill_edge_ewma / self._fill_edge_variance) * self.config.kelly_fraction * equity_quote
        return _clip(kelly_size, self.config.kelly_min_order_quote, self.config.kelly_max_order_quote)

    # ------------------------------------------------------------------
    # Spread / levels helpers
    # ------------------------------------------------------------------

    def _pick_spread_pct(self, regime_spec: RegimeSpec, turnover_x: Decimal) -> Decimal:
        if self.config.override_spread_pct is not None:
            return max(Decimal("0"), to_decimal(self.config.override_spread_pct))
        return self._spread_engine.pick_spread_pct(regime_spec, turnover_x)

    def _pick_levels(self, regime_spec: RegimeSpec, turnover_x: Decimal) -> int:
        return self._spread_engine.pick_levels(regime_spec, turnover_x)

    def _build_side_spreads(
        self, spread_pct: Decimal, skew: Decimal, levels: int, one_sided: str, min_side_spread: Decimal
    ) -> tuple[list[Decimal], list[Decimal]]:
        return self._spread_engine.build_side_spreads(spread_pct, skew, levels, one_sided, min_side_spread)

    def _apply_runtime_spreads_and_sizing(
        self,
        buy_spreads: list[Decimal],
        sell_spreads: list[Decimal],
        levels: int,
        equity_quote: Decimal,
        mid: Decimal,
        quote_size_pct: Decimal,
        size_mult: Decimal = _ONE,
    ) -> None:
        safe_mult = max(_ONE, to_decimal(size_mult))
        self._runtime_size_mult_applied = safe_mult
        self._spread_engine.apply_runtime_spreads_and_sizing(
            runtime_levels=self._runtime_levels,
            buy_spreads=buy_spreads,
            sell_spreads=sell_spreads,
            equity_quote=equity_quote,
            mid=mid,
            quote_size_pct=quote_size_pct,
            size_mult=safe_mult,
            kelly_order_quote=self._get_kelly_order_quote(equity_quote),
            min_notional_quote=self._min_notional_quote(),
            min_base_amount=self._min_base_amount(mid),
            max_order_notional_quote=self.config.max_order_notional_quote,
            max_total_notional_quote=self.config.max_total_notional_quote,
            cooldown_time=int(self.config.cooldown_time),
            no_trade=self.config.no_trade,
            variant=self.config.variant,
            enabled=self.config.enabled,
        )

    # ------------------------------------------------------------------
    # Level execution
    # ------------------------------------------------------------------

    def get_levels_to_execute(self) -> list[str]:
        if self._derisk_force_taker:
            return []
        if getattr(self, "_recovery_close_emitted", False):
            return []
        if str(getattr(self, "_selective_quote_state", "inactive")) == "blocked":
            return []
        cooldown = max(1, int(self._runtime_levels.cooldown_time))
        reissue_cooldown_s = cooldown
        now = self.market_data_provider.time()
        self._recently_issued_levels = {
            k: v for k, v in self._recently_issued_levels.items() if now - v < reissue_cooldown_s
        }
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
                lid = (getattr(ex, "custom_info", None) or {}).get("level_id", "")
                if lid:
                    stopping_level_ids.add(lid)
        if active_count >= self.config.max_active_executors:
            return []
        working_levels_ids = [
            (getattr(executor, "custom_info", None) or {}).get("level_id", "")
            for executor in working_levels
        ]
        working_levels_ids.extend(stopping_level_ids)
        working_levels_ids.extend(self._open_order_level_ids())
        candidates = self.get_not_active_levels_ids(working_levels_ids)
        result = [lid for lid in candidates if lid not in self._recently_issued_levels]
        if str(getattr(self, "_selective_quote_state", "inactive")) == "reduced" and result:
            max_levels_per_side = max(1, int(getattr(self.config, "selective_max_levels_per_side", 1)))
            grouped: dict[str, list[tuple[int, str]]] = {}
            for lid in result:
                side = str(lid).split("_", 1)[0]
                try:
                    level_idx = int(str(lid).rsplit("_", 1)[1])
                except Exception:
                    level_idx = 0
                grouped.setdefault(side, []).append((level_idx, lid))
            allowed: set[str] = set()
            for side_items in grouped.values():
                side_items.sort(key=lambda item: item[0], reverse=True)
                allowed.update(lid for _, lid in side_items[:max_levels_per_side])
            result = [lid for lid in result if lid in allowed]
        for lid in result:
            self._recently_issued_levels[lid] = now
        return result

    def executors_to_refresh(self) -> list[Any]:
        return _runtime_family_adapter(self).executors_to_refresh()

    def _in_reconnect_refresh_suppression_window(self, now_ts: float) -> bool:
        """Return True when executor refresh cancels should be suppressed.

        Reconnect churn can repeatedly tear down/recreate orders before they have a
        chance to rest/fill. Suppressing refresh-driven cancels during this window
        keeps inventory-neutral makers live until feeds stabilize.
        """
        reconnect_cooldown_until = float(getattr(self, "_reconnect_cooldown_until", 0.0) or 0.0)
        reconnect_grace_until = float(getattr(self, "_book_reconnect_grace_until_ts", 0.0) or 0.0)
        return float(now_ts) < max(reconnect_cooldown_until, reconnect_grace_until)

    def get_not_active_levels_ids(self, active_levels_ids: list[str]) -> list[str]:
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

    # ------------------------------------------------------------------
    # Runtime delegation helpers
    # ------------------------------------------------------------------

    def _runtime_spreads_and_amounts_in_quote(self, trade_type: TradeType) -> tuple[list[Decimal], list[Decimal]]:
        return _runtime_family_adapter(self)._runtime_spreads_and_amounts_in_quote(trade_type)

    def _runtime_required_base_amount(self, reference_price: Decimal) -> Decimal:
        return _runtime_family_adapter(self).runtime_required_base_amount(reference_price)

    def _perp_target_base_amount(self, reference_price: Decimal) -> Decimal:
        """Signed base amount implied by the current perp net-exposure target."""
        if reference_price <= 0:
            return Decimal("0")
        processed = getattr(self, "processed_data", {}) or {}
        equity_quote = to_decimal(processed.get("equity_quote", _ZERO))
        if equity_quote <= 0:
            return Decimal("0")
        target_net_base_pct = to_decimal(processed.get("target_net_base_pct", _ZERO))
        return (equity_quote * target_net_base_pct) / reference_price

    # ------------------------------------------------------------------
    # Quantization
    # ------------------------------------------------------------------

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
        if amount <= 0:
            return amount
        min_amount = Decimal("0")
        step = Decimal("0")
        if rule is not None:
            for attr in ("min_order_size", "min_base_amount", "min_amount"):
                value = getattr(rule, attr, None)
                if value is not None:
                    min_amount = max(min_amount, to_decimal(value))
            for attr in ("min_base_amount_increment", "min_order_size_increment", "amount_step"):
                value = getattr(rule, attr, None)
                if value is not None:
                    step = to_decimal(value)
                    break
        paper_min_amount, paper_step = self._order_size_constraints()
        min_amount = max(min_amount, paper_min_amount)
        if paper_step > 0:
            step = max(step, paper_step)
        if min_amount <= 0 and step <= 0:
            return amount
        q_amount = max(amount, min_amount)
        if step > 0:
            units = (q_amount / step).to_integral_value(rounding=ROUND_DOWN)
            q_amount = max(min_amount, units * step)
        return q_amount

    def _quantize_amount_up(self, amount: Decimal) -> Decimal:
        rule = self._trading_rule()
        if amount <= 0:
            return amount
        min_amount = Decimal("0")
        step = Decimal("0")
        if rule is not None:
            for attr in ("min_order_size", "min_base_amount", "min_amount"):
                value = getattr(rule, attr, None)
                if value is not None:
                    min_amount = max(min_amount, to_decimal(value))
            for attr in ("min_base_amount_increment", "min_order_size_increment", "amount_step"):
                value = getattr(rule, attr, None)
                if value is not None:
                    step = to_decimal(value)
                    break
        paper_min_amount, paper_step = self._order_size_constraints()
        min_amount = max(min_amount, paper_min_amount)
        if paper_step > 0:
            step = max(step, paper_step)
        if min_amount <= 0 and step <= 0:
            return amount
        q_amount = max(amount, min_amount)
        if step > 0:
            units = (q_amount / step).to_integral_value(rounding=ROUND_UP)
            q_amount = max(min_amount, units * step)
        return q_amount

    # ------------------------------------------------------------------
    # Notional / size constraints
    # ------------------------------------------------------------------

    def _min_notional_quote(self) -> Decimal:
        rule = self._trading_rule()
        if rule is None:
            return Decimal("0")
        for attr in ("min_notional_size", "min_notional", "min_order_value"):
            value = getattr(rule, attr, None)
            if value is not None:
                return to_decimal(value)
        return Decimal("0")

    def _order_size_constraints(self) -> tuple[Decimal, Decimal]:
        """Return (min_base, base_step) from connector trading rules.

        The bridge injects PaperDesk specs into connector.trading_rules,
        so this works uniformly for paper and live.
        """
        rule = self._trading_rule()
        if rule is None:
            return _ZERO, _ZERO
        try:
            min_qty = _ZERO
            for attr in ("min_order_size", "min_base_amount", "min_amount"):
                v = getattr(rule, attr, None)
                if v is not None:
                    min_qty = max(min_qty, to_decimal(v))
                    break
            size_step = _ZERO
            for attr in ("min_base_amount_increment", "min_order_size_increment", "amount_step"):
                v = getattr(rule, attr, None)
                if v is not None:
                    size_step = max(_ZERO, to_decimal(v))
                    break
            return max(min_qty, size_step), size_step
        except Exception:
            return _ZERO, _ZERO

    def _min_base_amount(self, ref_price: Decimal) -> Decimal:
        min_base = _ZERO
        quote_min = self._min_notional_quote()
        if quote_min > 0 and ref_price > 0:
            min_base = max(min_base, quote_min / ref_price)
        rule = self._trading_rule()
        if rule is not None:
            for attr in ("min_order_size", "min_base_amount", "min_amount"):
                value = getattr(rule, attr, None)
                if value is not None:
                    min_base = max(min_base, to_decimal(value))
        paper_min_base, _ = self._order_size_constraints()
        min_base = max(min_base, paper_min_base)
        return min_base

    def _project_total_amount_quote(
        self,
        equity_quote: Decimal,
        mid: Decimal,
        quote_size_pct: Decimal,
        total_levels: int,
        size_mult: Decimal = _ONE,
    ) -> Decimal:
        level_count = max(0, int(total_levels))
        if level_count <= 0:
            return _ZERO
        safe_mult = max(_ONE, to_decimal(size_mult))
        per_order_quote = max(self._min_notional_quote(), equity_quote * quote_size_pct * safe_mult)
        if self.config.max_order_notional_quote > 0:
            per_order_quote = min(per_order_quote, self.config.max_order_notional_quote)
        projected = per_order_quote * Decimal(level_count)
        if self.config.max_total_notional_quote > 0:
            projected = min(projected, self.config.max_total_notional_quote)
        min_base = self._min_base_amount(mid)
        if min_base > 0 and mid > 0 and projected > 0:
            min_total_quote = min_base * mid * Decimal(level_count)
            if projected < min_total_quote:
                projected = min_total_quote
        if self.config.max_total_notional_quote > 0:
            projected = min(projected, self.config.max_total_notional_quote)
        return projected
