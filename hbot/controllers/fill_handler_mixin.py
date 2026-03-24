"""Fill-handling mixin — extracted from SharedRuntimeKernel.

Contains fill event processing, deduplication, position bookkeeping,
and fill telemetry. Used as a mixin:
  class SharedRuntimeKernel(FillHandlerMixin, ...):
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

try:
    import orjson as _orjson
except ImportError:
    _orjson = None  # type: ignore[assignment]

from controllers.runtime.core import resolve_runtime_compatibility, runtime_metadata
from platform_lib.core.utils import to_decimal

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_100 = Decimal("100")
_10K = Decimal("10000")
_BALANCE_EPSILON = Decimal("1e-12")


def _identity_text(value: Any) -> str:
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def _config_is_paper(config: Any) -> bool:
    explicit = getattr(config, "is_paper", None)
    if explicit is not None:
        return bool(explicit)
    return str(getattr(config, "bot_mode", "")).strip().lower() == "paper"


class FillHandlerMixin:
    """Mixin providing fill event handling, deduplication, and position bookkeeping."""

    # ------------------------------------------------------------------
    # Static helpers for fill-event deduplication
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_fill_key_ts(value: object) -> str:
        """Normalize fill timestamp into a stable event-key component."""
        if value is None:
            return ""
        try:
            return f"{float(value):.6f}"
        except (ValueError, TypeError):
            pass
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            return f"{datetime.fromisoformat(raw.replace('Z', '+00:00')).timestamp():.6f}"
        except (ValueError, TypeError):
            return raw

    @staticmethod
    def _normalize_fill_key_decimal(value: object) -> str:
        """Normalize numeric fill fields so row/event keys match reliably."""
        try:
            dec = to_decimal(value).normalize()
            return format(dec, "f")
        except Exception:
            return str(value or "").strip()

    @staticmethod
    def _fill_event_dedupe_key(event: object) -> str:
        """Build replay-safe dedupe key for a fill event."""
        order_id = str(getattr(event, "order_id", "") or "").strip()
        for attr in ("exchange_trade_id", "trade_id", "fill_id", "trade_fill_id"):
            trade_id = str(getattr(event, attr, "") or "").strip()
            if trade_id:
                return f"trade:{trade_id}"
        ts_key = FillHandlerMixin._normalize_fill_key_ts(getattr(event, "timestamp", None))
        side = str(getattr(getattr(event, "trade_type", None), "name", "") or "").strip().lower()
        price = FillHandlerMixin._normalize_fill_key_decimal(getattr(event, "price", ""))
        amount = FillHandlerMixin._normalize_fill_key_decimal(getattr(event, "amount", ""))
        if not (order_id or ts_key):
            return ""
        # Include amount so partial fills at different quantities are distinct.
        # Two partials at same order+ts+side+price+amount are still theoretically
        # possible; callers should prefer exchange_trade_id when available.
        return f"legacy:{order_id}|{ts_key}|{side}|{price}|{amount}"

    _fill_legacy_seq: int = 0

    @staticmethod
    def _fill_row_dedupe_key(row: dict[str, object]) -> str:
        """Build dedupe key from a fills.csv row for warm-restart hydration."""
        for key in ("exchange_trade_id", "trade_id", "fill_id", "trade_fill_id"):
            trade_id = str(row.get(key, "") or "").strip()
            if trade_id:
                return f"trade:{trade_id}"
        order_id = str(row.get("order_id", "") or "").strip()
        ts_key = FillHandlerMixin._normalize_fill_key_ts(row.get("ts"))
        side = str(row.get("side", "") or "").strip().lower()
        price = FillHandlerMixin._normalize_fill_key_decimal(row.get("price", ""))
        amount = FillHandlerMixin._normalize_fill_key_decimal(row.get("amount_base", ""))
        if not (order_id or ts_key):
            return ""
        return f"legacy:{order_id}|{ts_key}|{side}|{price}|{amount}"

    @staticmethod
    def _is_excluded_fill_for_risk_accounting(order_id: object) -> bool:
        """Return True when a fill should be ignored for strategy accounting."""
        oid = str(order_id or "").strip().lower()
        return oid.startswith("probe-ord-")

    # ------------------------------------------------------------------
    # Instance methods for fill tracking
    # ------------------------------------------------------------------

    def _record_fill_event_key(self, event_key: str) -> bool:
        """Register fill key; return False when event was already seen."""
        key = str(event_key or "").strip()
        if not key:
            return True
        seen = getattr(self, "_seen_fill_event_keys", None)
        if not isinstance(seen, set):
            seen = set()
            self._seen_fill_event_keys = seen
        fifo = getattr(self, "_seen_fill_event_keys_fifo", None)
        if not isinstance(fifo, deque):
            fifo = deque()
            self._seen_fill_event_keys_fifo = fifo
        cap = int(getattr(self, "_seen_fill_event_keys_cap", 120_000) or 120_000)
        cap = max(1_000, cap)
        if key in seen:
            return False
        seen.add(key)
        fifo.append(key)
        while len(fifo) > cap:
            evicted = fifo.popleft()
            seen.discard(evicted)
        return True

    def _record_seen_fill_order_id(self, order_id: object) -> None:
        """Track order IDs for diagnostics and restart cache hydration."""
        oid = str(order_id or "").strip()
        if not oid:
            return
        seen = getattr(self, "_seen_fill_order_ids", None)
        if not isinstance(seen, set):
            seen = set()
            self._seen_fill_order_ids = seen
        fifo = getattr(self, "_seen_fill_order_ids_fifo", None)
        if not isinstance(fifo, deque):
            fifo = deque()
            self._seen_fill_order_ids_fifo = fifo
        cap = int(getattr(self, "_seen_fill_order_ids_cap", 50_000) or 50_000)
        cap = max(1_000, cap)
        if oid in seen:
            return
        seen.add(oid)
        fifo.append(oid)
        while len(fifo) > cap:
            evicted = fifo.popleft()
            seen.discard(evicted)

    # ------------------------------------------------------------------
    # Main fill handler
    # ------------------------------------------------------------------

    def did_fill_order(self, event: Any) -> None:
        event_instance_name = _identity_text(getattr(event, "instance_name", ""))
        controller_instance_name = _identity_text(getattr(self.config, "instance_name", ""))
        if event_instance_name and controller_instance_name and event_instance_name.lower() != controller_instance_name.lower():
            logger.warning(
                "Ignoring foreign fill event order_id=%s event_instance=%s controller_instance=%s",
                str(getattr(event, "order_id", "") or ""),
                event_instance_name,
                controller_instance_name,
            )
            return
        notional = to_decimal(event.amount) * to_decimal(event.price)
        order_id = str(getattr(event, "order_id", "") or "")
        fill_event_key = FillHandlerMixin._fill_event_dedupe_key(event)
        if not self._record_fill_event_key(fill_event_key):
            logger.debug("Skipping duplicate fill event order_id=%s key=%s", order_id, fill_event_key)
            return
        self._record_seen_fill_order_id(order_id)
        excluded_from_risk_accounting = FillHandlerMixin._is_excluded_fill_for_risk_accounting(order_id)
        if not excluded_from_risk_accounting:
            try:
                ts = getattr(event, "timestamp", None)
                if ts is not None:
                    self._last_fill_ts = float(ts)
                else:
                    self._last_fill_ts = float(self.market_data_provider.time())
            except Exception:
                self._last_fill_ts = float(self.market_data_provider.time())
        if not excluded_from_risk_accounting:
            self._traded_notional_today += notional
            self._fills_count_today += 1
        fee_quote = Decimal("0")
        quote_asset = self.config.trading_pair.split("-")[1]
        try:
            fee_quote = to_decimal(event.trade_fee.fee_amount_in_token(quote_asset, event.price, event.amount))
        except Exception:
            fee_quote = notional * self._taker_fee_pct
            logger.warning("Fee extraction failed for order %s, using estimate %.6f", order_id, fee_quote)
        if not excluded_from_risk_accounting:
            self._fees_paid_today_quote += fee_quote

        if (
            not self._fee_rate_mismatch_warned_today
            and self._fills_count_today >= 10
            and self._traded_notional_today > _ZERO
        ):
            eff = self._fees_paid_today_quote / self._traded_notional_today
            expected_hi = max(self._maker_fee_pct, self._taker_fee_pct)
            expected_lo = min(self._maker_fee_pct, self._taker_fee_pct)
            if expected_hi > _ZERO and eff > expected_hi * Decimal("2.5"):
                logger.warning(
                    "Effective fee_rate %.4fbps is OVER configured maker/taker %.4f/%.4fbps (source=%s). "
                    "Paper stats may be misleading until fee model is reconciled.",
                    float(eff * Decimal("10000")),
                    float(self._maker_fee_pct * Decimal("10000")),
                    float(self._taker_fee_pct * Decimal("10000")),
                    self._fee_source,
                )
                self._fee_rate_mismatch_warned_today = True
            elif expected_lo > _ZERO and eff < expected_lo * Decimal("0.1"):
                logger.warning(
                    "Effective fee_rate %.4fbps is UNDER configured maker/taker %.4f/%.4fbps (source=%s). "
                    "Paper engine may be using near-zero fees — live performance will be worse.",
                    float(eff * Decimal("10000")),
                    float(self._maker_fee_pct * Decimal("10000")),
                    float(self._taker_fee_pct * Decimal("10000")),
                    self._fee_source,
                )
                self._fee_rate_mismatch_warned_today = True
        expected_spread = to_decimal(self.processed_data.get("spread_pct", Decimal("0")))
        mid_ref = to_decimal(self.processed_data.get("mid", event.price))
        adverse_ref = to_decimal(self.processed_data.get("adverse_drift_30s", Decimal("0")))
        fill_price = to_decimal(event.price)
        is_maker = None
        try:
            trade_fee_is_maker = getattr(event.trade_fee, "is_maker", None)
            if trade_fee_is_maker is not None:
                is_maker = bool(trade_fee_is_maker)
        except Exception:
            logger.debug("is_maker extraction failed for order %s", order_id, exc_info=True)
        if is_maker is None:
            event_is_maker = getattr(event, "is_maker", None)
            if isinstance(event_is_maker, bool):
                is_maker = event_is_maker
            elif event_is_maker is not None:
                marker = str(event_is_maker).strip().lower()
                if marker in {"1", "true", "yes", "y", "on"}:
                    is_maker = True
                elif marker in {"0", "false", "no", "n", "off"}:
                    is_maker = False
        if is_maker is None and notional > _ZERO and fee_quote > _ZERO:
            maker_fee_pct = max(_ZERO, to_decimal(getattr(self, "_maker_fee_pct", _ZERO)))
            taker_fee_pct = max(_ZERO, to_decimal(getattr(self, "_taker_fee_pct", _ZERO)))
            if maker_fee_pct > _ZERO or taker_fee_pct > _ZERO:
                fee_rate_pct = abs(fee_quote / notional)
                maker_gap = abs(fee_rate_pct - maker_fee_pct)
                taker_gap = abs(fee_rate_pct - taker_fee_pct)
                if maker_gap < taker_gap:
                    is_maker = True
                elif taker_gap < maker_gap:
                    is_maker = False
        if is_maker is None:
            is_maker = False
            if (event.trade_type.name.lower() == "buy" and fill_price < mid_ref) or (event.trade_type.name.lower() == "sell" and fill_price > mid_ref):
                is_maker = True

        realized_pnl = _ZERO
        if not excluded_from_risk_accounting:
            realized_pnl = self._update_position_from_fill(event, fill_price, fee_quote)

        fill_edge_bps = _ZERO
        if mid_ref > _ZERO and not excluded_from_risk_accounting:
            side_sign = Decimal("-1") if event.trade_type.name.lower() == "buy" else _ONE
            fill_edge_bps = (fill_price - mid_ref) * side_sign / mid_ref * _10K
            _alpha = Decimal("0.05")
            if self._fill_edge_ewma is None:
                self._fill_edge_ewma = fill_edge_bps
                self._fill_edge_variance = fill_edge_bps ** 2
            else:
                prev_ewma = self._fill_edge_ewma
                self._fill_edge_ewma = _alpha * fill_edge_bps + (_ONE - _alpha) * prev_ewma
                deviation_sq = (fill_edge_bps - prev_ewma) ** 2
                if self._fill_edge_variance is None:
                    self._fill_edge_variance = deviation_sq
                else:
                    self._fill_edge_variance = _alpha * deviation_sq + (_ONE - _alpha) * self._fill_edge_variance
            self._fill_count_for_kelly += 1
            cost_floor_bps = (self._maker_fee_pct + self.config.slippage_est_pct) * _10K
            if self._fill_edge_ewma < -cost_floor_bps:
                self._adverse_fill_count += 1
            elif self._fill_edge_ewma >= -cost_floor_bps * Decimal("0.5"):
                self._adverse_fill_count = 0

        if mid_ref > _ZERO:
            price_deviation_pct = abs(fill_price - mid_ref) / mid_ref
            if price_deviation_pct > Decimal("0.01"):
                logger.warning("Fill price deviation %.4f%% for order %s (fill=%.2f mid=%.2f)",
                               float(price_deviation_pct * _100), order_id, float(fill_price), float(mid_ref))

        slippage_bps = _ZERO
        if mid_ref > _ZERO:
            if event.trade_type.name.lower() == "buy":
                slippage_bps = (fill_price - mid_ref) / mid_ref * _10K
            else:
                slippage_bps = (mid_ref - fill_price) / mid_ref * _10K
        auto_calibration_record_fill = getattr(self, "_auto_calibration_record_fill", None)
        if callable(auto_calibration_record_fill) and not excluded_from_risk_accounting:
            auto_calibration_record_fill(
                now_ts=float(event.timestamp),
                notional_quote=notional,
                fee_quote=fee_quote,
                realized_pnl_quote=realized_pnl,
                slippage_bps=slippage_bps,
                fill_edge_bps=fill_edge_bps if mid_ref > _ZERO else _ZERO,
                is_maker=bool(is_maker),
            )

        event_ts = datetime.fromtimestamp(event.timestamp, tz=UTC).isoformat()
        _exchange_trade_id = ""
        for _etid_attr in ("exchange_trade_id", "trade_id", "fill_id", "trade_fill_id"):
            _etid_val = str(getattr(event, _etid_attr, "") or "").strip()
            if _etid_val:
                _exchange_trade_id = _etid_val
                break
        self._csv.log_fill(
            {
                "bot_variant": self.config.variant,
                "exchange": self.config.connector_name,
                "trading_pair": self.config.trading_pair,
                "side": event.trade_type.name.lower(),
                "price": str(event.price),
                "amount_base": str(event.amount),
                "notional_quote": str(notional),
                "fee_quote": str(fee_quote),
                "order_id": order_id,
                "exchange_trade_id": _exchange_trade_id,
                "state": self._ops_guard.state.value,
                "regime": str(self.processed_data.get("regime", "")),
                "alpha_policy_state": str(self.processed_data.get("alpha_policy_state", "maker_two_sided")),
                "alpha_policy_reason": str(self.processed_data.get("alpha_policy_reason", "unknown")),
                "mid_ref": str(mid_ref),
                "expected_spread_pct": str(expected_spread),
                "adverse_drift_30s": str(adverse_ref),
                "fee_source": self._fee_source,
                "is_maker": str(is_maker),
                "realized_pnl_quote": str(realized_pnl),
            },
            ts=event_ts,
        )

        if not _config_is_paper(self.config):
            self._publish_fill_telemetry(event, event_ts, order_id, notional, fee_quote, is_maker, realized_pnl)

        if not excluded_from_risk_accounting:
            self._save_daily_state(force=True)

        # Immediately reconcile local position with the desk/exchange so the
        # next telemetry snapshot broadcasts the correct position to the
        # dashboard.  Without this, a dropped Redis event can leave the bot
        # reporting "flat" while the desk holds a real position.
        _force_recon = getattr(self, "_force_position_reconciliation", None)
        if callable(_force_recon):
            try:
                _force_recon()
            except Exception:
                logger.debug("Post-fill forced position reconciliation failed", exc_info=True)

    def _update_position_from_fill(self, event, fill_price: Decimal, fee_quote: Decimal) -> Decimal:
        """Update position state from a fill event; return realized PnL."""
        realized_pnl = _ZERO
        fill_amount = to_decimal(event.amount)
        fill_position_action = str(getattr(event, "position_action", "auto") or "auto").strip().lower()
        position_mode = str(getattr(self.config, "position_mode", "ONEWAY") or "ONEWAY").upper()
        if "HEDGE" not in position_mode:
            fill_position_action = "auto"
        if fill_position_action in {"open_long", "close_long", "open_short", "close_short"}:
            if fill_position_action == "open_long":
                new_qty = self._position_long_base + fill_amount
                if new_qty > _ZERO:
                    old_cost = self._avg_entry_price_long * self._position_long_base
                    new_cost = fill_price * fill_amount
                    self._avg_entry_price_long = (old_cost + new_cost) / new_qty
                self._position_long_base = new_qty
            elif fill_position_action == "close_long":
                close_amount = min(fill_amount, self._position_long_base)
                fee_portion = fee_quote * close_amount / fill_amount if fill_amount > _ZERO else fee_quote
                if close_amount > _ZERO and self._avg_entry_price_long > _ZERO:
                    realized_pnl = (fill_price - self._avg_entry_price_long) * close_amount - fee_portion
                self._position_long_base = max(_ZERO, self._position_long_base - fill_amount)
                if self._position_long_base <= _BALANCE_EPSILON:
                    self._avg_entry_price_long = _ZERO
            elif fill_position_action == "open_short":
                new_qty = self._position_short_base + fill_amount
                if new_qty > _ZERO:
                    old_cost = self._avg_entry_price_short * self._position_short_base
                    new_cost = fill_price * fill_amount
                    self._avg_entry_price_short = (old_cost + new_cost) / new_qty
                self._position_short_base = new_qty
            elif fill_position_action == "close_short":
                close_amount = min(fill_amount, self._position_short_base)
                fee_portion = fee_quote * close_amount / fill_amount if fill_amount > _ZERO else fee_quote
                if close_amount > _ZERO and self._avg_entry_price_short > _ZERO:
                    realized_pnl = (self._avg_entry_price_short - fill_price) * close_amount - fee_portion
                self._position_short_base = max(_ZERO, self._position_short_base - fill_amount)
                if self._position_short_base <= _BALANCE_EPSILON:
                    self._avg_entry_price_short = _ZERO
        else:
            if event.trade_type.name.lower() == "buy":
                if self._position_base < _ZERO and self._avg_entry_price > _ZERO:
                    close_amount = min(fill_amount, abs(self._position_base))
                    fee_portion = fee_quote * close_amount / fill_amount if fill_amount > _ZERO else fee_quote
                    realized_pnl = (self._avg_entry_price - fill_price) * close_amount - fee_portion
                new_pos = self._position_base + fill_amount
                if new_pos > _ZERO and fill_amount > _ZERO:
                    existing_long = max(_ZERO, self._position_base)
                    opening_amount = new_pos - existing_long
                    old_cost = self._avg_entry_price * existing_long
                    new_cost = fill_price * opening_amount
                    self._avg_entry_price = (old_cost + new_cost) / new_pos if new_pos > _ZERO else fill_price
                self._position_base = new_pos
            else:
                if self._position_base > _ZERO and self._avg_entry_price > _ZERO:
                    close_amount = min(fill_amount, self._position_base)
                    fee_portion = fee_quote * close_amount / fill_amount if fill_amount > _ZERO else fee_quote
                    realized_pnl = (fill_price - self._avg_entry_price) * close_amount - fee_portion
                new_pos = self._position_base - fill_amount
                if new_pos < _ZERO and fill_amount > _ZERO:
                    existing_short = max(_ZERO, -self._position_base)
                    opening_amount = abs(new_pos) - existing_short
                    old_cost = self._avg_entry_price * existing_short
                    new_cost = fill_price * opening_amount
                    self._avg_entry_price = (old_cost + new_cost) / abs(new_pos) if abs(new_pos) > _ZERO else fill_price
                self._position_base = new_pos
            # Only derive long/short from net in ONEWAY mode.
            # In HEDGE mode, long/short are tracked independently via
            # explicit position actions; overwriting them here would
            # corrupt hedge-mode accounting.
            if "HEDGE" not in position_mode:
                if self._position_base > _ZERO:
                    self._position_long_base = self._position_base
                    self._avg_entry_price_long = self._avg_entry_price
                    self._position_short_base = _ZERO
                    self._avg_entry_price_short = _ZERO
                elif self._position_base < _ZERO:
                    self._position_short_base = abs(self._position_base)
                    self._avg_entry_price_short = self._avg_entry_price
                    self._position_long_base = _ZERO
                    self._avg_entry_price_long = _ZERO
                else:
                    self._position_long_base = _ZERO
                    self._position_short_base = _ZERO
                    self._avg_entry_price_long = _ZERO
                    self._avg_entry_price_short = _ZERO
                    self._avg_entry_price = _ZERO
        self._position_base = self._position_long_base - self._position_short_base
        self._position_gross_base = self._position_long_base + self._position_short_base
        if self._position_base > _ZERO:
            self._avg_entry_price = self._avg_entry_price_long
        elif self._position_base < _ZERO:
            self._avg_entry_price = self._avg_entry_price_short
        elif self._position_gross_base <= _BALANCE_EPSILON:
            self._avg_entry_price = _ZERO
        self._realized_pnl_today += realized_pnl
        return realized_pnl

    def _publish_fill_telemetry(self, event, event_ts: str, order_id: str,
                                notional: Decimal, fee_quote: Decimal,
                                is_maker: bool, realized_pnl: Decimal) -> None:
        """Publish fill telemetry to Redis (live mode only)."""
        try:
            import json as _json_tel
            import uuid as _uuid_tel

            from platform_lib.contracts.event_identity import validate_event_identity as _validate_event_identity

            surface = getattr(self, "_runtime_compat", None)
            if surface is None:
                runtime_impl = type(self).__name__.replace("Controller", "") or "shared_runtime_v24"
                surface = resolve_runtime_compatibility(self.config, runtime_impl=runtime_impl)
                self._runtime_compat = surface
            runtime_compat = surface

            _r = self._get_telemetry_redis()
            if _r is not None:
                _p = {
                    "event_id": str(_uuid_tel.uuid4()),
                    "event_type": "bot_fill",
                    "event_version": "v1",
                    "schema_version": "1.0",
                    "ts_utc": event_ts,
                    "producer": f"{runtime_compat.telemetry_producer_prefix}.{self.config.instance_name}",
                    "instance_name": self.config.instance_name,
                    "controller_id": str(getattr(self, "id", "") or getattr(self.config, "id", "") or self.config.instance_name or ""),
                    "connector_name": self.config.connector_name,
                    "trading_pair": self.config.trading_pair,
                    "side": event.trade_type.name.lower(),
                    "price": float(event.price),
                    "amount_base": float(event.amount),
                    "notional_quote": float(notional),
                    "fee_quote": float(fee_quote),
                    "order_id": order_id,
                    "accounting_source": "live_connector",
                    "is_maker": bool(is_maker),
                    "realized_pnl_quote": float(realized_pnl),
                    "bot_state": self._ops_guard.state.value,
                    "metadata": runtime_metadata(runtime_compat),
                }
                _identity_ok, _identity_reason = _validate_event_identity(_p)
                if _identity_ok:
                    _fill_s = _orjson.dumps(_p).decode() if _orjson is not None else _json_tel.dumps(_p)
                    _r.xadd("hb.bot_telemetry.v1", {"payload": _fill_s}, maxlen=100_000, approximate=True)
                else:
                    logger.warning(
                        "Fill telemetry dropped for order %s due to identity contract: %s",
                        order_id,
                        _identity_reason,
                    )
        except Exception:
            logger.debug("Fill telemetry publish failed for order %s", order_id, exc_info=True)

    def did_cancel_order(self, cancelled_event: Any) -> None:
        self._cancel_events_ts.append(float(self.market_data_provider.time()))
        self._cancel_fail_streak = 0

    def did_fail_order(self, order_failed_event: Any) -> None:
        msg = (order_failed_event.error_message or "").lower()
        if "cancel" in msg:
            self._cancel_fail_streak += 1
