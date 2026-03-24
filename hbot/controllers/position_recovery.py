"""Shared position recovery guard for orphaned positions after restart.

When a bot restarts, positions are restored from persistent state but the
PositionExecutors that monitored SL/TP are lost.  This module provides a
lightweight, strategy-agnostic guard that:

  1. Detects non-zero positions with no managing executor after startup sync.
  2. Monitors mid price against SL/TP thresholds derived from the bot config.
  3. Triggers a MARKET close when a barrier is breached.
  4. Deactivates when the position flattens, the strategy creates its own
     executor, or the close action has been emitted.

Usage (inside SharedRuntimeKernel):
  - After ``_run_startup_position_sync()`` completes, call ``_init_recovery_guard()``.
  - Every tick in ``_preflight_hot_path()``, call ``_check_recovery_guard()``.
"""
from __future__ import annotations

import logging
import time as _time_mod
from decimal import Decimal

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_BALANCE_EPSILON = Decimal("1e-12")


class PositionRecoveryGuard:
    """Code-side SL/TP monitor for orphaned positions that survived a restart.

    Parameters
    ----------
    position_base : Decimal
        Signed position size (positive = long, negative = short).
    avg_entry_price : Decimal
        Weighted average entry price for the position.
    stop_loss_pct : Optional[Decimal]
        Fractional stop-loss distance from entry (e.g. 0.0028 = 28 bps).
    take_profit_pct : Optional[Decimal]
        Fractional take-profit distance from entry.
    time_limit_s : Optional[int]
        Maximum position age in seconds before forced close.
    last_fill_ts : float
        Timestamp of the most recent fill (used for time-limit evaluation).
    connector_name : str
        Connector identifier (for logging / action building).
    trading_pair : str
        Trading pair symbol.
    leverage : int
        Position leverage.
    """

    def __init__(
        self,
        position_base: Decimal,
        avg_entry_price: Decimal,
        stop_loss_pct: Decimal | None,
        take_profit_pct: Decimal | None,
        time_limit_s: int | None,
        last_fill_ts: float,
        connector_name: str,
        trading_pair: str,
        leverage: int,
        activated_at: float | None = None,
    ):
        self.position_base = position_base
        self.avg_entry_price = avg_entry_price
        self.connector_name = connector_name
        self.trading_pair = trading_pair
        self.leverage = leverage
        self.activated_at: float = activated_at if activated_at is not None else _time_mod.time()
        self.last_fill_ts: float = last_fill_ts if last_fill_ts > 0 else self.activated_at
        self.active: bool = True
        self._close_triggered: bool = False

        is_long = position_base > _ZERO
        self.sl_price: Decimal | None = None
        self.tp_price: Decimal | None = None
        self.time_limit_s: int | None = time_limit_s if time_limit_s and time_limit_s > 0 else None

        if stop_loss_pct and stop_loss_pct > _ZERO and avg_entry_price > _ZERO:
            if is_long:
                self.sl_price = avg_entry_price * (Decimal("1") - stop_loss_pct)
            else:
                self.sl_price = avg_entry_price * (Decimal("1") + stop_loss_pct)

        if take_profit_pct and take_profit_pct > _ZERO and avg_entry_price > _ZERO:
            if is_long:
                self.tp_price = avg_entry_price * (Decimal("1") + take_profit_pct)
            else:
                self.tp_price = avg_entry_price * (Decimal("1") - take_profit_pct)

    @property
    def is_long(self) -> bool:
        return self.position_base > _ZERO

    def check(self, mid_price: Decimal, now: float) -> str | None:
        """Evaluate SL/TP/time barriers against current mid price.

        Returns a trigger reason string or ``None`` if no barrier is breached.
        """
        if not self.active or self._close_triggered:
            return None
        if mid_price <= _ZERO:
            return None

        is_long = self.is_long

        if self.sl_price is not None:
            if (is_long and mid_price <= self.sl_price) or (not is_long and mid_price >= self.sl_price):
                return "recovery_stop_loss"

        if self.tp_price is not None:
            if (is_long and mid_price >= self.tp_price) or (not is_long and mid_price <= self.tp_price):
                return "recovery_take_profit"

        if self.time_limit_s is not None and (now - self.activated_at) > self.time_limit_s:
            return "recovery_time_limit"

        return None

    def mark_close_triggered(self) -> None:
        """Mark that a close action has been emitted; prevents duplicate actions."""
        self._close_triggered = True

    def deactivate(self, reason: str) -> None:
        """Deactivate the guard and log the reason."""
        if not self.active:
            return
        self.active = False
        logger.info(
            "Recovery guard deactivated: reason=%s pair=%s position=%.8f entry=%.2f",
            reason,
            self.trading_pair,
            float(self.position_base),
            float(self.avg_entry_price),
        )

    def summary(self) -> dict:
        """Return a compact dict for logging / telemetry."""
        return {
            "active": self.active,
            "close_triggered": self._close_triggered,
            "position": float(self.position_base),
            "entry": float(self.avg_entry_price),
            "sl_price": float(self.sl_price) if self.sl_price is not None else None,
            "tp_price": float(self.tp_price) if self.tp_price is not None else None,
            "time_limit_s": self.time_limit_s,
            "last_fill_ts": self.last_fill_ts,
            "activated_at": self.activated_at,
        }
