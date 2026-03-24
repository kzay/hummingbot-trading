from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from controllers.runtime.runtime_types import MarketConditions, RegimeSpec, SpreadEdgeState


@dataclass(frozen=True)
class RuntimeDataContext:
    """Neutral runtime inputs assembled before execution-family mapping."""

    now_ts: float
    mid: Decimal
    regime_name: str
    regime_spec: RegimeSpec
    spread_state: SpreadEdgeState
    market: MarketConditions
    equity_quote: Decimal
    target_base_pct: Decimal
    target_net_base_pct: Decimal
    base_pct_gross: Decimal
    base_pct_net: Decimal


__all__ = ["RuntimeDataContext"]
