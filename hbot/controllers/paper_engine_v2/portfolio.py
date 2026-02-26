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
        # Per-instrument metadata for margin and mark-to-market.
        # Stored opportunistically on fills / mtm ticks so PaperPortfolio can
        # compute maintenance margin without holding a hard dependency on the
        # desk/engine registry.
        self._spec_by_key: Dict[str, InstrumentSpec] = {}
        self._leverage_by_key: Dict[str, int] = {}
        self._position_margin_reserved: Dict[str, Decimal] = {}  # key -> reserved quote
        self._peak_equity: Decimal = _ZERO
        self._daily_open_equity: Optional[Decimal] = None
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
        """Update unrealized PnL on all positions, and refresh maintenance margin reserves."""
        for key, pos in self._positions.items():
            price = prices.get(key)
            if price is None or price <= _ZERO or pos.quantity == _ZERO:
                pos.unrealized_pnl = _ZERO
                continue
            pos.unrealized_pnl = _unrealized_pnl(pos.quantity, pos.avg_entry_price, price)
        self._refresh_position_margin_reserves(prices)

    def _refresh_position_margin_reserves(self, prices: Dict[str, Decimal]) -> None:
        """Reserve/release maintenance margin for perp positions (Nautilus-style).

        Order reserves are handled by the matching engine. This reserve bucket
        models locked *position* margin so available quote balance is realistic
        while positions are open.
        """
        for key, pos in self._positions.items():
            if not pos.instrument_id.is_perp or pos.quantity == _ZERO:
                self._set_position_margin_reserved(key, _ZERO, pos.instrument_id.quote_asset)
                continue
            spec = self._spec_by_key.get(key)
            lev = int(self._leverage_by_key.get(key, 1) or 1)
            px = prices.get(key)
            if spec is None or px is None or px <= _ZERO:
                # If we can't price the position, keep prior reserve to avoid
                # oscillation. (Availability will still clamp to zero safely.)
                continue
            target = spec.compute_margin_maint(pos.abs_quantity, px, lev)
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

        Delegates position math to `accounting.apply_fill()` (Nautilus-inspired
        deterministic accounting core). Ledger settlement (cash/margin flows)
        and event emission remain here.

        Realized PnL = pure price PnL only.
        Fees debited separately (Nautilus convention).
        """
        pos = self._positions.get(instrument_id.key, PaperPosition.flat(instrument_id))

        # Cache per-instrument metadata for later mtm/margin refresh.
        self._spec_by_key[instrument_id.key] = spec
        self._leverage_by_key[instrument_id.key] = max(1, int(leverage))

        # ---- Pure accounting via dedicated core ----
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

        # ---- Update position fields ----
        pos.quantity = new_state.quantity
        pos.avg_entry_price = new_state.avg_entry_price
        pos.realized_pnl = new_state.realized_pnl
        pos.opened_at_ns = new_state.opened_at_ns
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
        if self._daily_open_equity is None and eq > _ZERO:
            self._daily_open_equity = eq

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
