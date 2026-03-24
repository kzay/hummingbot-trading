"""Risk evaluation for EPP v2.4.

Stateless risk limit checks, loss metrics computation, and stateful
edge gate hysteresis logic — extracted from ``EppV24Controller``.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from controllers.ops_guard import GuardState
from controllers.runtime.risk_context import RuntimeRiskDecision
from platform_lib.core.utils import safe_decimal

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")


class RiskEvaluator:
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
        margin_ratio_hard_stop_pct: Decimal = Decimal("0.10"),
        margin_ratio_soft_pause_pct: Decimal = Decimal("0.20"),
        position_drift_soft_pause_pct: Decimal = Decimal("0.05"),
    ):
        self._min_base_pct = min_base_pct
        self._max_base_pct = max_base_pct
        self._max_total_notional_quote = max_total_notional_quote
        self._max_daily_turnover_x_hard = max_daily_turnover_x_hard
        self._max_daily_loss_pct_hard = max_daily_loss_pct_hard
        self._max_drawdown_pct_hard = max_drawdown_pct_hard
        self._edge_hold_s = edge_state_hold_s
        self._margin_ratio_hard_stop_pct = margin_ratio_hard_stop_pct
        self._margin_ratio_soft_pause_pct = margin_ratio_soft_pause_pct
        self._position_drift_soft_pause_pct = position_drift_soft_pause_pct

        self._edge_gate_blocked: bool = False
        self._edge_gate_changed_ts: float = 0.0

    @property
    def edge_gate_blocked(self) -> bool:
        return self._edge_gate_blocked

    # ------------------------------------------------------------------
    # Loss metrics (stateless)
    # ------------------------------------------------------------------

    @staticmethod
    def risk_loss_metrics(
        equity_quote: Decimal,
        daily_equity_open: Decimal,
        daily_equity_peak: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """Return ``(daily_loss_pct, drawdown_pct)``.

        NaN/Inf inputs are treated as worst-case (100% loss) to ensure
        risk checks never fail-open on bad data.
        """
        eq = safe_decimal(equity_quote)
        deo = safe_decimal(daily_equity_open)
        dep = safe_decimal(daily_equity_peak)
        daily_loss_pct = _ZERO
        drawdown_pct = _ZERO
        if deo > _ZERO:
            daily_loss_pct = max(_ZERO, (deo - eq) / deo)
        if dep > _ZERO:
            drawdown_pct = max(_ZERO, (dep - eq) / dep)
        if daily_loss_pct.is_nan() or daily_loss_pct.is_infinite():
            daily_loss_pct = _ONE
        if drawdown_pct.is_nan() or drawdown_pct.is_infinite():
            drawdown_pct = _ONE
        return daily_loss_pct, drawdown_pct

    # ------------------------------------------------------------------
    # Risk policy checks (stateless)
    # ------------------------------------------------------------------

    def risk_policy_checks(
        self,
        base_pct: Decimal,
        turnover_x: Decimal,
        projected_total_quote: Decimal,
        daily_loss_pct: Decimal,
        drawdown_pct: Decimal,
    ) -> tuple[list[str], bool]:
        """Return ``(reasons, hard_stop)``."""
        reasons: list[str] = []
        hard = False
        if base_pct < self._min_base_pct:
            reasons.append("base_pct_below_min")
        if base_pct > self._max_base_pct:
            reasons.append("base_pct_above_max")
        if self._max_total_notional_quote > _ZERO and projected_total_quote > self._max_total_notional_quote:
            reasons.append("projected_total_quote_above_cap")
        if self._max_daily_turnover_x_hard > _ZERO and turnover_x > self._max_daily_turnover_x_hard:
            reasons.append("daily_turnover_hard_limit")
            hard = True
        if daily_loss_pct > self._max_daily_loss_pct_hard:
            reasons.append("daily_loss_hard_limit")
            hard = True
        if drawdown_pct > self._max_drawdown_pct_hard:
            reasons.append("drawdown_hard_limit")
            hard = True
        return reasons, hard

    # ------------------------------------------------------------------
    # Full risk evaluation (combines policy + margin + operational)
    # ------------------------------------------------------------------

    def evaluate_all_risk(
        self,
        daily_loss_pct: Decimal,
        drawdown_pct: Decimal,
        base_pct_gross: Decimal,
        turnover_x: Decimal,
        projected_total_quote: Decimal,
        is_perp: bool,
        margin_ratio: Decimal,
        startup_position_sync_done: bool,
        position_drift_pct: Decimal,
        order_book_stale: bool,
        pending_eod_close: bool,
    ) -> tuple[list[str], bool]:
        """Run risk policy, margin, drift, and operational checks.

        Returns ``(risk_reasons, risk_hard_stop)``.
        """
        reasons, hard = self.risk_policy_checks(
            base_pct=base_pct_gross,
            turnover_x=turnover_x,
            projected_total_quote=projected_total_quote,
            daily_loss_pct=daily_loss_pct,
            drawdown_pct=drawdown_pct,
        )
        if is_perp:
            if margin_ratio < self._margin_ratio_hard_stop_pct:
                reasons.append("margin_ratio_critical")
                hard = True
                logger.error(
                    "Margin ratio %.4f below hard stop threshold %.4f",
                    margin_ratio, self._margin_ratio_hard_stop_pct,
                )
            elif margin_ratio < self._margin_ratio_soft_pause_pct:
                reasons.append("margin_ratio_warning")
        if not startup_position_sync_done:
            reasons.append("startup_position_sync_pending")
        if position_drift_pct > self._position_drift_soft_pause_pct:
            reasons.append("position_drift_high")
        if order_book_stale:
            reasons.append("order_book_stale")
        if pending_eod_close:
            reasons.append("eod_close_pending")
        return reasons, hard

    def build_runtime_risk_decision(
        self,
        *,
        daily_loss_pct: Decimal,
        drawdown_pct: Decimal,
        base_pct_gross: Decimal,
        turnover_x: Decimal,
        projected_total_quote: Decimal,
        is_perp: bool,
        margin_ratio: Decimal,
        startup_position_sync_done: bool,
        position_drift_pct: Decimal,
        order_book_stale: bool,
        pending_eod_close: bool,
        guard_state: GuardState,
    ) -> RuntimeRiskDecision:
        reasons, hard = self.evaluate_all_risk(
            daily_loss_pct=daily_loss_pct,
            drawdown_pct=drawdown_pct,
            base_pct_gross=base_pct_gross,
            turnover_x=turnover_x,
            projected_total_quote=projected_total_quote,
            is_perp=is_perp,
            margin_ratio=margin_ratio,
            startup_position_sync_done=startup_position_sync_done,
            position_drift_pct=position_drift_pct,
            order_book_stale=order_book_stale,
            pending_eod_close=pending_eod_close,
        )
        return RuntimeRiskDecision(
            risk_reasons=reasons,
            risk_hard_stop=hard,
            daily_loss_pct=daily_loss_pct,
            drawdown_pct=drawdown_pct,
            guard_state=guard_state,
        )

    # ------------------------------------------------------------------
    # Edge gate hysteresis (stateful)
    # ------------------------------------------------------------------

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

    def reset_edge_gate(self, now_ts: float = 0.0) -> None:
        """Clear edge-gate state when a strategy does not opt into shared edge gating."""
        self._edge_gate_blocked = False
        self._edge_gate_changed_ts = now_ts
