"""Portfolio management for Paper Engine v2.

Implements:
- MultiAssetLedger: balance tracking with reserve/release
- RiskGuard: pre-trade checks (position size, drawdown, exposure)
- PaperPortfolio: desk-level financial state shared across all bots

Key accounting rules (Nautilus-aligned):
- realized_pnl is PURE price PnL only — fees never subtracted
- Fee tracked separately in position.total_fees_paid
- Spot: full notional reserve; Perp: margin-only reserve
- Available balance clamped to zero (graceful degradation on transient over-margin)

Position accounting is delegated to the standalone `accounting.py` core
(Nautilus-inspired) so that the pure math is independently testable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from controllers.paper_engine_v2.accounting import (
    PositionState,
    apply_fill as _apply_fill,
    unrealized_pnl as _unrealized_pnl,
)
from controllers.paper_engine_v2.risk_engine import (
    MarginLevel,
    RiskConfig,
    RiskEngine,
    LiquidationAction,
)
from controllers.paper_engine_v2.types import (
    FundingApplied,
    InstrumentId,
    InstrumentSpec,
    OrderSide,
    PaperOrder,
    PaperPosition,
    PositionAction,
    PositionChanged,
    _EPS,
    _ONE,
    _ZERO,
    _uuid,
)

logger = logging.getLogger(__name__)


def _is_open_action(position_action: PositionAction) -> bool:
    return position_action in {PositionAction.OPEN_LONG, PositionAction.OPEN_SHORT}


def _is_close_action(position_action: PositionAction) -> bool:
    return position_action in {PositionAction.CLOSE_LONG, PositionAction.CLOSE_SHORT}


def _is_hedge_mode(position_mode: str) -> bool:
    return "HEDGE" in str(position_mode or "").upper()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class PortfolioConfig:
    max_position_notional_per_instrument: Decimal = Decimal("10000")
    max_net_exposure_quote: Decimal = Decimal("50000")
    max_drawdown_pct_hard: Decimal = Decimal("0.10")
    default_leverage: int = 1
    leverage_max: int = 20
    margin_ratio_warn_pct: Decimal = Decimal("0.20")
    margin_ratio_critical_pct: Decimal = Decimal("0.10")
    margin_model_type: str = "leveraged"  # "leveraged"|"standard"


# ---------------------------------------------------------------------------
# MultiAssetLedger
# ---------------------------------------------------------------------------

class MultiAssetLedger:
    """Tracks balances and reserves across all assets.

    Available balance clamped to zero (Nautilus graceful degradation):
    if margin temporarily exceeds total, free = 0, not negative.
    """

    def __init__(self, initial_balances: Dict[str, Decimal]):
        self._balances: Dict[str, Decimal] = {k: v for k, v in initial_balances.items()}
        self._reserved: Dict[str, Decimal] = {}

    def total(self, asset: str) -> Decimal:
        return self._balances.get(asset, _ZERO)

    def available(self, asset: str) -> Decimal:
        """Available = total - reserved, clamped to 0."""
        raw = self.total(asset) - self._reserved.get(asset, _ZERO)
        return max(_ZERO, raw)

    def can_reserve(self, asset: str, amount: Decimal) -> bool:
        return self.available(asset) + _EPS >= amount

    def reserve(self, asset: str, amount: Decimal) -> None:
        amount = max(_ZERO, amount)
        self._reserved[asset] = self._reserved.get(asset, _ZERO) + amount

    def release(self, asset: str, amount: Decimal) -> None:
        amount = max(_ZERO, amount)
        curr = self._reserved.get(asset, _ZERO)
        self._reserved[asset] = max(_ZERO, curr - amount)

    def credit(self, asset: str, amount: Decimal) -> None:
        amount = max(_ZERO, amount)
        self._balances[asset] = self.total(asset) + amount

    def debit(self, asset: str, amount: Decimal) -> None:
        amount = max(_ZERO, amount)
        self._balances[asset] = self.total(asset) - amount

    def to_dict(self) -> Dict[str, str]:
        return {k: str(v) for k, v in self._balances.items()}

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> "MultiAssetLedger":
        return cls({k: Decimal(v) for k, v in d.items()})


# ---------------------------------------------------------------------------
# RiskGuard
# ---------------------------------------------------------------------------

class RiskGuard:
    """Pre-trade risk checks. Returns rejection reason or None if clear."""

    def __init__(self, config: PortfolioConfig, portfolio: "PaperPortfolio"):
        self._cfg = config
        self._portfolio = portfolio

    def check_order(
        self,
        order: PaperOrder,
        spec: InstrumentSpec,
        mid_price: Optional[Decimal],
    ) -> Optional[str]:
        if mid_price is None or mid_price <= _ZERO:
            mid_price = order.price

        # Drawdown hard stop
        if self._portfolio.drawdown_pct() > self._cfg.max_drawdown_pct_hard:
            # Safety valve: allow strictly risk-reducing market orders so the desk
            # can de-risk out of stressed states instead of deadlocking itself.
            if self._is_drawdown_reducing_market_order(order, spec):
                return None
            return "drawdown_hard_stop"

        # Position notional cap
        pos = self._portfolio.get_position(spec.instrument_id)
        action = getattr(order, "position_action", PositionAction.AUTO)
        if not isinstance(action, PositionAction):
            try:
                action = PositionAction(str(action or "auto").lower())
            except Exception:
                action = PositionAction.AUTO
        current_abs = pos.gross_quantity if getattr(pos, "has_hedge_legs", False) else pos.abs_quantity
        if action == PositionAction.CLOSE_LONG:
            projected_abs = max(_ZERO, current_abs - min(order.quantity, pos.long_quantity))
        elif action == PositionAction.CLOSE_SHORT:
            projected_abs = max(_ZERO, current_abs - min(order.quantity, pos.short_quantity))
        else:
            projected_abs = current_abs + order.quantity
        new_notional = projected_abs * mid_price
        if new_notional > self._cfg.max_position_notional_per_instrument:
            return (
                f"position_notional_cap: {new_notional:.2f} > "
                f"{self._cfg.max_position_notional_per_instrument}"
            )

        # Net exposure cap
        net_exp = self._portfolio.net_exposure_quote({spec.instrument_id.key: mid_price})
        order_exp = order.quantity * mid_price
        if (abs(net_exp) + order_exp) > self._cfg.max_net_exposure_quote:
            return (
                f"net_exposure_cap: {abs(net_exp) + order_exp:.2f} > "
                f"{self._cfg.max_net_exposure_quote}"
            )

        return None

    def _is_drawdown_reducing_market_order(self, order: PaperOrder, spec: InstrumentSpec) -> bool:
        order_type_text = str(getattr(getattr(order, "order_type", None), "value", "")).lower()
        if order_type_text != "market":
            return False
        pos = self._portfolio.get_position(spec.instrument_id)
        qty = pos.quantity if pos is not None else _ZERO
        action = getattr(order, "position_action", PositionAction.AUTO)
        if not isinstance(action, PositionAction):
            try:
                action = PositionAction(str(action or "auto").lower())
            except Exception:
                action = PositionAction.AUTO
        if action == PositionAction.CLOSE_LONG:
            return order.side == OrderSide.SELL and order.quantity <= pos.long_quantity + _EPS
        if action == PositionAction.CLOSE_SHORT:
            return order.side == OrderSide.BUY and order.quantity <= pos.short_quantity + _EPS
        if qty >= _ZERO and order.side == OrderSide.BUY:
            return False
        if qty <= _ZERO and order.side == OrderSide.SELL:
            return False
        # Strictly reducing only: do not allow flipping through zero.
        if qty > _ZERO and order.side == OrderSide.SELL:
            return order.quantity <= qty + _EPS
        if qty < _ZERO and order.side == OrderSide.BUY:
            return order.quantity <= abs(qty) + _EPS
        return False


# ---------------------------------------------------------------------------
# PaperPortfolio
# ---------------------------------------------------------------------------

class PaperPortfolio:
    """Desk-level financial state shared across all bots and instruments.

    Settlement accounting (Nautilus-aligned):
    - realized_pnl = pure price PnL only (no fees)
    - fees debited from ledger separately
    - spot: full notional exchange; perp: margin-only reserve
    """

    def __init__(
        self,
        initial_balances: Dict[str, Decimal],
        config: PortfolioConfig,
    ):
        self._ledger = MultiAssetLedger(initial_balances)
        self._positions: Dict[str, PaperPosition] = {}
        # Per-instrument metadata for margin and mark-to-market.
        # Stored opportunistically on fills / mtm ticks so PaperPortfolio can
        # compute maintenance margin without holding a hard dependency on the
        # desk/engine registry.
        self._spec_by_key: Dict[str, InstrumentSpec] = {}
        self._leverage_by_key: Dict[str, int] = {}
        self._position_margin_reserved: Dict[str, Decimal] = {}  # key -> reserved quote
        self._peak_equity: Decimal = _ZERO
        self._daily_open_equity: Optional[Decimal] = None
        self._daily_open_day_key: Optional[str] = None
        self.risk_guard = RiskGuard(config, self)
        self._config = config
        # Promoted risk engine (parallel to legacy RiskGuard; gradually replaces it).
        self._risk_engine = RiskEngine(RiskConfig(
            max_drawdown_pct_hard=config.max_drawdown_pct_hard,
            max_position_notional_per_instrument=config.max_position_notional_per_instrument,
            max_net_exposure_quote=config.max_net_exposure_quote,
            margin_ratio_warn=Decimal("3.0"),
            margin_ratio_critical=Decimal("1.5"),
            margin_ratio_liquidate=Decimal("1.1"),
        ))
        self._last_margin_level: MarginLevel = MarginLevel.SAFE

    @property
    def peak_equity(self) -> Decimal:
        return self._peak_equity

    @property
    def daily_open_equity(self) -> Optional[Decimal]:
        return self._daily_open_equity

    @staticmethod
    def _utc_day_key(now_ns: Optional[int] = None) -> str:
        if now_ns is None:
            return datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return datetime.fromtimestamp(float(now_ns) / 1e9, tz=timezone.utc).strftime("%Y-%m-%d")

    def _refresh_daily_open_baseline(self, equity_quote: Decimal, now_ns: Optional[int] = None) -> None:
        """Keep daily_open_equity aligned to UTC day boundaries."""
        if equity_quote <= _ZERO:
            return
        day_key = self._utc_day_key(now_ns)
        if self._daily_open_day_key is None:
            self._daily_open_day_key = day_key
        if self._daily_open_day_key != day_key:
            logger.info(
                "PaperPortfolio day rollover: %s -> %s (daily_open_equity=%s -> %s)",
                self._daily_open_day_key,
                day_key,
                self._daily_open_equity,
                equity_quote,
            )
            self._daily_open_day_key = day_key
            self._daily_open_equity = equity_quote
            return
        if self._daily_open_equity is None:
            self._daily_open_equity = equity_quote

    @staticmethod
    def _collapse_oneway_legs(pos: PaperPosition) -> None:
        """Enforce netted semantics for non-hedge position modes.

        Some upstream order flows can still attach explicit open/close leg hints
        even when the connector runs in one-way mode. In one-way, opposite-side
        fills must net the position, not accumulate synthetic long+short hedge
        legs. Collapse any dual-leg state back to a single net leg.
        """
        if _is_hedge_mode(getattr(pos, "position_mode", "ONEWAY")):
            return
        pos.ensure_leg_consistency()
        pos.long_quantity = max(_ZERO, pos.long_quantity)
        pos.short_quantity = max(_ZERO, pos.short_quantity)
        net_qty = pos.long_quantity - pos.short_quantity
        net_realized = pos.long_realized_pnl + pos.short_realized_pnl
        net_unrealized = pos.long_unrealized_pnl + pos.short_unrealized_pnl
        net_funding = pos.long_funding_paid + pos.short_funding_paid
        if net_qty > _EPS:
            pos.long_quantity = net_qty
            if pos.long_avg_entry_price <= _ZERO:
                pos.long_avg_entry_price = max(_ZERO, pos.avg_entry_price)
            pos.long_realized_pnl = net_realized
            pos.long_unrealized_pnl = net_unrealized
            pos.long_funding_paid = net_funding
            if pos.long_opened_at_ns <= 0:
                pos.long_opened_at_ns = pos.opened_at_ns
            pos.short_quantity = _ZERO
            pos.short_avg_entry_price = _ZERO
            pos.short_realized_pnl = _ZERO
            pos.short_unrealized_pnl = _ZERO
            pos.short_funding_paid = _ZERO
            pos.short_opened_at_ns = 0
        elif net_qty < -_EPS:
            pos.short_quantity = abs(net_qty)
            if pos.short_avg_entry_price <= _ZERO:
                pos.short_avg_entry_price = max(_ZERO, pos.avg_entry_price)
            pos.short_realized_pnl = net_realized
            pos.short_unrealized_pnl = net_unrealized
            pos.short_funding_paid = net_funding
            if pos.short_opened_at_ns <= 0:
                pos.short_opened_at_ns = pos.opened_at_ns
            pos.long_quantity = _ZERO
            pos.long_avg_entry_price = _ZERO
            pos.long_realized_pnl = _ZERO
            pos.long_unrealized_pnl = _ZERO
            pos.long_funding_paid = _ZERO
            pos.long_opened_at_ns = 0
        else:
            pos.long_quantity = _ZERO
            pos.short_quantity = _ZERO
            pos.long_avg_entry_price = _ZERO
            pos.short_avg_entry_price = _ZERO
            # Keep aggregate realized/funding totals on the legacy net fields.
            pos.long_realized_pnl = net_realized
            pos.short_realized_pnl = _ZERO
            pos.long_unrealized_pnl = _ZERO
            pos.short_unrealized_pnl = _ZERO
            pos.long_funding_paid = net_funding
            pos.short_funding_paid = _ZERO
            pos.long_opened_at_ns = 0
            pos.short_opened_at_ns = 0
        pos.sync_derived_fields()

    # -- Balance -----------------------------------------------------------

    def can_reserve(self, asset: str, amount: Decimal) -> bool:
        return self._ledger.can_reserve(asset, amount)

    def reserve(self, asset: str, amount: Decimal) -> None:
        self._ledger.reserve(asset, amount)

    def release(self, asset: str, amount: Decimal) -> None:
        self._ledger.release(asset, amount)

    def balance(self, asset: str) -> Decimal:
        return self._ledger.total(asset)

    def available(self, asset: str) -> Decimal:
        return self._ledger.available(asset)

    def equity_quote(
        self,
        mark_prices: Optional[Dict[str, Decimal]] = None,
        quote_asset: str = "USDT",
    ) -> Decimal:
        """Total equity: cash + unrealized position value in quote."""
        equity = self._ledger.total(quote_asset)
        if mark_prices:
            for pos in self._positions.values():
                price = mark_prices.get(pos.instrument_id.key)
                if price and price > _ZERO and pos.quantity != _ZERO:
                    if pos.instrument_id.instrument_type == "spot":
                        equity += pos.abs_quantity * price
                    else:
                        equity += pos.unrealized_pnl
        return equity

    # -- Positions ---------------------------------------------------------

    def get_position(
        self,
        instrument_id: InstrumentId,
        position_action: Optional[PositionAction] = None,
    ) -> PaperPosition:
        pos = self._positions.get(instrument_id.key)
        if pos is None:
            return PaperPosition.flat(instrument_id)
        pos.ensure_leg_consistency()
        PaperPortfolio._collapse_oneway_legs(pos)
        pos.sync_derived_fields()
        if position_action is None:
            return pos
        if not _is_hedge_mode(pos.position_mode):
            return pos
        if not isinstance(position_action, PositionAction):
            try:
                position_action = PositionAction(str(position_action or "auto").lower())
            except Exception:
                position_action = PositionAction.AUTO
        if position_action in {PositionAction.OPEN_LONG, PositionAction.CLOSE_LONG}:
            return PaperPosition(
                instrument_id=instrument_id,
                quantity=pos.long_quantity,
                avg_entry_price=pos.long_avg_entry_price,
                realized_pnl=pos.long_realized_pnl,
                unrealized_pnl=pos.long_unrealized_pnl,
                total_fees_paid=pos.total_fees_paid,
                funding_paid=pos.long_funding_paid,
                opened_at_ns=pos.long_opened_at_ns,
                last_fill_at_ns=pos.last_fill_at_ns,
                position_mode=pos.position_mode,
                long_quantity=pos.long_quantity,
                long_avg_entry_price=pos.long_avg_entry_price,
                long_realized_pnl=pos.long_realized_pnl,
                long_unrealized_pnl=pos.long_unrealized_pnl,
                long_funding_paid=pos.long_funding_paid,
                long_opened_at_ns=pos.long_opened_at_ns,
            )
        if position_action in {PositionAction.OPEN_SHORT, PositionAction.CLOSE_SHORT}:
            return PaperPosition(
                instrument_id=instrument_id,
                quantity=-pos.short_quantity,
                avg_entry_price=pos.short_avg_entry_price,
                realized_pnl=pos.short_realized_pnl,
                unrealized_pnl=pos.short_unrealized_pnl,
                total_fees_paid=pos.total_fees_paid,
                funding_paid=pos.short_funding_paid,
                opened_at_ns=pos.short_opened_at_ns,
                last_fill_at_ns=pos.last_fill_at_ns,
                position_mode=pos.position_mode,
                short_quantity=pos.short_quantity,
                short_avg_entry_price=pos.short_avg_entry_price,
                short_realized_pnl=pos.short_realized_pnl,
                short_unrealized_pnl=pos.short_unrealized_pnl,
                short_funding_paid=pos.short_funding_paid,
                short_opened_at_ns=pos.short_opened_at_ns,
            )
        return pos

    def all_positions(self) -> Dict[str, PaperPosition]:
        out: Dict[str, PaperPosition] = {}
        for key, pos in self._positions.items():
            pos.ensure_leg_consistency()
            PaperPortfolio._collapse_oneway_legs(pos)
            pos.sync_derived_fields()
            out[key] = pos
        return out

    def mark_to_market(self, prices: Dict[str, Decimal]) -> None:
        """Update unrealized PnL on all positions, and refresh maintenance margin reserves."""
        for key, pos in self._positions.items():
            price = prices.get(key)
            pos.ensure_leg_consistency()
            PaperPortfolio._collapse_oneway_legs(pos)
            if price is None or price <= _ZERO or (pos.quantity == _ZERO and pos.gross_quantity <= _ZERO):
                pos.unrealized_pnl = _ZERO
                pos.long_unrealized_pnl = _ZERO
                pos.short_unrealized_pnl = _ZERO
                continue
            pos.long_unrealized_pnl = _unrealized_pnl(pos.long_quantity, pos.long_avg_entry_price, price)
            pos.short_unrealized_pnl = _unrealized_pnl(-pos.short_quantity, pos.short_avg_entry_price, price)
            pos.sync_derived_fields()
        self._refresh_position_margin_reserves(prices)
        eq = self.equity_quote(prices)
        if eq > self._peak_equity:
            self._peak_equity = eq
        self._refresh_daily_open_baseline(eq)

    def _refresh_position_margin_reserves(self, prices: Dict[str, Decimal]) -> None:
        """Reserve/release maintenance margin for perp positions (Nautilus-style).

        Order reserves are handled by the matching engine. This reserve bucket
        models locked *position* margin so available quote balance is realistic
        while positions are open.
        """
        for key, pos in self._positions.items():
            pos.ensure_leg_consistency()
            if not pos.instrument_id.is_perp or pos.gross_quantity == _ZERO:
                self._set_position_margin_reserved(key, _ZERO, pos.instrument_id.quote_asset)
                continue
            spec = self._spec_by_key.get(key)
            lev = int(self._leverage_by_key.get(key, 1) or 1)
            if self._config.margin_model_type.lower() != "leveraged":
                lev = 1
            px = prices.get(key)
            if spec is None or px is None or px <= _ZERO:
                # If we can't price the position, keep prior reserve to avoid
                # oscillation. (Availability will still clamp to zero safely.)
                continue
            target = spec.compute_margin_maint(pos.gross_quantity, px, lev)
            self._set_position_margin_reserved(key, target, pos.instrument_id.quote_asset)

    def _set_position_margin_reserved(self, key: str, target: Decimal, quote_asset: str) -> None:
        target = max(_ZERO, target)
        current = self._position_margin_reserved.get(key, _ZERO)
        if target == current:
            return
        if target > current:
            self._ledger.reserve(quote_asset, target - current)
        else:
            self._ledger.release(quote_asset, current - target)
        if target <= _ZERO:
            self._position_margin_reserved.pop(key, None)
        else:
            self._position_margin_reserved[key] = target

    def maintenance_margin_quote(self) -> Decimal:
        """Total maintenance margin reserved across all perps (quote currency)."""
        return sum(self._position_margin_reserved.values(), _ZERO)

    def margin_ratio(self, prices: Optional[Dict[str, Decimal]] = None) -> Decimal:
        """Equity / maintenance_margin (higher is safer)."""
        eq = self.equity_quote(prices) if prices else self.equity_quote()
        mm = self.maintenance_margin_quote()
        if mm <= _ZERO:
            return Decimal("999")
        if eq <= _ZERO:
            return _ZERO
        return eq / mm

    def apply_funding(
        self, instrument_id: InstrumentId, charge: Decimal, now_ns: int, leg_side: Optional[str] = None
    ) -> FundingApplied:
        """Apply signed funding transfer and record on position.

        Positive charge debits quote (paid funding).
        Negative charge credits quote (funding received).
        """
        pos = self._positions.get(instrument_id.key)
        notional = _ZERO
        if pos is not None:
            pos.ensure_leg_consistency()
            leg = str(leg_side or "").strip().lower()
            if leg == "long":
                pos.long_funding_paid += charge
                notional = pos.long_quantity * pos.long_avg_entry_price
            elif leg == "short":
                pos.short_funding_paid += charge
                notional = pos.short_quantity * pos.short_avg_entry_price
            else:
                pos.funding_paid += charge
                notional = pos.abs_quantity * pos.avg_entry_price
                if pos.quantity > _ZERO:
                    pos.long_funding_paid = pos.funding_paid
                    pos.short_funding_paid = _ZERO
                elif pos.quantity < _ZERO:
                    pos.short_funding_paid = pos.funding_paid
                    pos.long_funding_paid = _ZERO
                else:
                    pos.long_funding_paid = _ZERO
                    pos.short_funding_paid = _ZERO
            pos.sync_derived_fields()
        if charge >= _ZERO:
            self._ledger.debit(instrument_id.quote_asset, charge)
        else:
            self._ledger.credit(instrument_id.quote_asset, abs(charge))
        eq = self.equity_quote()
        if eq > self._peak_equity:
            self._peak_equity = eq
        self._refresh_daily_open_baseline(eq, now_ns=now_ns)
        return FundingApplied(
            event_id=_uuid(), timestamp_ns=now_ns,
            instrument_id=instrument_id,
            funding_rate=_ZERO,  # caller can enrich
            charge_quote=charge,
            position_notional=notional,
        )

    # -- Settlement (core accounting) --------------------------------------

    def settle_fill(
        self,
        instrument_id: InstrumentId,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
        source_bot: str,
        now_ns: int,
        spec: InstrumentSpec,
        leverage: int,
        position_action: PositionAction = PositionAction.AUTO,
        position_mode: str = "ONEWAY",
    ) -> PositionChanged:
        """Settle a fill: update position and ledger.

        Delegates position math to `accounting.apply_fill()` (Nautilus-inspired
        deterministic accounting core). Ledger settlement (cash/margin flows)
        and event emission remain here.

        Realized PnL = pure price PnL only.
        Fees debited separately (Nautilus convention).
        """
        pos = self._positions.get(instrument_id.key, PaperPosition.flat(instrument_id))
        pos.ensure_leg_consistency()
        pos.position_mode = str(position_mode or pos.position_mode or "ONEWAY").upper()
        PaperPortfolio._collapse_oneway_legs(pos)

        # Cache per-instrument metadata for later mtm/margin refresh.
        self._spec_by_key[instrument_id.key] = spec
        self._leverage_by_key[instrument_id.key] = max(1, int(leverage))

        # ---- Pure accounting via dedicated core ----
        if not isinstance(position_action, PositionAction):
            try:
                position_action = PositionAction(str(position_action or "auto").lower())
            except Exception:
                position_action = PositionAction.AUTO
        if not _is_hedge_mode(pos.position_mode) and (_is_open_action(position_action) or _is_close_action(position_action)):
            # One-way perps/spot should net by signed quantity regardless of
            # upstream leg hints.
            position_action = PositionAction.AUTO
        if position_action in {
            PositionAction.OPEN_LONG,
            PositionAction.CLOSE_LONG,
            PositionAction.OPEN_SHORT,
            PositionAction.CLOSE_SHORT,
        }:
            leg_side = "long" if position_action in {PositionAction.OPEN_LONG, PositionAction.CLOSE_LONG} else "short"
            leg_quantity = pos.long_quantity if leg_side == "long" else -pos.short_quantity
            leg_avg_entry = pos.long_avg_entry_price if leg_side == "long" else pos.short_avg_entry_price
            leg_realized = pos.long_realized_pnl if leg_side == "long" else pos.short_realized_pnl
            leg_opened_at = pos.long_opened_at_ns if leg_side == "long" else pos.short_opened_at_ns
            old_state = PositionState(
                quantity=leg_quantity,
                avg_entry_price=leg_avg_entry,
                realized_pnl=leg_realized,
                opened_at_ns=leg_opened_at,
            )
            result = _apply_fill(
                old=old_state,
                fill_side=side.value,
                fill_qty=quantity,
                fill_price=price,
                now_ns=now_ns,
            )
            new_state = result.new_state
            realized_pnl = result.fill_realized_pnl
            is_closing = result.is_closing
            if leg_side == "long":
                pos.long_quantity = max(_ZERO, new_state.quantity)
                pos.long_avg_entry_price = new_state.avg_entry_price if pos.long_quantity > _ZERO else _ZERO
                pos.long_realized_pnl = new_state.realized_pnl
                pos.long_opened_at_ns = new_state.opened_at_ns
            else:
                pos.short_quantity = max(_ZERO, abs(new_state.quantity))
                pos.short_avg_entry_price = new_state.avg_entry_price if pos.short_quantity > _ZERO else _ZERO
                pos.short_realized_pnl = new_state.realized_pnl
                pos.short_opened_at_ns = new_state.opened_at_ns
            pos.sync_derived_fields()
        else:
            old_state = PositionState(
                quantity=pos.quantity,
                avg_entry_price=pos.avg_entry_price,
                realized_pnl=pos.realized_pnl,
                opened_at_ns=pos.opened_at_ns,
            )
            result = _apply_fill(
                old=old_state,
                fill_side=side.value,
                fill_qty=quantity,
                fill_price=price,
                now_ns=now_ns,
            )
            new_state = result.new_state
            realized_pnl = result.fill_realized_pnl
            is_closing = result.is_closing
            pos.quantity = new_state.quantity
            pos.avg_entry_price = new_state.avg_entry_price
            pos.realized_pnl = new_state.realized_pnl
            pos.opened_at_ns = new_state.opened_at_ns
            if pos.quantity > _ZERO:
                pos.long_quantity = pos.quantity
                pos.long_avg_entry_price = pos.avg_entry_price
                pos.long_realized_pnl = pos.realized_pnl
                pos.long_unrealized_pnl = pos.unrealized_pnl
                pos.long_funding_paid = pos.funding_paid
                pos.long_opened_at_ns = pos.opened_at_ns
                pos.short_quantity = _ZERO
                pos.short_avg_entry_price = _ZERO
                pos.short_realized_pnl = _ZERO
                pos.short_unrealized_pnl = _ZERO
                pos.short_funding_paid = _ZERO
                pos.short_opened_at_ns = 0
            elif pos.quantity < _ZERO:
                pos.short_quantity = abs(pos.quantity)
                pos.short_avg_entry_price = pos.avg_entry_price
                pos.short_realized_pnl = pos.realized_pnl
                pos.short_unrealized_pnl = pos.unrealized_pnl
                pos.short_funding_paid = pos.funding_paid
                pos.short_opened_at_ns = pos.opened_at_ns
                pos.long_quantity = _ZERO
                pos.long_avg_entry_price = _ZERO
                pos.long_realized_pnl = _ZERO
                pos.long_unrealized_pnl = _ZERO
                pos.long_funding_paid = _ZERO
                pos.long_opened_at_ns = 0
            else:
                pos.long_quantity = _ZERO
                pos.long_avg_entry_price = _ZERO
                pos.long_realized_pnl = pos.realized_pnl
                pos.long_unrealized_pnl = _ZERO
                pos.long_funding_paid = pos.funding_paid
                pos.long_opened_at_ns = 0
                pos.short_quantity = _ZERO
                pos.short_avg_entry_price = _ZERO
                pos.short_realized_pnl = _ZERO
                pos.short_unrealized_pnl = _ZERO
                pos.short_funding_paid = _ZERO
                pos.short_opened_at_ns = 0
        pos.total_fees_paid += fee           # fees separate from PnL (Nautilus)
        pos.last_fill_at_ns = now_ns

        # ---- Ledger settlement (cash/margin flows) ----
        self._settle_ledger(
            instrument_id, side, quantity, price, fee,
            spec, leverage, realized_pnl, is_closing,
        )

        # Update peak equity tracking
        eq = self.equity_quote()
        if eq > self._peak_equity:
            self._peak_equity = eq
        self._refresh_daily_open_baseline(eq, now_ns=now_ns)

        self._positions[instrument_id.key] = pos

        # Refresh maintenance margin reserve using fill price as a best-effort mark.
        try:
            self._refresh_position_margin_reserves({instrument_id.key: price})
        except Exception:
            pass

        return PositionChanged(
            event_id=_uuid(), timestamp_ns=now_ns,
            instrument_id=instrument_id,
            position=pos,
            trigger_order_id="",
            trigger_side=side.value,
            fill_price=price,
            fill_quantity=quantity,
            realized_pnl=realized_pnl,
            position_action=position_action.value,
        )

    def _settle_ledger(
        self,
        instrument_id: InstrumentId,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
        spec: InstrumentSpec,
        leverage: int,
        realized_pnl: Decimal,
        is_closing: bool,
    ) -> None:
        quote = instrument_id.quote_asset
        base = instrument_id.base_asset

        if instrument_id.is_perp:
            # Perp: margin-based reserve. Fee always from quote.
            self._ledger.debit(quote, fee)
            if is_closing:
                # Return or deduct realized PnL
                if realized_pnl > _ZERO:
                    self._ledger.credit(quote, realized_pnl)
                elif realized_pnl < _ZERO:
                    self._ledger.debit(quote, abs(realized_pnl))
        else:
            # Spot: full notional exchange
            if side == OrderSide.BUY:
                self._ledger.debit(quote, quantity * price + fee)
                self._ledger.credit(base, quantity)
            else:
                self._ledger.debit(base, quantity)
                self._ledger.credit(quote, quantity * price - fee)

    # -- Risk metrics -------------------------------------------------------

    def net_exposure_quote(self, prices: Dict[str, Decimal]) -> Decimal:
        """Net signed exposure across all instruments in quote."""
        exposure = _ZERO
        for key, pos in self._positions.items():
            price = prices.get(key, pos.avg_entry_price)
            exposure += pos.quantity * price
        return exposure

    def drawdown_pct(self) -> Decimal:
        """Current drawdown from peak equity."""
        eq = self.equity_quote()
        if self._peak_equity <= _ZERO or eq >= self._peak_equity:
            return _ZERO
        return (self._peak_equity - eq) / self._peak_equity

    # -- Risk Engine (promoted) -------------------------------------------

    @property
    def margin_level(self) -> MarginLevel:
        """Current margin level (assessed at last mark-to-market or fill)."""
        return self._last_margin_level

    def evaluate_risk(
        self, prices: Optional[Dict[str, Decimal]] = None
    ) -> "tuple[MarginLevel, list[LiquidationAction]]":
        """Evaluate portfolio-level risk via the promoted RiskEngine.

        Returns (MarginLevel, [LiquidationAction]) where liquidation
        actions are advisory — the desk should execute them as forced orders.
        """
        eq = self.equity_quote(prices)
        mm = self.maintenance_margin_quote()
        # Build position snapshot for the risk engine.
        positions = {
            key: (pos.quantity, pos.instrument_id)
            for key, pos in self._positions.items()
            if pos.quantity != _ZERO
        }
        level, actions = self._risk_engine.evaluate(eq, mm, positions)
        self._last_margin_level = level
        return level, actions

    def risk_reasons(self, prices: Optional[Dict[str, Decimal]] = None) -> str:
        """Return ops-compatible risk reason string for current margin level."""
        level, _ = self.evaluate_risk(prices)
        return self._risk_engine.margin_level_to_risk_reason(level)

    # -- Persistence -------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        return {
            "balances": self._ledger.to_dict(),
            "positions": {k: v.to_dict() for k, v in self._positions.items()},
            "peak_equity": str(self._peak_equity),
            "daily_open_equity": str(self._daily_open_equity) if self._daily_open_equity else None,
            "daily_open_day_key": self._daily_open_day_key,
            "leverage_by_key": {k: int(v) for k, v in self._leverage_by_key.items()},
            "position_margin_reserved": {k: str(v) for k, v in self._position_margin_reserved.items()},
        }

    def restore_from_snapshot(self, data: Dict[str, Any]) -> None:
        if "balances" in data:
            self._ledger = MultiAssetLedger.from_dict(data["balances"])
        if "peak_equity" in data and data["peak_equity"]:
            self._peak_equity = Decimal(data["peak_equity"])
        if "daily_open_equity" in data and data["daily_open_equity"]:
            self._daily_open_equity = Decimal(data["daily_open_equity"])
        if "daily_open_day_key" in data and data["daily_open_day_key"]:
            self._daily_open_day_key = str(data["daily_open_day_key"])
        elif self._daily_open_equity is not None:
            self._daily_open_day_key = self._utc_day_key()
        if "positions" in data:
            for key, pd in data["positions"].items():
                try:
                    venue, pair, itype = key.split(":", 2)
                    iid = InstrumentId(venue=venue, trading_pair=pair, instrument_type=itype)
                    self._positions[key] = PaperPosition.from_dict(pd, iid)
                except Exception as exc:
                    logger.warning("Could not restore position %s: %s", key, exc)
        if "leverage_by_key" in data and isinstance(data["leverage_by_key"], dict):
            try:
                self._leverage_by_key = {k: int(v) for k, v in data["leverage_by_key"].items()}
            except Exception:
                pass
        if "position_margin_reserved" in data and isinstance(data["position_margin_reserved"], dict):
            try:
                self._position_margin_reserved = {k: Decimal(str(v)) for k, v in data["position_margin_reserved"].items()}
                # Apply reserves into ledger so available() reflects lock after restart.
                for key, amt in self._position_margin_reserved.items():
                    if amt > _ZERO:
                        # Derive quote asset from the instrument key: venue:BASE-QUOTE:itype
                        quote = "USDT"
                        try:
                            _, pair, _ = key.split(":", 2)
                            parts = pair.split("-")
                            if len(parts) > 1 and parts[1]:
                                quote = parts[1]
                        except Exception:
                            pass
                        self._ledger.reserve(quote, amt)
            except Exception:
                pass
