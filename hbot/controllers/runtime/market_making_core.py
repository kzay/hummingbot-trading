from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from hummingbot.core.data_type.common import TradeType
from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig

from controllers.runtime.data_context import RuntimeDataContext
from controllers.runtime.execution_context import RuntimeExecutionPlan
from platform_lib.core.utils import to_decimal

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_BALANCE_EPSILON = Decimal("1e-8")




class MarketMakingRuntimeAdapter:
    """Explicit market-making family adapter for the shared runtime kernel."""

    def __init__(self, controller: Any):
        self._controller = controller

    def build_execution_plan(self, data_context: RuntimeDataContext) -> RuntimeExecutionPlan:
        controller = self._controller
        levels = controller._pick_levels(data_context.regime_spec, data_context.spread_state.turnover_x)
        controller._runtime_levels.executor_refresh_time = int(data_context.regime_spec.refresh_s)
        one_sided = controller._resolve_quote_side_mode(
            mid=data_context.mid,
            regime_name=data_context.regime_name,
            regime_spec=data_context.regime_spec,
        )
        buy_spreads, sell_spreads = controller._build_side_spreads(
            data_context.spread_state.spread_pct,
            data_context.spread_state.skew,
            levels,
            one_sided,
            data_context.market.side_spread_floor,
        )
        buy_spreads, sell_spreads = controller._apply_spread_competitiveness_cap(
            buy_spreads=buy_spreads,
            sell_spreads=sell_spreads,
            market=data_context.market,
        )
        alpha_state = str(getattr(controller, "_alpha_policy_state", "maker_two_sided"))
        if alpha_state == "no_trade":
            buy_spreads = []
            sell_spreads = []
        elif alpha_state in {"aggressive_buy", "aggressive_sell"}:
            cross_mult = max(_ONE, to_decimal(getattr(controller.config, "alpha_policy_cross_spread_mult", Decimal("1.05"))))
            aggressive_spread = max(data_context.market.side_spread_floor * cross_mult, Decimal("0.000001"))
            if alpha_state == "aggressive_buy" and buy_spreads:
                buy_spreads = [min(spread, aggressive_spread) for spread in buy_spreads]
                sell_spreads = []
            elif alpha_state == "aggressive_sell" and sell_spreads:
                sell_spreads = [min(spread, aggressive_spread) for spread in sell_spreads]
                buy_spreads = []
        size_mult = controller._compute_pnl_governor_size_mult(
            equity_quote=data_context.equity_quote,
            turnover_x=data_context.spread_state.turnover_x,
        )
        projected_total_quote = controller._project_total_amount_quote(
            equity_quote=data_context.equity_quote,
            mid=data_context.mid,
            quote_size_pct=data_context.regime_spec.quote_size_pct,
            total_levels=max(1, len(buy_spreads) + len(sell_spreads)),
            size_mult=size_mult,
        )
        return RuntimeExecutionPlan(
            family="market_making",
            buy_spreads=buy_spreads,
            sell_spreads=sell_spreads,
            projected_total_quote=projected_total_quote,
            size_mult=size_mult,
            metadata={
                "levels": max(len(buy_spreads), len(sell_spreads)),
                "executor_refresh_time": int(controller._runtime_levels.executor_refresh_time),
                "quote_side_mode": str(getattr(controller, "_quote_side_mode", "off")),
                "quote_side_reason": str(getattr(controller, "_quote_side_reason", "regime")),
            },
        )

    def apply_execution_plan(self, plan: RuntimeExecutionPlan, *, equity_quote: Decimal, mid: Decimal, quote_size_pct: Decimal) -> None:
        self._controller._apply_runtime_spreads_and_sizing(
            buy_spreads=plan.buy_spreads,
            sell_spreads=plan.sell_spreads,
            levels=max(len(plan.buy_spreads), len(plan.sell_spreads)),
            equity_quote=equity_quote,
            mid=mid,
            quote_size_pct=quote_size_pct,
            size_mult=plan.size_mult,
        )

    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal) -> Any:
        controller = self._controller
        side = controller.get_trade_type_from_level_id(level_id)
        q_price = controller._quantize_price(price, side)
        q_amount = controller._quantize_amount(amount)
        min_notional_quote = controller._min_notional_quote()
        if min_notional_quote > 0 and q_price > 0 and (q_amount * q_price) < min_notional_quote:
            q_amount = controller._quantize_amount_up(min_notional_quote / q_price)
        triple_barrier_cfg = controller.config.triple_barrier_config
        entry_price = q_price
        if controller._derisk_force_taker:
            try:
                from hummingbot.core.data_type.common import OrderType as _HBOrderType

                triple_barrier_cfg = controller.config.triple_barrier_config.model_copy(
                    update={"open_order_type": _HBOrderType.MARKET}
                )
                entry_price = None
            except Exception:
                logger.debug("Derisk force-taker fallback to default open order type", exc_info=True)
        if controller._derisk_force_taker and level_id == "position_rebalance":
            trace_derisk = getattr(controller, "_trace_derisk", None)
            if callable(trace_derisk):
                trace_derisk(
                    controller.market_data_provider.time(),
                    "rebalance_executor_config",
                    level_id=level_id,
                    side=getattr(side, "name", str(side)),
                    amount=q_amount,
                    entry_price=entry_price,
                    open_order_type=getattr(triple_barrier_cfg, "open_order_type", None),
                )
        return PositionExecutorConfig(
            timestamp=controller.market_data_provider.time(),
            level_id=level_id,
            connector_name=controller.config.connector_name,
            trading_pair=controller.config.trading_pair,
            entry_price=entry_price,
            amount=q_amount,
            triple_barrier_config=triple_barrier_cfg,
            leverage=controller.config.leverage,
            side=side,
        )

    def executors_to_refresh(self) -> list[Any]:
        controller = self._controller
        refresh_s = max(1, int(controller._runtime_levels.executor_refresh_time))
        ack_timeout_s = max(5, controller.config.order_ack_timeout_s)
        now = controller.market_data_provider.time()
        reconnect_refresh_suppressed = controller._in_reconnect_refresh_suppression_window(now)
        stale_age_s = refresh_s

        open_order_timeout_s = int(getattr(controller.config, "open_order_timeout_s", 0) or 0)

        if reconnect_refresh_suppressed:
            stale_executors = []
            stuck_executors = []
            entry_timeout_executors = []
            controller._consecutive_stuck_ticks = 0
        else:

            def _is_unacked_executor(executor: Any) -> bool:
                ex_order_id = str(getattr(executor, "order_id", "") or "")
                if ex_order_id:
                    return False
                custom = getattr(executor, "custom_info", None) or {}
                if isinstance(custom, dict):
                    custom_order_id = str(custom.get("order_id", "") or "")
                    if custom_order_id:
                        return False
                return True

            def _is_acked_executor(executor: Any) -> bool:
                return not _is_unacked_executor(executor)

            def _stale_filter(x: Any) -> bool:
                if x.is_trading or not x.is_active:
                    return False
                age = now - x.timestamp
                if age <= stale_age_s:
                    return False
                if open_order_timeout_s > 0 and _is_acked_executor(x):
                    return age > open_order_timeout_s
                return True

            stale_executors = controller.filter_executors(
                executors=controller.executors_info,
                filter_func=_stale_filter,
            )
            stuck_executors = controller.filter_executors(
                executors=controller.executors_info,
                filter_func=lambda x: (
                    not x.is_trading
                    and x.is_active
                    and _is_unacked_executor(x)
                    and now - x.timestamp > ack_timeout_s
                    and now - x.timestamp <= refresh_s
                ),
            )

            if open_order_timeout_s > 0:
                entry_timeout_executors = controller.filter_executors(
                    executors=controller.executors_info,
                    filter_func=lambda x: (
                        not x.is_trading
                        and x.is_active
                        and _is_acked_executor(x)
                        and now - x.timestamp > open_order_timeout_s
                    ),
                )
                if entry_timeout_executors:
                    logger.info(
                        "Entry timeout: %d executor(s) unfilled after %ds, canceling",
                        len(entry_timeout_executors),
                        open_order_timeout_s,
                    )
            else:
                entry_timeout_executors = []

            if stuck_executors:
                logger.warning(
                    "Order ack timeout: %d executor(s) stuck in placing state for >%ds",
                    len(stuck_executors),
                    ack_timeout_s,
                )
                controller._consecutive_stuck_ticks += 1
            else:
                controller._consecutive_stuck_ticks = 0

        if not reconnect_refresh_suppressed:
            cancel_stale_fn = getattr(controller, "_cancel_stale_orders", None)
            if callable(cancel_stale_fn):
                effective_stale_age = max(stale_age_s, open_order_timeout_s) if open_order_timeout_s > 0 else stale_age_s
                canceled = cancel_stale_fn(stale_age_s=effective_stale_age, now_ts=now)
                if canceled > 0:
                    logger.info(
                        "Canceled %d stale order(s) older than %.1fs for %s during refresh reconciliation",
                        canceled,
                        effective_stale_age,
                        controller.config.trading_pair,
                    )

        from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction

        all_executors = stale_executors + stuck_executors + entry_timeout_executors
        seen_ids: set[str] = set()
        actions: list[Any] = []
        for executor in all_executors:
            eid = str(getattr(executor, "id", ""))
            if eid and eid not in seen_ids:
                seen_ids.add(eid)
                actions.append(StopExecutorAction(controller_id=controller.config.id, executor_id=eid))

        if controller._pending_stale_cancel_actions:
            for action in controller._pending_stale_cancel_actions:
                aeid = str(getattr(action, "executor_id", ""))
                if aeid and aeid not in seen_ids:
                    seen_ids.add(aeid)
                    actions.append(action)
            controller._pending_stale_cancel_actions = []
        return actions

    def get_price_and_amount(self, level_id: str) -> tuple[Decimal, Decimal]:
        controller = self._controller
        level = controller.get_level_from_level_id(level_id)
        trade_type = controller.get_trade_type_from_level_id(level_id)
        spreads, amounts_quote = self._runtime_spreads_and_amounts_in_quote(trade_type)
        reference_price = to_decimal(controller.processed_data.get("reference_price", 0))
        if reference_price <= _ZERO:
            reference_price = to_decimal(getattr(controller, "_last_mid", 0))
        if reference_price <= _ZERO:
            raise ValueError("No reference price available — connector not ready")
        spread_in_pct = spreads[int(level)] * to_decimal(controller.processed_data.get("spread_multiplier", 1))
        side_multiplier = Decimal("-1") if trade_type == TradeType.BUY else Decimal("1")
        order_price = reference_price * (1 + side_multiplier * spread_in_pct)
        return order_price, amounts_quote[int(level)] / order_price

    def _runtime_spreads_and_amounts_in_quote(self, trade_type: TradeType) -> tuple[list[Decimal], list[Decimal]]:
        controller = self._controller
        buy_amounts_pct = controller._runtime_levels.buy_amounts_pct
        sell_amounts_pct = controller._runtime_levels.sell_amounts_pct
        total_pct = sum(buy_amounts_pct) + sum(sell_amounts_pct)
        if total_pct <= 0:
            return [], []
        if trade_type == TradeType.BUY:
            normalized = [amt_pct / total_pct for amt_pct in buy_amounts_pct]
            spreads = controller._runtime_levels.buy_spreads
        else:
            normalized = [amt_pct / total_pct for amt_pct in sell_amounts_pct]
            spreads = controller._runtime_levels.sell_spreads
        amounts = [amt_pct * controller._runtime_levels.total_amount_quote for amt_pct in normalized]
        return spreads, amounts

    def runtime_required_base_amount(self, reference_price: Decimal) -> Decimal:
        if reference_price <= 0:
            return _ZERO
        _, sell_amounts_quote = self._runtime_spreads_and_amounts_in_quote(TradeType.SELL)
        return sum(sell_amounts_quote) / reference_price

    def position_rebalance_floor(self, reference_price: Decimal) -> Decimal:
        controller = self._controller
        floor = _BALANCE_EPSILON
        min_base_mult = max(
            _ZERO,
            to_decimal(getattr(controller.config, "position_rebalance_min_base_mult", Decimal("1.0"))),
        )
        min_base_amount_fn = getattr(controller, "_min_base_amount", None)
        if callable(min_base_amount_fn):
            try:
                min_exchange_base = max(_ZERO, to_decimal(min_base_amount_fn(reference_price)))
                floor = max(floor, min_exchange_base * min_base_mult)
            except Exception:
                logger.debug("position rebalance floor resolution failed", exc_info=True)
        return floor


__all__ = ["MarketMakingRuntimeAdapter"]
