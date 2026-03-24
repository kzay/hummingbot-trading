"""State container dataclasses for EppV24Controller."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

_ZERO = Decimal("0")
_ONE = Decimal("1")


@dataclass
class PositionState:
    base: Decimal = _ZERO
    avg_entry_price: Decimal = _ZERO
    realized_pnl_today: Decimal = _ZERO
    drift_pct: Decimal = _ZERO
    drift_correction_count: int = 0
    first_drift_correction_ts: float = 0.0


@dataclass
class DailyCounters:
    equity_open: Decimal | None = None
    equity_peak: Decimal | None = None
    traded_notional: Decimal = _ZERO
    fills_count: int = 0
    fees_paid_quote: Decimal = _ZERO
    funding_cost_quote: Decimal = _ZERO
    cancel_budget_breach_count: int = 0
    key: str = ""


@dataclass
class FillEdgeState:
    ewma: Decimal | None = None
    variance: Decimal | None = None
    fill_count_for_kelly: int = 0
    adverse_fill_count: int = 0


@dataclass
class FeeState:
    maker_pct: Decimal = Decimal("0.0010")
    taker_pct: Decimal = Decimal("0.0010")
    source: str = "manual"
    resolved: bool = False
    resolution_error: str = ""
    last_resolve_ts: float = 0.0
    rate_mismatch_warned: bool = False


@dataclass
class TickContext:
    """Bundles all data needed by _emit_tick_output and related methods."""
    t0: float
    now: float
    mid: Decimal
    regime_name: str
    target_base_pct: Decimal
    target_net_base_pct: Decimal
    base_pct_gross: Decimal
    base_pct_net: Decimal
    equity_quote: Decimal
    spread_state: Any  # SpreadEdgeState
    market: Any  # MarketConditions
    risk_hard_stop: bool
    risk_reasons: list
    daily_loss_pct: Decimal
    drawdown_pct: Decimal
    projected_total_quote: Decimal
    state: Any  # GuardState
