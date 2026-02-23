"""Risk policy checks and edge gating for EPP v2.4.

Provides stateless risk limit evaluation and stateful edge gate logic.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Tuple

from controllers.epp_v2_4 import _clip


class RiskPolicy:
    """Evaluates risk limits and manages edge gate state."""

    def __init__(
        self,
        min_base_pct: Decimal,
        max_base_pct: Decimal,
        max_total_notional_quote: Decimal,
        max_daily_turnover_x_hard: Decimal,
        max_daily_loss_pct_hard: Decimal,
        max_drawdown_pct_hard: Decimal,
        edge_state_hold_s: int,
    ):
        self._min_base_pct = min_base_pct
        self._max_base_pct = max_base_pct
        self._max_total_notional_quote = max_total_notional_quote
        self._max_daily_turnover_x_hard = max_daily_turnover_x_hard
        self._max_daily_loss_pct_hard = max_daily_loss_pct_hard
        self._max_drawdown_pct_hard = max_drawdown_pct_hard
        self._edge_hold_s = edge_state_hold_s

        self._edge_gate_blocked: bool = False
        self._edge_gate_changed_ts: float = 0.0

    @property
    def edge_gate_blocked(self) -> bool:
        return self._edge_gate_blocked

    def check_risk(
        self,
        base_pct: Decimal,
        turnover_x: Decimal,
        projected_total_quote: Decimal,
        daily_loss_pct: Decimal,
        drawdown_pct: Decimal,
    ) -> Tuple[List[str], bool]:
        """Return ``(reasons, hard_stop)`` — reasons list and whether hard stop is warranted."""
        reasons: List[str] = []
        hard = False
        if base_pct < self._min_base_pct:
            reasons.append("base_pct_below_min")
        if base_pct > self._max_base_pct:
            reasons.append("base_pct_above_max")
        if self._max_total_notional_quote > 0 and projected_total_quote > self._max_total_notional_quote:
            reasons.append("projected_total_quote_above_cap")
        if turnover_x > self._max_daily_turnover_x_hard:
            reasons.append("daily_turnover_hard_limit")
            hard = True
        if daily_loss_pct > self._max_daily_loss_pct_hard:
            reasons.append("daily_loss_hard_limit")
            hard = True
        if drawdown_pct > self._max_drawdown_pct_hard:
            reasons.append("drawdown_hard_limit")
            hard = True
        return reasons, hard

    @staticmethod
    def loss_metrics(
        equity_quote: Decimal,
        daily_equity_open: Decimal,
        daily_equity_peak: Decimal,
    ) -> Tuple[Decimal, Decimal]:
        """Return ``(daily_loss_pct, drawdown_pct)``."""
        daily_loss_pct = Decimal("0")
        drawdown_pct = Decimal("0")
        if daily_equity_open > 0:
            daily_loss_pct = max(Decimal("0"), (daily_equity_open - equity_quote) / daily_equity_open)
        if daily_equity_peak > 0:
            drawdown_pct = max(Decimal("0"), (daily_equity_peak - equity_quote) / daily_equity_peak)
        return daily_loss_pct, drawdown_pct

    def edge_gate_update(
        self,
        now_ts: float,
        net_edge: Decimal,
        pause_threshold: Decimal,
        resume_threshold: Decimal,
    ) -> None:
        """Update edge gate state with hysteresis and hold timer."""
        hold_sec = max(5, self._edge_hold_s)
        if self._edge_gate_changed_ts <= 0:
            self._edge_gate_changed_ts = now_ts
        elapsed = now_ts - self._edge_gate_changed_ts
        if self._edge_gate_blocked:
            if net_edge > resume_threshold and elapsed >= hold_sec:
                self._edge_gate_blocked = False
                self._edge_gate_changed_ts = now_ts
            return
        if net_edge < pause_threshold and elapsed >= hold_sec:
            self._edge_gate_blocked = True
            self._edge_gate_changed_ts = now_ts
