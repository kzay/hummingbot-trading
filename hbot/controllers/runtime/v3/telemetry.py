"""Unified telemetry emitter for the v3 trading desk.

Accepts (MarketSnapshot, TradingSignal, RiskDecision) per tick and writes
to CSV, Redis, and Prometheus uniformly.  Column names are auto-discovered
from the desk's base fields + strategy's TelemetrySchema.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

from controllers.runtime.v3.risk_types import RiskDecision
from controllers.runtime.v3.signals import TelemetrySchema, TradingSignal
from controllers.runtime.v3.types import MarketSnapshot

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


# ── Base desk columns (always emitted) ───────────────────────────────

BASE_COLUMNS: list[str] = [
    "timestamp_ms",
    "mid",
    "best_bid",
    "best_ask",
    "spread_pct",
    "regime",
    "equity_quote",
    "daily_pnl_quote",
    "daily_loss_pct",
    "max_drawdown_pct",
    "net_base_pct",
    "base_amount",
    "turnover_x",
    "signal_family",
    "signal_direction",
    "signal_conviction",
    "signal_reason",
    "risk_approved",
    "risk_reason",
    "risk_layer",
]


class TelemetryEmitter:
    """Writes tick-level telemetry to CSV, Redis, and exposes Prometheus metrics.

    Columns are auto-discovered: BASE_COLUMNS + strategy.telemetry_schema().
    No hardcoded strategy-specific columns — new strategies get telemetry
    output without modifying logging code.
    """

    def __init__(
        self,
        strategy_schema: TelemetrySchema,
        csv_writer: Any = None,
        redis_publisher: Any = None,
        instance_name: str = "",
    ) -> None:
        self._schema = strategy_schema
        self._csv = csv_writer
        self._redis = redis_publisher
        self._instance = instance_name

        # Build full column list
        self._columns = BASE_COLUMNS + strategy_schema.column_names

        # Daily rollover state
        self._current_day: int = -1
        self._daily_fill_count: int = 0
        self._daily_turnover_quote: Decimal = _ZERO

    @property
    def columns(self) -> list[str]:
        """Full column list (base + strategy-specific)."""
        return list(self._columns)

    def emit_tick(
        self,
        snapshot: MarketSnapshot,
        signal: TradingSignal,
        decision: RiskDecision,
    ) -> dict[str, Any]:
        """Emit one tick's telemetry.  Returns the assembled row dict."""
        row = self._build_row(snapshot, signal, decision)

        # CSV
        if self._csv is not None:
            try:
                self._csv.log_tick(row)
            except Exception as e:
                logger.debug("CSV write error: %s", e)

        # Redis
        if self._redis is not None:
            try:
                self._publish_redis(row, snapshot, signal)
            except Exception as e:
                logger.debug("Redis publish error: %s", e)

        # Daily rollover check
        self._check_daily_rollover(snapshot)

        return row

    def emit_fill(
        self,
        *,
        order_id: str,
        side: str,
        price: Decimal,
        amount: Decimal,
        fee: Decimal,
        slippage_bps: Decimal = _ZERO,
        realized_pnl: Decimal = _ZERO,
        strategy_name: str = "",
    ) -> dict[str, Any]:
        """Log a fill event to WAL and Redis."""
        fill = {
            "timestamp_ms": int(time.time() * 1000),
            "order_id": order_id,
            "side": side,
            "price": str(price),
            "amount": str(amount),
            "fee": str(fee),
            "slippage_bps": str(slippage_bps),
            "realized_pnl": str(realized_pnl),
            "strategy_name": strategy_name,
            "instance_name": self._instance,
        }

        self._daily_fill_count += 1
        self._daily_turnover_quote += price * amount

        # CSV fill WAL
        if self._csv is not None:
            try:
                self._csv.append_fill(fill)
            except Exception as e:
                logger.debug("Fill WAL write error: %s", e)

        # Redis
        if self._redis is not None:
            try:
                self._redis.publish_fill(fill)
            except Exception as e:
                logger.debug("Fill Redis publish error: %s", e)

        return fill

    def emit_daily_summary(
        self,
        snapshot: MarketSnapshot,
    ) -> dict[str, Any]:
        """Write daily summary row to daily.csv."""
        summary = {
            "date": time.strftime("%Y-%m-%d", time.gmtime()),
            "open_equity": str(snapshot.equity.daily_open_equity),
            "close_equity": str(snapshot.equity.equity_quote),
            "daily_pnl": str(snapshot.equity.daily_pnl_quote),
            "fill_count": self._daily_fill_count,
            "turnover_quote": str(self._daily_turnover_quote),
            "max_drawdown_pct": str(snapshot.equity.max_drawdown_pct),
            "instance_name": self._instance,
        }

        if self._csv is not None:
            try:
                self._csv.log_daily(summary)
            except Exception as e:
                logger.debug("Daily CSV write error: %s", e)

        return summary

    # ── Internal ──────────────────────────────────────────────────────

    def _build_row(
        self,
        snapshot: MarketSnapshot,
        signal: TradingSignal,
        decision: RiskDecision,
    ) -> dict[str, Any]:
        """Assemble a telemetry row from snapshot + signal + decision."""
        row: dict[str, Any] = {
            "timestamp_ms": snapshot.timestamp_ms,
            "mid": snapshot.mid,
            "best_bid": snapshot.order_book.best_bid,
            "best_ask": snapshot.order_book.best_ask,
            "spread_pct": snapshot.order_book.spread_pct,
            "regime": snapshot.regime.name,
            "equity_quote": snapshot.equity.equity_quote,
            "daily_pnl_quote": snapshot.equity.daily_pnl_quote,
            "daily_loss_pct": snapshot.equity.daily_loss_pct,
            "max_drawdown_pct": snapshot.equity.max_drawdown_pct,
            "net_base_pct": snapshot.position.net_base_pct,
            "base_amount": snapshot.position.base_amount,
            "turnover_x": snapshot.equity.daily_turnover_x,
            "signal_family": signal.family,
            "signal_direction": signal.direction,
            "signal_conviction": signal.conviction,
            "signal_reason": signal.reason,
            "risk_approved": decision.approved,
            "risk_reason": decision.reason,
            "risk_layer": decision.layer,
        }

        # Strategy-specific fields from signal metadata
        row.update(self._schema.extract(signal.metadata))

        return row

    def _publish_redis(
        self,
        row: dict[str, Any],
        snapshot: MarketSnapshot,
        signal: TradingSignal,
    ) -> None:
        """Publish snapshot event to Redis with strategy metadata."""
        self._redis.publish_snapshot(
            row,
            strategy_data=signal.metadata,
            instance_name=self._instance,
        )

    def _check_daily_rollover(self, snapshot: MarketSnapshot) -> None:
        """Detect UTC day boundary, emit daily summary, reset counters."""
        current_day = int(snapshot.timestamp_ms // 86_400_000)
        if self._current_day == -1:
            self._current_day = current_day
            return

        if current_day != self._current_day:
            self.emit_daily_summary(snapshot)
            self._current_day = current_day
            self._daily_fill_count = 0
            self._daily_turnover_quote = _ZERO


__all__ = ["BASE_COLUMNS", "TelemetryEmitter"]
