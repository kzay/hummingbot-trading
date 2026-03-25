"""TradingDesk — unified tick loop for all bot strategies.

Orchestrates: snapshot → signal → risk → execute → telemetry.
Owns order lifecycle, position tracking, P&L, and state persistence.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

from controllers.runtime.v3.data_surface import KernelDataSurface
from controllers.runtime.v3.execution.directional import DirectionalExecutionAdapter
from controllers.runtime.v3.execution.hybrid import HybridExecutionAdapter
from controllers.runtime.v3.execution.mm_grid import MMGridExecutionAdapter
from controllers.runtime.v3.orders import (
    CancelOrder,
    ClosePosition,
    DeskAction,
    DeskOrder,
    PartialReduce,
    SubmitOrder,
)
from controllers.runtime.v3.protocols import ExecutionAdapter, StrategySignalSource
from controllers.runtime.v3.risk.desk_risk_gate import DeskRiskGate
from controllers.runtime.v3.risk_types import RiskDecision
from controllers.runtime.v3.signals import TelemetrySchema, TradingSignal
from controllers.runtime.v3.telemetry import TelemetryEmitter
from controllers.runtime.v3.types import MarketSnapshot, PositionSnapshot

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


def _select_adapter(family: str) -> ExecutionAdapter:
    """Select execution adapter by family name."""
    if family == "mm_grid":
        return MMGridExecutionAdapter()
    elif family == "directional":
        return DirectionalExecutionAdapter()
    elif family == "hybrid":
        return HybridExecutionAdapter()
    else:
        raise ValueError(f"Unknown execution family: {family}")


class TradingDesk:
    """Unified trading desk — the single integration point for all bots.

    The tick loop is fixed:
        1. snapshot = data_surface.snapshot()
        2. signal = strategy.evaluate(snapshot)
        3. decision = risk_gate.evaluate(signal, snapshot)
        4. if approved: orders = adapter.translate(signal, snapshot)
        5. telemetry.emit(snapshot, signal, decision)

    Strategy code never touches orders directly.
    """

    def __init__(
        self,
        *,
        strategy: StrategySignalSource,
        data_surface: KernelDataSurface,
        risk_gate: DeskRiskGate,
        execution_family: str = "mm_grid",
        order_submitter: Any = None,
        csv_writer: Any = None,
        redis_publisher: Any = None,
        instance_name: str = "",
    ) -> None:
        self._strategy = strategy
        self._surface = data_surface
        self._risk_gate = risk_gate
        self._adapter: ExecutionAdapter = _select_adapter(execution_family)
        self._submitter = order_submitter
        self._instance = instance_name

        self._telemetry = TelemetryEmitter(
            strategy_schema=strategy.telemetry_schema(),
            csv_writer=csv_writer,
            redis_publisher=redis_publisher,
            instance_name=instance_name,
        )

        # Order tracking
        self._open_orders: dict[str, DeskOrder] = {}
        self._order_id_counter: int = 0
        self._order_submit_ts: dict[str, float] = {}

        # Position tracking (simplified — real impl delegates to kernel)
        self._position = PositionSnapshot()

        # State
        self._tick_count: int = 0
        self._last_signal: TradingSignal = TradingSignal.no_trade()
        self._last_decision: RiskDecision = RiskDecision.approve("none")
        self._warmup_done: bool = False

    # ── Tick loop ─────────────────────────────────────────────────────

    def tick(self, now_ts: float | None = None) -> None:
        """Run one iteration of the tick loop."""
        if now_ts is None:
            now_ts = time.time()

        self._tick_count += 1

        # 1. Snapshot
        snapshot = self._surface.snapshot()

        # 2. Warmup check
        if not self._warmup_done:
            required = self._strategy.warmup_bars_required()
            available = snapshot.indicators.bars_available
            if available < required:
                logger.debug(
                    "Warmup: %d/%d bars available", available, required,
                )
                self._telemetry.emit_tick(
                    snapshot,
                    TradingSignal.no_trade("warmup"),
                    RiskDecision.approve("desk"),
                )
                return
            self._warmup_done = True

        # 3. Signal
        signal = self._strategy.evaluate(snapshot)
        self._last_signal = signal

        # 4. Risk
        decision = self._risk_gate.evaluate(signal, snapshot)
        self._last_decision = decision

        # 5. Execute
        if decision.approved:
            effective_signal = decision.modified_signal or signal
            if effective_signal.family != "no_trade":
                orders = self._adapter.translate(effective_signal, snapshot)
                self._execute_orders(orders, now_ts)

                # Trailing stop management
                actions = self._adapter.manage_trailing(
                    snapshot.position, effective_signal,
                )
                self._execute_actions(actions, now_ts)
        else:
            # Rejected — cancel stale orders
            self._cancel_stale_orders(now_ts)

        # 6. Telemetry
        self._telemetry.emit_tick(snapshot, signal, decision)

    # ── Order lifecycle ───────────────────────────────────────────────

    def _execute_orders(self, orders: list[DeskOrder], now_ts: float) -> None:
        """Submit orders through the order submitter."""
        for order in orders:
            order_id = self._next_order_id()

            if self._submitter is not None:
                try:
                    self._submitter.submit(order, order_id=order_id)
                except Exception as e:
                    logger.warning("Order submit failed: %s", e)
                    continue

            self._open_orders[order_id] = order
            self._order_submit_ts[order_id] = now_ts

    def _execute_actions(self, actions: list[DeskAction], now_ts: float) -> None:
        """Execute desk actions (cancel, close, partial reduce)."""
        for action in actions:
            if isinstance(action, CancelOrder):
                self.cancel_order(action.order_id or action.level_id)
            elif isinstance(action, ClosePosition):
                self._close_position(action.reason)
            elif isinstance(action, PartialReduce):
                self._partial_reduce(action.reduce_ratio, action.reason)
            elif isinstance(action, SubmitOrder):
                self._execute_orders([action.order], now_ts)

    def _cancel_stale_orders(self, now_ts: float, max_age_s: float = 120) -> None:
        """Cancel orders older than max_age_s."""
        stale = [
            oid for oid, ts in self._order_submit_ts.items()
            if now_ts - ts > max_age_s
        ]
        for oid in stale:
            self.cancel_order(oid)

    def _close_position(self, reason: str) -> None:
        """Close entire position at market."""
        if self._submitter is not None:
            try:
                self._submitter.close_position(reason=reason)
            except Exception as e:
                logger.warning("Close position failed: %s", e)
        self.cancel_all()

    def _partial_reduce(self, ratio: Decimal, reason: str) -> None:
        """Reduce position by a fraction."""
        if self._submitter is not None:
            try:
                self._submitter.partial_reduce(ratio=ratio, reason=reason)
            except Exception as e:
                logger.warning("Partial reduce failed: %s", e)

    # ── Public API ────────────────────────────────────────────────────

    def get_position(self) -> PositionSnapshot:
        """Current position (from latest snapshot)."""
        return self._surface.snapshot().position

    def submit_orders(self, orders: list[DeskOrder]) -> list[str]:
        """Submit orders manually. Returns order IDs."""
        ids = []
        for order in orders:
            oid = self._next_order_id()
            if self._submitter is not None:
                self._submitter.submit(order, order_id=oid)
            self._open_orders[oid] = order
            self._order_submit_ts[oid] = time.time()
            ids.append(oid)
        return ids

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a specific order."""
        if order_id in self._open_orders:
            if self._submitter is not None:
                try:
                    self._submitter.cancel(order_id)
                except Exception as e:
                    logger.debug("Cancel failed for %s: %s", order_id, e)
                    return False
            del self._open_orders[order_id]
            self._order_submit_ts.pop(order_id, None)
            return True
        return False

    def cancel_all(self) -> int:
        """Cancel all open orders. Returns count cancelled."""
        count = len(self._open_orders)
        for oid in list(self._open_orders):
            self.cancel_order(oid)
        return count

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def last_signal(self) -> TradingSignal:
        return self._last_signal

    @property
    def last_decision(self) -> RiskDecision:
        return self._last_decision

    @property
    def open_order_count(self) -> int:
        return len(self._open_orders)

    # ── Internal ──────────────────────────────────────────────────────

    def _next_order_id(self) -> str:
        self._order_id_counter += 1
        return f"{self._instance}_desk_{self._order_id_counter}"


__all__ = ["TradingDesk"]
