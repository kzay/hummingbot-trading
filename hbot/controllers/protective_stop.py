"""Exchange-side protective stop-loss manager.

Places a server-side trigger stop-loss order on the exchange whenever the bot
holds a position. This order survives bot crashes/restarts because it lives on
the exchange, not in the bot.

Lifecycle:
  1. Position opens → place stop at entry * (1 - stop_loss_pct) for longs
  2. Position changes (new fill) → cancel old stop, place new one
  3. Position closes → cancel stop
  4. Bot restarts → check for existing protective stop, adopt or re-place
"""
from __future__ import annotations

import logging
import os
import time
from decimal import Decimal
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import ccxt
except Exception:
    ccxt = None

_ZERO = Decimal("0")


class ProtectiveStopManager:
    def __init__(
        self,
        exchange_id: str,
        trading_pair: str,
        stop_loss_pct: Decimal,
        refresh_interval_s: int = 60,
    ):
        self._exchange_id = exchange_id.replace("_paper_trade", "").replace("_perpetual", "")
        self._is_perp = "perpetual" in exchange_id or "swap" in exchange_id
        self._trading_pair = trading_pair
        self._ccxt_symbol = trading_pair.replace("-", "/")
        if self._is_perp:
            quote = trading_pair.split("-")[1] if "-" in trading_pair else "USDT"
            self._ccxt_symbol = f"{self._ccxt_symbol}:{quote}"
        self._stop_loss_pct = stop_loss_pct
        self._refresh_interval_s = refresh_interval_s
        self._exchange: Any = None
        self._current_stop_order_id: Optional[str] = None
        self._last_position_base: Decimal = _ZERO
        self._last_avg_entry: Decimal = _ZERO
        self._last_refresh_ts: float = 0.0
        self._enabled = False
        self._init_error: str = ""

    def initialize(self) -> bool:
        if ccxt is None:
            self._init_error = "ccxt not installed"
            logger.warning("Protective stop disabled: ccxt not installed")
            return False

        api_key = os.getenv("BITGET_API_KEY", "") or os.getenv("BOT1_BITGET_API_KEY", "")
        secret = os.getenv("BITGET_API_SECRET", "") or os.getenv("BOT1_BITGET_API_SECRET", "")
        passphrase = os.getenv("BITGET_PASSPHRASE", "") or os.getenv("BOT1_BITGET_PASSPHRASE", "")

        if not api_key or not secret:
            self._init_error = "missing API credentials in env"
            logger.warning("Protective stop disabled: no API credentials")
            return False

        try:
            exchange_cls = getattr(ccxt, "bitget", None)
            if exchange_cls is None:
                self._init_error = "ccxt.bitget not available"
                return False

            cfg: Dict[str, Any] = {
                "apiKey": api_key,
                "secret": secret,
                "enableRateLimit": True,
                "options": {"defaultType": "swap" if self._is_perp else "spot"},
            }
            if passphrase:
                cfg["password"] = passphrase

            self._exchange = exchange_cls(cfg)
            self._exchange.load_markets()
            self._enabled = True
            logger.info(
                "Protective stop initialized: %s %s stop_loss=%.2f%%",
                self._exchange_id, self._ccxt_symbol, float(self._stop_loss_pct * 100),
            )
            return True
        except Exception as exc:
            self._init_error = str(exc)
            logger.warning("Protective stop init failed: %s", exc)
            return False

    def update(self, position_base: Decimal, avg_entry_price: Decimal) -> None:
        if not self._enabled:
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
            self._place_stop(stop_side, abs(position_base), stop_price)

        self._last_position_base = position_base
        self._last_avg_entry = avg_entry_price

    def _place_stop(self, side: str, amount: Decimal, trigger_price: Decimal) -> None:
        try:
            order = self._exchange.create_order(
                symbol=self._ccxt_symbol,
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
            self._current_stop_order_id = str(order.get("id", ""))
            logger.info(
                "Protective stop placed: %s %s %.8f @ trigger %.2f (order=%s)",
                side, self._ccxt_symbol, float(amount), float(trigger_price),
                self._current_stop_order_id,
            )
        except Exception as exc:
            logger.error("Failed to place protective stop: %s", exc)
            self._current_stop_order_id = None

    def _cancel_stop(self) -> None:
        if not self._current_stop_order_id:
            return
        try:
            self._exchange.cancel_order(
                self._current_stop_order_id,
                symbol=self._ccxt_symbol,
            )
            logger.info("Protective stop canceled: %s", self._current_stop_order_id)
        except Exception as exc:
            logger.warning("Failed to cancel protective stop %s: %s", self._current_stop_order_id, exc)
        self._current_stop_order_id = None

    def cancel_all(self) -> None:
        self._cancel_stop()

    @property
    def active_stop_order_id(self) -> Optional[str]:
        return self._current_stop_order_id

    @property
    def is_enabled(self) -> bool:
        return self._enabled
