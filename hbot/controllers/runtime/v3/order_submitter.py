"""Order submitter — translates v3 DeskOrders into HB executor actions.

This is the bridge between the v3 TradingDesk and the Hummingbot
executor framework.  It converts DeskOrder objects into
CreateExecutorAction / StopExecutorAction and injects them into the
controller's action pipeline.

The submitter does NOT call the connector directly — it produces
actions that the existing executor_orchestrator processes on the
next tick.  This means:
- Paper exchange bridge works unchanged
- HB order lifecycle (ack, fill, cancel) works unchanged
- Existing supervisory logic (stale order cleanup, etc.) works unchanged
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

from controllers.runtime.v3.orders import DeskOrder

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


class HBOrderSubmitter:
    """Translates v3 DeskOrder → HB CreateExecutorAction.

    Usage::

        submitter = HBOrderSubmitter(controller)
        submitter.submit(desk_order, order_id="desk_bot1_1")
        submitter.cancel(order_id)
        submitter.close_position(reason="trailing_stop")
    """

    def __init__(self, controller: Any) -> None:
        self._ctrl = controller
        self._pending_actions: list[Any] = []
        self._active_order_ids: dict[str, str] = {}  # desk_id → executor_id

    def submit(self, order: DeskOrder, *, order_id: str = "") -> str:
        """Convert a DeskOrder to a CreateExecutorAction.

        The action is buffered and injected into the controller's
        action pipeline on the next flush.
        """
        try:
            from hummingbot.core.data_type.common import OrderType as HBOrderType, TradeType
            from hummingbot.strategy_v2.executors.position_executor.data_types import (
                PositionExecutorConfig,
            )
            from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction
        except ImportError:
            logger.warning("HB framework not available — cannot submit orders")
            return ""

        cfg = self._ctrl.config
        side = TradeType.BUY if order.side == "buy" else TradeType.SELL

        # Compute amount in base from quote
        price = order.price
        if price <= _ZERO:
            logger.warning("DeskOrder price <= 0, skipping: %s", order)
            return ""
        amount = order.amount_quote / price

        # Quantize
        q_price = self._ctrl._quantize_price(price, side)
        q_amount = self._ctrl._quantize_amount(amount)

        # Build triple barrier config from DeskOrder barriers
        triple_barrier = cfg.triple_barrier_config
        if order.stop_loss is not None or order.take_profit is not None or order.time_limit_s is not None:
            updates = {}
            if order.stop_loss is not None:
                updates["stop_loss"] = float(order.stop_loss / price) if price > _ZERO else None
            if order.take_profit is not None:
                updates["take_profit"] = float(order.take_profit / price) if price > _ZERO else None
            if order.time_limit_s is not None:
                updates["time_limit"] = order.time_limit_s
            try:
                triple_barrier = triple_barrier.model_copy(update=updates)
            except Exception:
                logger.debug("Failed to update triple barrier config", exc_info=True)

        # Order type
        hb_order_type = HBOrderType.MARKET if order.order_type == "market" else HBOrderType.LIMIT
        if hb_order_type == HBOrderType.MARKET:
            try:
                triple_barrier = triple_barrier.model_copy(update={"open_order_type": hb_order_type})
                q_price = None
            except Exception:
                pass

        level_id = order.level_id or order_id or f"v3_{order.side}_{int(time.time())}"

        executor_config = PositionExecutorConfig(
            timestamp=self._ctrl.market_data_provider.time(),
            level_id=level_id,
            connector_name=cfg.connector_name,
            trading_pair=cfg.trading_pair,
            entry_price=q_price,
            amount=q_amount,
            triple_barrier_config=triple_barrier,
            leverage=cfg.leverage,
            side=side,
        )

        action = CreateExecutorAction(
            controller_id=cfg.id,
            executor_config=executor_config,
        )
        self._pending_actions.append(action)
        self._active_order_ids[order_id or level_id] = level_id

        logger.debug(
            "V3 order queued: %s %s %.8f @ %.2f (level=%s)",
            order.side, order.order_type, float(q_amount), float(order.price), level_id,
        )
        return level_id

    def cancel(self, order_id: str) -> bool:
        """Cancel an order by stopping its executor."""
        try:
            from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction
        except ImportError:
            return False

        level_id = self._active_order_ids.pop(order_id, order_id)

        # Find the active executor with this level_id
        executor = self._find_executor_by_level(level_id)
        if executor is None:
            logger.debug("V3 cancel: no executor found for level=%s", level_id)
            return False

        action = StopExecutorAction(
            controller_id=self._ctrl.config.id,
            executor_id=executor.id,
        )
        self._pending_actions.append(action)
        logger.debug("V3 cancel queued: level=%s executor=%s", level_id, executor.id)
        return True

    def close_position(self, *, reason: str = "") -> None:
        """Close all position by stopping all active executors."""
        try:
            from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction
        except ImportError:
            return

        executors = self._get_active_executors()
        for executor in executors:
            action = StopExecutorAction(
                controller_id=self._ctrl.config.id,
                executor_id=executor.id,
            )
            self._pending_actions.append(action)

        logger.info("V3 close_position: %d executors stopped (reason=%s)", len(executors), reason)

    def partial_reduce(self, *, ratio: Decimal, reason: str = "") -> None:
        """Reduce position by closing a fraction of active executors."""
        executors = self._get_active_executors()
        count_to_close = max(1, int(len(executors) * float(ratio)))

        try:
            from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction
        except ImportError:
            return

        for executor in executors[:count_to_close]:
            action = StopExecutorAction(
                controller_id=self._ctrl.config.id,
                executor_id=executor.id,
            )
            self._pending_actions.append(action)

        logger.info(
            "V3 partial_reduce: %d/%d executors stopped (ratio=%.2f reason=%s)",
            count_to_close, len(executors), float(ratio), reason,
        )

    def flush(self) -> list[Any]:
        """Return and clear pending actions.

        Called by the desk integration to inject actions into the
        controller's action pipeline.
        """
        actions = self._pending_actions
        self._pending_actions = []
        return actions

    @property
    def pending_count(self) -> int:
        return len(self._pending_actions)

    # ── Internal ──────────────────────────────────────────────────────

    def _find_executor_by_level(self, level_id: str) -> Any:
        """Find an active executor matching the level_id."""
        for executor in self._get_active_executors():
            cfg = getattr(executor, "executor_config", None) or getattr(executor, "config", None)
            if cfg and getattr(cfg, "level_id", "") == level_id:
                return executor
        return None

    def _get_active_executors(self) -> list[Any]:
        """Get all active executors for this controller."""
        orchestrator = getattr(self._ctrl, "executor_orchestrator", None)
        if orchestrator is None:
            # Fallback: try strategy-level orchestrator
            strategy = getattr(self._ctrl, "strategy", None)
            orchestrator = getattr(strategy, "executor_orchestrator", None)
        if orchestrator is None:
            return []

        active_map = getattr(orchestrator, "active_executors", {})
        controller_id = getattr(self._ctrl.config, "id", "")
        executors = active_map.get(controller_id, [])
        if isinstance(executors, list):
            return executors
        return []


__all__ = ["HBOrderSubmitter"]
