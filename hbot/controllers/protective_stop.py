"""Exchange-side protective stop-loss manager.

Places a server-side trigger stop-loss order on the exchange whenever the bot
holds a position. This order survives bot crashes/restarts because it lives on
the exchange, not in the bot.

Lifecycle:
  1. Position opens -> place stop at entry * (1 - stop_loss_pct) for longs
  2. Position changes (new fill) -> cancel old stop, place new one
  3. Position closes -> cancel stop
  4. Bot restarts -> check for existing protective stop, adopt or re-place

Architecture:
  ``ProtectiveStopBackend`` defines the exchange-agnostic interface.
  ``BitgetStopBackend`` implements it via ccxt for Bitget.
  ``create_stop_backend()`` is the factory that resolves credentials and
  returns the appropriate backend (or ``None`` on failure).
  ``ProtectiveStopManager`` is the stateful manager consumed by the controller.
"""
from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


class ProtectiveStopBackend(ABC):
    """Exchange-agnostic interface for server-side stop-loss orders."""

    @abstractmethod
    def place_stop(self, symbol: str, side: str, amount: Decimal, trigger_price: Decimal) -> Optional[str]:
        """Place a stop order. Return order ID on success, None on failure."""

    @abstractmethod
    def cancel_stop(self, symbol: str, order_id: str) -> bool:
        """Cancel a stop order. Return True on success."""

    @abstractmethod
    def cancel_all_stops(self, symbol: str) -> None:
        """Cancel all protective stop orders for the symbol."""


class BitgetStopBackend(ProtectiveStopBackend):
    """Bitget implementation via ccxt."""

    def __init__(self, exchange: Any, is_perp: bool):
        self._exchange = exchange
        self._is_perp = is_perp

    def place_stop(self, symbol: str, side: str, amount: Decimal, trigger_price: Decimal) -> Optional[str]:
        try:
            order = self._exchange.create_order(
                symbol=symbol,
                type="market",
                side=side,
                amount=float(amount),
                params={
                    "stopLoss": {
                        "triggerPrice": float(trigger_price),
                        "type": "mark_price",
                    },
                },
            )
            order_id = str(order.get("id", ""))
            logger.info(
                "Protective stop placed: %s %s %.8f @ trigger %.2f (order=%s)",
                side, symbol, float(amount), float(trigger_price), order_id,
            )
            return order_id
        except Exception as exc:
            logger.error("Failed to place protective stop: %s", exc)
            return None

    def cancel_stop(self, symbol: str, order_id: str) -> bool:
        try:
            self._exchange.cancel_order(order_id, symbol=symbol)
            logger.info("Protective stop canceled: %s", order_id)
            return True
        except Exception as exc:
            logger.warning("Failed to cancel protective stop %s: %s", order_id, exc)
            return False

    def cancel_all_stops(self, symbol: str) -> None:
        pass


def _resolve_credentials(exchange_id: str) -> Dict[str, str]:
    """Resolve API credentials from environment variables.

    Supports per-bot prefixed vars (e.g. BOT1_BITGET_API_KEY) as well as
    global vars (BITGET_API_KEY). The per-bot prefix is tried first.
    """
    clean_id = exchange_id.replace("_paper_trade", "").replace("_perpetual", "")
    upper = clean_id.upper()

    api_key = os.getenv(f"{upper}_API_KEY", "") or os.getenv(f"BOT1_{upper}_API_KEY", "")
    secret = os.getenv(f"{upper}_API_SECRET", "") or os.getenv(f"BOT1_{upper}_API_SECRET", "")
    passphrase = os.getenv(f"{upper}_PASSPHRASE", "") or os.getenv(f"BOT1_{upper}_PASSPHRASE", "")

    return {"api_key": api_key, "secret": secret, "passphrase": passphrase}


def create_stop_backend(exchange_id: str, is_perp: bool) -> Optional[ProtectiveStopBackend]:
    """Factory: create a ProtectiveStopBackend for the given exchange.

    Returns None if ccxt is unavailable, credentials are missing, or
    the exchange client fails to initialize.
    """
    try:
        import ccxt as ccxt_lib
    except ImportError:
        logger.warning("Protective stop disabled: ccxt not installed")
        return None

    clean_id = exchange_id.replace("_paper_trade", "").replace("_perpetual", "")
    exchange_cls = getattr(ccxt_lib, clean_id, None)
    if exchange_cls is None:
        logger.warning("Protective stop disabled: ccxt.%s not available", clean_id)
        return None

    creds = _resolve_credentials(exchange_id)
    if not creds["api_key"] or not creds["secret"]:
        logger.warning("Protective stop disabled: no API credentials for %s", clean_id)
        return None

    try:
        cfg: Dict[str, Any] = {
            "apiKey": creds["api_key"],
            "secret": creds["secret"],
            "enableRateLimit": True,
            "options": {"defaultType": "swap" if is_perp else "spot"},
        }
        if creds["passphrase"]:
            cfg["password"] = creds["passphrase"]

        exchange = exchange_cls(cfg)
        exchange.load_markets()
        return BitgetStopBackend(exchange, is_perp)
    except Exception as exc:
        logger.warning("Protective stop init failed for %s: %s", clean_id, exc)
        return None


class ProtectiveStopManager:
    """Stateful manager that tracks position and maintains the stop order."""

    def __init__(
        self,
        exchange_id: str,
        trading_pair: str,
        stop_loss_pct: Decimal,
        refresh_interval_s: int = 60,
        backend: Optional[ProtectiveStopBackend] = None,
    ):
        self._exchange_id = exchange_id
        self._is_perp = "perpetual" in exchange_id or "swap" in exchange_id
        self._trading_pair = trading_pair
        self._ccxt_symbol = trading_pair.replace("-", "/")
        if self._is_perp:
            quote = trading_pair.split("-")[1] if "-" in trading_pair else "USDT"
            self._ccxt_symbol = f"{self._ccxt_symbol}:{quote}"
        self._stop_loss_pct = stop_loss_pct
        self._refresh_interval_s = refresh_interval_s
        self._backend = backend
        self._current_stop_order_id: Optional[str] = None
        self._last_position_base: Decimal = _ZERO
        self._last_avg_entry: Decimal = _ZERO
        self._last_refresh_ts: float = 0.0
        self._enabled = backend is not None
        self._init_error: str = "" if self._enabled else "no_backend"

    def initialize(self) -> bool:
        """Initialize the stop manager. Creates backend via factory if none was injected."""
        if self._backend is not None:
            self._enabled = True
            logger.info(
                "Protective stop initialized: %s stop_loss=%.2f%%",
                self._ccxt_symbol, float(self._stop_loss_pct * 100),
            )
            return True
        self._backend = create_stop_backend(
            exchange_id=self._exchange_id,
            is_perp=self._is_perp,
        )
        self._enabled = self._backend is not None
        if self._enabled:
            self._init_error = ""
            logger.info(
                "Protective stop initialized: %s stop_loss=%.2f%%",
                self._ccxt_symbol, float(self._stop_loss_pct * 100),
            )
        else:
            self._init_error = "backend_creation_failed"
        return self._enabled

    def update(self, position_base: Decimal, avg_entry_price: Decimal) -> None:
        if not self._enabled or self._backend is None:
            return

        now = time.time()
        position_changed = (
            position_base != self._last_position_base
            or avg_entry_price != self._last_avg_entry
        )
        time_to_refresh = (now - self._last_refresh_ts) >= self._refresh_interval_s

        if not position_changed and not time_to_refresh:
            return

        self._last_refresh_ts = now

        if abs(position_base) < Decimal("1e-10"):
            if self._current_stop_order_id:
                self._cancel_stop()
            self._last_position_base = _ZERO
            self._last_avg_entry = _ZERO
            return

        if avg_entry_price <= _ZERO:
            return

        if position_base > _ZERO:
            stop_price = avg_entry_price * (Decimal("1") - self._stop_loss_pct)
            stop_side = "sell"
        else:
            stop_price = avg_entry_price * (Decimal("1") + self._stop_loss_pct)
            stop_side = "buy"

        if position_changed and self._current_stop_order_id:
            self._cancel_stop()

        if self._current_stop_order_id is None:
            order_id = self._backend.place_stop(self._ccxt_symbol, stop_side, abs(position_base), stop_price)
            self._current_stop_order_id = order_id

        self._last_position_base = position_base
        self._last_avg_entry = avg_entry_price

    def _cancel_stop(self) -> None:
        if not self._current_stop_order_id or self._backend is None:
            return
        self._backend.cancel_stop(self._ccxt_symbol, self._current_stop_order_id)
        self._current_stop_order_id = None

    def cancel_all(self) -> None:
        self._cancel_stop()

    @property
    def active_stop_order_id(self) -> Optional[str]:
        return self._current_stop_order_id

    @property
    def is_enabled(self) -> bool:
        return self._enabled
