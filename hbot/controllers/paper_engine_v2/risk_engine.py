"""Risk Engine for Paper Engine v2.

Extracted from PaperPortfolio.risk_guard and promoted to a first-class engine
with pre-trade and post-trade hooks, a full liquidation ladder, and portfolio-
level exposure aggregation (Nautilus-style RiskEngine architecture).

Liquidation ladder (inspired by exchange perp liquidation systems):
  SAFE   — margin ratio ≥ warn threshold: normal operation.
  WARN   — margin ratio < warn threshold: log warning, no action.
  CRITICAL — margin ratio < critical threshold: soft-pause new orders.
  LIQUIDATE — margin ratio < liquidation threshold: force-reduce position.
  BANKRUPT — equity ≤ 0: force-close all positions.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Tuple

from controllers.paper_engine_v2.types import (
    InstrumentId,
    InstrumentSpec,
    OrderSide,
    PaperOrder,
    _ZERO,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Risk levels
# ---------------------------------------------------------------------------

class MarginLevel(str, Enum):
    SAFE = "safe"
    WARN = "warn"
    CRITICAL = "critical"
    LIQUIDATE = "liquidate"
    BANKRUPT = "bankrupt"


@dataclass(frozen=True)
class LiquidationAction:
    """Describes a risk-engine-initiated reduction or close."""
    instrument_id: InstrumentId
    side: OrderSide           # direction needed to reduce/close
    quantity: Decimal         # abs quantity to trade
    reason: str
    level: MarginLevel


@dataclass(frozen=True)
class RiskDecision:
    """Result of a pre-trade risk check."""
    allowed: bool
    reason: str = ""       # populated when not allowed


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class RiskConfig:
    # Drawdown guard (% of peak equity)
    max_drawdown_pct_hard: Decimal = Decimal("0.10")
    # Per-instrument position notional cap
    max_position_notional_per_instrument: Decimal = Decimal("10000")
    # Portfolio net exposure cap
    max_net_exposure_quote: Decimal = Decimal("50000")
    # Margin ratio thresholds (equity / maintenance_margin)
    margin_ratio_warn: Decimal = Decimal("3.0")       # warn below 3x
    margin_ratio_critical: Decimal = Decimal("1.5")   # soft-pause below 1.5x
    margin_ratio_liquidate: Decimal = Decimal("1.1")  # force-reduce below 1.1x
    # Reduce fraction for a single liquidation step
    liquidation_reduce_pct: Decimal = Decimal("0.50") # reduce 50% of position per step


# ---------------------------------------------------------------------------
# RiskEngine
# ---------------------------------------------------------------------------

class RiskEngine:
    """First-class risk engine with pre-trade and post-trade hooks.

    Pre-trade: `check_order()` — reject or allow an incoming order.
    Post-trade: `evaluate()` — returns any required liquidation actions.

    The engine maintains no mutable state of its own; it queries the
    portfolio via the provided callable at call time.
    """

    def __init__(self, config: RiskConfig):
        self._cfg = config
        self._last_margin_level: MarginLevel = MarginLevel.SAFE

    # -- Pre-trade ---------------------------------------------------------

    def check_order(
        self,
        order: PaperOrder,
        spec: InstrumentSpec,
        portfolio_equity: Decimal,
        portfolio_peak_equity: Decimal,
        position_abs_qty: Decimal,
        net_exposure_quote: Decimal,
        mid_price: Optional[Decimal] = None,
        margin_level: MarginLevel = MarginLevel.SAFE,
    ) -> RiskDecision:
        """Pre-trade risk check. Returns RiskDecision(allowed=True/False)."""
        if mid_price is None or mid_price <= _ZERO:
            mid_price = order.price

        # Drawdown hard stop
        if portfolio_peak_equity > _ZERO and portfolio_equity < portfolio_peak_equity:
            dd = (portfolio_peak_equity - portfolio_equity) / portfolio_peak_equity
            if dd > self._cfg.max_drawdown_pct_hard:
                return RiskDecision(False, "drawdown_hard_stop")

        # Block new opening trades during critical/liquidate margin states
        if margin_level in (MarginLevel.CRITICAL, MarginLevel.LIQUIDATE, MarginLevel.BANKRUPT):
            return RiskDecision(False, f"margin_level_{margin_level.value}")

        # Position notional cap
        new_notional = (position_abs_qty + order.quantity) * mid_price
        if new_notional > self._cfg.max_position_notional_per_instrument:
            return RiskDecision(
                False,
                f"position_notional_cap: {new_notional:.2f} > {self._cfg.max_position_notional_per_instrument}",
            )

        # Net exposure cap
        order_exp = order.quantity * mid_price
        if (abs(net_exposure_quote) + order_exp) > self._cfg.max_net_exposure_quote:
            return RiskDecision(
                False,
                f"net_exposure_cap: {abs(net_exposure_quote) + order_exp:.2f} > {self._cfg.max_net_exposure_quote}",
            )

        return RiskDecision(True)

    # -- Margin level assessment -------------------------------------------

    def assess_margin_level(self, equity: Decimal, maintenance_margin: Decimal) -> MarginLevel:
        """Classify current portfolio into a MarginLevel."""
        if equity <= _ZERO:
            level = MarginLevel.BANKRUPT
        elif maintenance_margin <= _ZERO:
            level = MarginLevel.SAFE
        else:
            ratio = equity / maintenance_margin
            if ratio < self._cfg.margin_ratio_liquidate:
                level = MarginLevel.LIQUIDATE
            elif ratio < self._cfg.margin_ratio_critical:
                level = MarginLevel.CRITICAL
            elif ratio < self._cfg.margin_ratio_warn:
                level = MarginLevel.WARN
            else:
                level = MarginLevel.SAFE

        if level != self._last_margin_level:
            if level in (MarginLevel.CRITICAL, MarginLevel.LIQUIDATE, MarginLevel.BANKRUPT):
                logger.warning(
                    "RiskEngine: margin level changed %s -> %s (equity=%s, maint=%s)",
                    self._last_margin_level.value, level.value, equity, maintenance_margin,
                )
            self._last_margin_level = level
        return level

    # -- Post-trade / liquidation ladder -----------------------------------

    def evaluate(
        self,
        equity: Decimal,
        maintenance_margin: Decimal,
        positions: Dict[str, Tuple[Decimal, InstrumentId]],  # key -> (signed_qty, iid)
    ) -> Tuple[MarginLevel, List[LiquidationAction]]:
        """Post-trade risk evaluation. Returns margin level + any actions.

        Liquidation actions are advisory: the desk should route them as
        forced orders outside the normal order-placement flow.

        Parameters
        ----------
        equity:
            Current portfolio equity in quote currency.
        maintenance_margin:
            Total maintenance margin reserved across all perp positions.
        positions:
            Dict of key -> (signed_quantity, InstrumentId) for all open perps.

        Returns
        -------
        (MarginLevel, list[LiquidationAction])
        """
        level = self.assess_margin_level(equity, maintenance_margin)
        actions: List[LiquidationAction] = []

        if level == MarginLevel.BANKRUPT:
            # Force-close all positions.
            for key, (qty, iid) in positions.items():
                if qty == _ZERO or not iid.is_perp:
                    continue
                side = OrderSide.SELL if qty > _ZERO else OrderSide.BUY
                actions.append(LiquidationAction(
                    instrument_id=iid,
                    side=side,
                    quantity=abs(qty),
                    reason="bankruptcy_force_close",
                    level=level,
                ))

        elif level == MarginLevel.LIQUIDATE:
            # Reduce each perp position by `liquidation_reduce_pct`.
            reduce_pct = self._cfg.liquidation_reduce_pct
            for key, (qty, iid) in positions.items():
                if qty == _ZERO or not iid.is_perp:
                    continue
                reduce_qty = abs(qty) * reduce_pct
                if reduce_qty <= _ZERO:
                    continue
                side = OrderSide.SELL if qty > _ZERO else OrderSide.BUY
                actions.append(LiquidationAction(
                    instrument_id=iid,
                    side=side,
                    quantity=reduce_qty,
                    reason="margin_liquidation_reduce",
                    level=level,
                ))

        return level, actions

    # -- Ops/reporting helpers ---------------------------------------------

    def margin_level_to_risk_reason(self, level: MarginLevel) -> str:
        """Convert a margin level to a risk reason string (EPP-compatible)."""
        mapping = {
            MarginLevel.SAFE: "",
            MarginLevel.WARN: "margin_warn",
            MarginLevel.CRITICAL: "margin_critical",
            MarginLevel.LIQUIDATE: "margin_liquidate",
            MarginLevel.BANKRUPT: "margin_bankrupt",
        }
        return mapping.get(level, "")
