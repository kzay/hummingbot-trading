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
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

from controllers.paper_engine_v2.types import (
    FundingApplied,
    InstrumentId,
    InstrumentSpec,
    OrderSide,
    PaperOrder,
    PaperPosition,
    PositionChanged,
    _EPS,
    _ONE,
    _ZERO,
    _uuid,
)

logger = logging.getLogger(__name__)


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
            return "drawdown_hard_stop"

        # Position notional cap
        pos = self._portfolio.get_position(spec.instrument_id)
        new_notional = (pos.abs_quantity + order.quantity) * mid_price
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
        self._peak_equity: Decimal = _ZERO
        self._daily_open_equity: Optional[Decimal] = None
        self.risk_guard = RiskGuard(config, self)
        self._config = config

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

    def get_position(self, instrument_id: InstrumentId) -> PaperPosition:
        return self._positions.get(instrument_id.key, PaperPosition.flat(instrument_id))

    def all_positions(self) -> Dict[str, PaperPosition]:
        return dict(self._positions)

    def mark_to_market(self, prices: Dict[str, Decimal]) -> None:
        """Update unrealized PnL on all positions."""
        for key, pos in self._positions.items():
            price = prices.get(key)
            if price is None or price <= _ZERO or pos.quantity == _ZERO:
                pos.unrealized_pnl = _ZERO
                continue
            direction = _ONE if pos.quantity > _ZERO else Decimal("-1")
            pos.unrealized_pnl = (price - pos.avg_entry_price) * pos.abs_quantity * direction

    def apply_funding(
        self, instrument_id: InstrumentId, charge: Decimal, now_ns: int
    ) -> FundingApplied:
        """Debit funding charge from portfolio and record on position."""
        pos = self._positions.get(instrument_id.key)
        notional = _ZERO
        if pos is not None:
            pos.funding_paid += charge
            notional = pos.abs_quantity * pos.avg_entry_price
        self._ledger.debit(instrument_id.quote_asset, charge)
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
    ) -> PositionChanged:
        """Settle a fill: update position and ledger.

        Realized PnL = pure price PnL only.
        Fees debited separately (Nautilus convention).
        """
        pos = self._positions.get(instrument_id.key, PaperPosition.flat(instrument_id))

        fill_signed = +quantity if side == OrderSide.BUY else -quantity
        old_qty = pos.quantity
        new_qty = old_qty + fill_signed
        realized_pnl = _ZERO

        is_closing = (old_qty > _ZERO and fill_signed < _ZERO) or (
            old_qty < _ZERO and fill_signed > _ZERO
        )

        if is_closing and old_qty != _ZERO:
            # min() avoids double-counting on flip (Nautilus pattern)
            close_qty = min(abs(fill_signed), abs(old_qty))
            direction = _ONE if old_qty > _ZERO else Decimal("-1")
            realized_pnl = (price - pos.avg_entry_price) * close_qty * direction

            # Flip: remaining qty opens in opposite direction at fill price
            if new_qty != _ZERO and (new_qty > _ZERO) != (old_qty > _ZERO):
                pos.avg_entry_price = price
            # Partial close: avg_entry unchanged
        else:
            # Opening or adding to existing
            if abs(old_qty) > _ZERO:
                old_cost = abs(old_qty) * pos.avg_entry_price
                new_cost = quantity * price
                abs_new = abs(new_qty)
                pos.avg_entry_price = (old_cost + new_cost) / abs_new if abs_new > _ZERO else price
            else:
                pos.avg_entry_price = price
                pos.opened_at_ns = now_ns

        pos.quantity = new_qty
        pos.realized_pnl += realized_pnl
        pos.total_fees_paid += fee     # fees separate from PnL
        pos.last_fill_at_ns = now_ns

        # Reset opening time when flipping from flat
        if pos.opened_at_ns == 0 and new_qty != _ZERO:
            pos.opened_at_ns = now_ns

        # Clear position if flat
        if abs(new_qty) <= _EPS:
            pos.quantity = _ZERO

        # --- Ledger settlement ---
        self._settle_ledger(instrument_id, side, quantity, price, fee, spec, leverage, realized_pnl, is_closing)

        # Update peak equity tracking
        eq = self.equity_quote()
        if eq > self._peak_equity:
            self._peak_equity = eq
        if self._daily_open_equity is None and eq > _ZERO:
            self._daily_open_equity = eq

        self._positions[instrument_id.key] = pos

        return PositionChanged(
            event_id=_uuid(), timestamp_ns=now_ns,
            instrument_id=instrument_id,
            position=pos,
            trigger_order_id="",
            trigger_side=side.value,
            fill_price=price,
            fill_quantity=quantity,
            realized_pnl=realized_pnl,
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

    # -- Persistence -------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        return {
            "balances": self._ledger.to_dict(),
            "positions": {k: v.to_dict() for k, v in self._positions.items()},
            "peak_equity": str(self._peak_equity),
            "daily_open_equity": str(self._daily_open_equity) if self._daily_open_equity else None,
        }

    def restore_from_snapshot(self, data: Dict[str, Any]) -> None:
        if "balances" in data:
            self._ledger = MultiAssetLedger.from_dict(data["balances"])
        if "peak_equity" in data and data["peak_equity"]:
            self._peak_equity = Decimal(data["peak_equity"])
        if "daily_open_equity" in data and data["daily_open_equity"]:
            self._daily_open_equity = Decimal(data["daily_open_equity"])
        if "positions" in data:
            for key, pd in data["positions"].items():
                try:
                    venue, pair, itype = key.split(":", 2)
                    iid = InstrumentId(venue=venue, trading_pair=pair, instrument_type=itype)
                    self._positions[key] = PaperPosition.from_dict(pd, iid)
                except Exception as exc:
                    logger.warning("Could not restore position %s: %s", key, exc)
