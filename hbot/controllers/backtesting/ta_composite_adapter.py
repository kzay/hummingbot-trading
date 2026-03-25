"""Composable TA adapter for backtesting.

Evaluates entry/exit rules built from SIGNAL_REGISTRY primitives with
configurable AND/OR rule modes, ATR-based position management (SL/TP/
trailing stop/max hold), daily risk gating, and market/limit entry types.

Config-driven via ``TaCompositeConfig`` — YAML-hydrated by the adapter
registry just like every other adapter.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from controllers.backtesting.ta_signals import (
    SIGNAL_REGISTRY,
    SignalResult,
    validate_signal_params,
    warmup_bars_for_signal,
)
from controllers.backtesting.types import CandleRow
from controllers.price_buffer import PriceBuffer
from simulation.desk import PaperDesk
from simulation.types import (
    InstrumentId,
    InstrumentSpec,
    OrderSide,
    PaperOrderType,
)

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")


# ---------------------------------------------------------------------------
# Config structures
# ---------------------------------------------------------------------------

@dataclass
class SignalConfig:
    signal_type: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    invert: bool = False


@dataclass
class RuleConfig:
    mode: str = "all"
    signals: list[SignalConfig] = field(default_factory=list)


def _parse_signal_config(raw: dict[str, Any]) -> SignalConfig:
    return SignalConfig(
        signal_type=raw.get("signal_type", raw.get("type", "")),
        params={k: v for k, v in raw.items() if k not in ("signal_type", "type", "invert")},
        invert=bool(raw.get("invert", False)),
    )


def _parse_rule_config(raw: dict[str, Any]) -> RuleConfig:
    signals_raw = raw.get("signals", [])
    signals = [_parse_signal_config(s) for s in signals_raw]
    return RuleConfig(mode=raw.get("mode", "all"), signals=signals)


@dataclass
class TaCompositeConfig:
    entry_rules: RuleConfig = field(default_factory=RuleConfig)
    exit_rules: RuleConfig = field(default_factory=RuleConfig)

    risk_pct: Decimal = Decimal("0.10")
    atr_period: int = 14
    sl_atr_mult: Decimal = Decimal("1.5")
    tp_atr_mult: Decimal = Decimal("2.0")
    trail_activate_r: Decimal = Decimal("1.0")
    trail_offset_atr: Decimal = Decimal("0.8")
    max_hold_minutes: int = 120
    cooldown_s: int = 300
    max_daily_loss_pct: Decimal = Decimal("0.03")
    min_warmup_bars: int = 0
    entry_order_type: str = "market"
    limit_entry_offset_atr: Decimal = Decimal("0.1")

    def hydrate_nested(self) -> None:
        """Convert raw dict entry/exit rules into proper dataclass instances.

        Called after ``hydrate_config`` which sets raw dicts from YAML.
        """
        if isinstance(self.entry_rules, dict):
            self.entry_rules = _parse_rule_config(self.entry_rules)
        if isinstance(self.exit_rules, dict):
            self.exit_rules = _parse_rule_config(self.exit_rules)

    def validate(self) -> None:
        """Raise ``ValueError`` for invalid configuration."""
        if not self.entry_rules.signals:
            raise ValueError("entry_rules.signals must be non-empty")
        if self.entry_rules.mode not in ("all", "any"):
            raise ValueError(f"entry_rules.mode must be 'all' or 'any', got {self.entry_rules.mode!r}")
        if self.exit_rules.signals and self.exit_rules.mode not in ("all", "any"):
            raise ValueError(f"exit_rules.mode must be 'all' or 'any', got {self.exit_rules.mode!r}")
        if self.sl_atr_mult <= _ZERO:
            raise ValueError("sl_atr_mult must be positive")
        if self.tp_atr_mult <= _ZERO:
            raise ValueError("tp_atr_mult must be positive")
        if self.entry_order_type not in ("market", "limit"):
            raise ValueError(f"entry_order_type must be 'market' or 'limit', got {self.entry_order_type!r}")
        if self.entry_order_type == "limit" and self.limit_entry_offset_atr < _ZERO:
            raise ValueError("limit_entry_offset_atr must be >= 0 for limit entries")
        all_signals = list(self.entry_rules.signals) + list(self.exit_rules.signals)
        for sc in all_signals:
            if sc.signal_type not in SIGNAL_REGISTRY:
                raise ValueError(
                    f"Unknown signal type {sc.signal_type!r}. "
                    f"Available: {sorted(SIGNAL_REGISTRY.keys())}"
                )
            errs = validate_signal_params(sc.signal_type, sc.params)
            if errs:
                raise ValueError("; ".join(errs))

    def derived_warmup(self) -> int:
        """Compute minimum warmup bars from configured signals + ATR."""
        warmup = self.atr_period + 1
        all_signals = list(self.entry_rules.signals) + list(self.exit_rules.signals)
        for sc in all_signals:
            warmup = max(warmup, warmup_bars_for_signal(sc.signal_type, sc.params))
        return max(warmup, self.min_warmup_bars)


# ---------------------------------------------------------------------------
# Position state
# ---------------------------------------------------------------------------

@dataclass
class _PositionState:
    side: str = "off"
    entry_price: Decimal = _ZERO
    entry_ts: float = 0.0
    sl_price: Decimal = _ZERO
    tp_price: Decimal = _ZERO
    risk_dist: Decimal = _ZERO
    trail_active: bool = False
    trail_hwm: Decimal = _ZERO
    trail_lwm: Decimal = _ZERO


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class TaCompositeAdapter:
    """Config-driven TA adapter evaluating composable signal primitives."""

    def __init__(
        self,
        desk: PaperDesk,
        instrument_id: InstrumentId,
        instrument_spec: InstrumentSpec,
        config: TaCompositeConfig | None = None,
    ) -> None:
        self._desk = desk
        self._instrument_id = instrument_id
        self._instrument_spec = instrument_spec
        self._cfg = config or TaCompositeConfig()
        self._cfg.hydrate_nested()
        self._cfg.validate()
        self._buf = PriceBuffer()
        self._warmup_target = self._cfg.derived_warmup()
        self._pos = _PositionState()
        self._last_exit_ts: float = 0.0
        self._last_submitted_count: int = 0
        self._daily_equity_open: Decimal = _ZERO
        self._current_day: int = -1
        self._last_candle_ts: int = 0

    @property
    def last_submitted_count(self) -> int:
        return self._last_submitted_count

    def warmup(self, candles: list[CandleRow]) -> int:
        from controllers.price_buffer import MinuteBar
        for c in candles:
            self._buf.append_bar(MinuteBar(
                ts_minute=int(c.timestamp_ms // 1000 // 60) * 60,
                open=c.open, high=c.high,
                low=c.low, close=c.close,
            ))
        return len(candles)

    def tick(
        self,
        now_s: float,
        mid: Decimal,
        book: Any,
        equity_quote: Decimal,
        position_base: Decimal,
        candle: Any = None,
    ) -> dict[str, Any] | None:
        self._last_submitted_count = 0
        cfg = self._cfg

        if candle is not None and candle.timestamp_ms != self._last_candle_ts:
            from controllers.price_buffer import MinuteBar
            self._buf.append_bar(MinuteBar(
                ts_minute=int(candle.timestamp_ms // 1000 // 60) * 60,
                open=candle.open, high=candle.high,
                low=candle.low, close=candle.close,
            ))
            self._last_candle_ts = candle.timestamp_ms

        day = int(now_s // 86400)
        if day != self._current_day:
            self._current_day = day
            self._daily_equity_open = equity_quote

        if len(self._buf.bars) < self._warmup_target:
            return None
        if mid <= _ZERO or equity_quote <= _ZERO:
            return None

        has_position = abs(position_base) > Decimal("1e-8")

        if has_position and self._pos.side != "off":
            atr = self._buf.atr(cfg.atr_period)
            action = self._manage_position(mid, position_base, atr or _ZERO, now_s)
            if action:
                return action
            exit_signal = self._eval_exit_rules()
            if exit_signal is not None:
                self._close_position(mid, position_base, now_s)
                return {"side": "exit", "reason": "signal_exit", "signal_direction": exit_signal}

        if self._daily_equity_open > _ZERO:
            daily_loss = (self._daily_equity_open - equity_quote) / self._daily_equity_open
            if daily_loss > cfg.max_daily_loss_pct:
                return {"side": "off", "reason": "daily_risk_limit"}

        if has_position:
            return {"side": self._pos.side, "holding": True}

        if self._last_exit_ts > 0 and (now_s - self._last_exit_ts) < cfg.cooldown_s:
            return {"side": "off", "cooldown": True}

        entry_dir = self._eval_entry_rules()
        if entry_dir is None:
            return {"side": "off", "reason": "no_signal"}

        atr = self._buf.atr(cfg.atr_period)
        if atr is None or atr <= _ZERO:
            return {"side": "off", "reason": "zero_atr"}

        order_side = OrderSide.BUY if entry_dir == "long" else OrderSide.SELL
        quote_amount = equity_quote * cfg.risk_pct
        base_qty = quote_amount / mid
        quantity = self._instrument_spec.quantize_size(base_qty)
        if quantity <= _ZERO:
            return {"side": "off", "reason": "qty_zero"}

        if cfg.entry_order_type == "limit":
            offset = atr * cfg.limit_entry_offset_atr
            if entry_dir == "long":
                entry_price = self._instrument_spec.quantize_price(mid - offset, "buy")
            else:
                entry_price = self._instrument_spec.quantize_price(mid + offset, "sell")
            order_type = PaperOrderType.LIMIT
        else:
            entry_price = mid
            order_type = PaperOrderType.MARKET

        self._desk.submit_order(
            instrument_id=self._instrument_id,
            side=order_side,
            order_type=order_type,
            price=entry_price,
            quantity=quantity,
            source_bot="ta_composite",
        )
        self._last_submitted_count = 1

        sl_dist = atr * cfg.sl_atr_mult
        tp_dist = atr * cfg.tp_atr_mult
        side_str = "buy" if entry_dir == "long" else "sell"
        if entry_dir == "long":
            sl_price = mid - sl_dist
            tp_price = mid + tp_dist
        else:
            sl_price = mid + sl_dist
            tp_price = mid - tp_dist

        self._pos = _PositionState(
            side=side_str,
            entry_price=mid,
            entry_ts=now_s,
            sl_price=sl_price,
            tp_price=tp_price,
            risk_dist=sl_dist,
        )
        return {"side": side_str, "reason": "signal_entry", "direction": entry_dir}

    def record_fill_notional(self, notional: Decimal) -> None:
        pass

    # --- Rule evaluation ---

    def _eval_entry_rules(self) -> str | None:
        """Evaluate entry rules. Returns 'long', 'short', or None."""
        rules = self._cfg.entry_rules
        results: list[SignalResult] = []
        for sc in rules.signals:
            fn = SIGNAL_REGISTRY[sc.signal_type]
            result = fn(self._buf, **sc.params)
            if sc.invert:
                inv_dir = {"long": "short", "short": "long", "neutral": "neutral"}[result.direction]
                result = SignalResult(inv_dir, result.strength)  # type: ignore[arg-type]
            results.append(result)

        non_neutral = [r for r in results if r.direction != "neutral"]
        if not non_neutral:
            return None

        if rules.mode == "all":
            if len(non_neutral) != len(results):
                return None
            dirs = {r.direction for r in non_neutral}
            if len(dirs) != 1:
                return None
            return dirs.pop()
        else:
            dirs = {r.direction for r in non_neutral}
            if len(dirs) != 1:
                return None
            return dirs.pop()

    def _eval_exit_rules(self) -> str | None:
        """Evaluate exit rules against current position, respecting mode."""
        rules = self._cfg.exit_rules
        if not rules.signals:
            return None
        pos_side = self._pos.side
        if pos_side == "off":
            return None
        exit_dir = "short" if pos_side == "buy" else "long"

        matches = 0
        for sc in rules.signals:
            fn = SIGNAL_REGISTRY[sc.signal_type]
            result = fn(self._buf, **sc.params)
            if sc.invert:
                inv_dir = {"long": "short", "short": "long", "neutral": "neutral"}[result.direction]
                result = SignalResult(inv_dir, result.strength)  # type: ignore[arg-type]
            if result.direction == exit_dir:
                if rules.mode == "any":
                    return exit_dir
                matches += 1
        if rules.mode == "all" and matches == len(rules.signals):
            return exit_dir
        return None

    # --- Position management (mirrors momentum_scalper) ---

    def _manage_position(
        self,
        mid: Decimal,
        position_base: Decimal,
        atr: Decimal,
        now_s: float,
    ) -> dict | None:
        pos = self._pos
        cfg = self._cfg

        if pos.entry_price <= _ZERO:
            return None

        hit_sl = (
            (pos.side == "buy" and mid <= pos.sl_price)
            or (pos.side == "sell" and mid >= pos.sl_price)
        )
        if hit_sl:
            self._close_position(mid, position_base, now_s)
            return {"side": "exit", "reason": "stop_loss"}

        hit_tp = (
            (pos.side == "buy" and mid >= pos.tp_price)
            or (pos.side == "sell" and mid <= pos.tp_price)
        )
        if hit_tp:
            self._close_position(mid, position_base, now_s)
            return {"side": "exit", "reason": "take_profit"}

        hold_min = (now_s - pos.entry_ts) / 60
        if hold_min > cfg.max_hold_minutes:
            self._close_position(mid, position_base, now_s)
            return {"side": "exit", "reason": "max_hold"}

        if pos.risk_dist > _ZERO:
            if pos.side == "buy":
                r_mult = (mid - pos.entry_price) / pos.risk_dist
            else:
                r_mult = (pos.entry_price - mid) / pos.risk_dist
        else:
            r_mult = _ZERO

        if not pos.trail_active and r_mult >= cfg.trail_activate_r:
            pos.trail_active = True
            if pos.side == "buy":
                pos.trail_hwm = mid
            else:
                pos.trail_lwm = mid

        if pos.trail_active:
            trail_dist = atr * cfg.trail_offset_atr
            if pos.side == "buy":
                if mid > pos.trail_hwm:
                    pos.trail_hwm = mid
                trail_stop = pos.trail_hwm - trail_dist
                if mid <= trail_stop:
                    self._close_position(mid, position_base, now_s)
                    return {"side": "exit", "reason": "trail_stop"}
            else:
                if mid < pos.trail_lwm:
                    pos.trail_lwm = mid
                trail_stop = pos.trail_lwm + trail_dist
                if mid >= trail_stop:
                    self._close_position(mid, position_base, now_s)
                    return {"side": "exit", "reason": "trail_stop"}
        return None

    def _cancel_all(self) -> None:
        try:
            self._desk.cancel_all(self._instrument_id)
        except Exception:  # cancel_all may raise if no orders exist; safe to ignore
            pass

    def _close_position(self, mid: Decimal, position_base: Decimal, now_s: float) -> None:
        close_qty = abs(position_base)
        if close_qty <= _ZERO:
            self._pos = _PositionState()
            return
        self._cancel_all()
        close_side = OrderSide.SELL if position_base > _ZERO else OrderSide.BUY
        qty = self._instrument_spec.quantize_size(close_qty)
        if qty > _ZERO:
            self._desk.submit_order(
                instrument_id=self._instrument_id,
                side=close_side,
                order_type=PaperOrderType.MARKET,
                price=mid,
                quantity=qty,
                source_bot="ta_composite_exit",
            )
        self._last_exit_ts = now_s
        self._pos = _PositionState()
