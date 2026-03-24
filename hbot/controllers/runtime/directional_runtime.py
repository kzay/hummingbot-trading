"""Directional strategy runtime — inherits shared kernel, disables MM machinery.

Directional bots (bot5, bot6, bot7) extend this class instead of the raw
``EppV24Controller``/``SharedMmV24Controller``.  MM-specific subsystems
(edge gate, PnL governor, selective quoting, alpha policy, adaptive spread
knobs, auto-calibration) are stubbed to safe no-ops so they can never
accidentally activate on a directional strategy.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from controllers.runtime.contracts import RuntimeFamilyAdapter
from controllers.runtime.directional_core import DirectionalRuntimeAdapter
from controllers.runtime.runtime_types import MarketConditions, SpreadEdgeState
from controllers.shared_runtime_v24 import SharedRuntimeKernel

_ZERO = Decimal("0")
_ONE = Decimal("1")


class DirectionalRuntimeController(SharedRuntimeKernel):
    """Runtime base for directional strategy lanes.

    Inherits the shared runtime kernel directly (price buffer, risk limits,
    fill handling, logging, paper bridge, fee resolution, OpsGuard) while
    permanently disabling MM-only subsystems.  Does NOT inherit through
    ``EppV24Controller``, so MM-specific code is absent from the MRO.
    """

    # ── MM adapter override ───────────────────────────────────────────

    def _make_runtime_family_adapter(self) -> RuntimeFamilyAdapter:
        return DirectionalRuntimeAdapter(self)

    # ── Edge gate ─────────────────────────────────────────────────────

    def _update_edge_gate_ewma(self, now: float, spread_state: SpreadEdgeState) -> None:
        self._soft_pause_edge = False

    def _edge_gate_update(
        self, now_ts: float, net_edge: Decimal, pause_threshold: Decimal, resume_threshold: Decimal,
    ) -> None:
        pass

    # ── PnL governor ──────────────────────────────────────────────────

    def _compute_pnl_governor_size_mult(self, equity_quote: Decimal, turnover_x: Decimal) -> Decimal:
        self._pnl_governor_size_mult = _ONE
        self._pnl_governor_size_boost_active = False
        self._pnl_governor_size_boost_reason = "directional_runtime"
        return _ONE

    def _increment_governor_reason_count(self, attr_name: str, reason: str) -> None:
        pass

    # ── Selective quoting ─────────────────────────────────────────────

    def _compute_selective_quote_quality(self, regime_name: str) -> dict[str, Any]:
        return {"score": _ZERO, "state": "inactive", "side_bias": _ZERO}

    # ── Alpha policy ──────────────────────────────────────────────────

    def _compute_alpha_policy(
        self,
        *,
        regime_name: str,
        spread_state: SpreadEdgeState,
        market: MarketConditions,
        target_net_base_pct: Decimal,
        base_pct_net: Decimal,
    ) -> dict[str, Any]:
        return {
            "state": "directional",
            "reason": "directional_runtime",
            "maker_score": _ZERO,
            "aggressive_score": _ZERO,
            "cross_allowed": False,
        }

    # ── MM soft-pause gates ───────────────────────────────────────────

    def _fill_edge_below_cost_floor(self) -> bool:
        return False

    def _adverse_fill_soft_pause_active(self) -> bool:
        return False

    def _edge_confidence_soft_pause_active(self) -> bool:
        return False

    def _slippage_soft_pause_active(self) -> bool:
        return False

    # ── Spread competitiveness (MM-only) ──────────────────────────────

    def _apply_spread_competitiveness_cap(
        self,
        buy_spreads: list[Decimal],
        sell_spreads: list[Decimal],
        market: MarketConditions,
    ) -> tuple[list[Decimal], list[Decimal]]:
        self._spread_competitiveness_cap_active = False
        self._spread_competitiveness_cap_side_pct = _ZERO
        return buy_spreads, sell_spreads

    # ── Adaptive spread knobs (MM-only) ───────────────────────────────

    def _update_adaptive_history(
        self, *, band_pct: Decimal | None = None, market_spread_pct: Decimal | None = None,
    ) -> None:
        pass

    # ── Kelly sizing (MM-only) ────────────────────────────────────────

    def _get_kelly_order_quote(self, equity_quote: Decimal) -> Decimal:
        return _ZERO

    # ── Auto-calibration (MM-only) ────────────────────────────────────

    def _auto_calibration_record_minute(self, *args: Any, **kwargs: Any) -> None:
        pass

    def _auto_calibration_record_fill(self, *args: Any, **kwargs: Any) -> None:
        pass

    def _auto_calibration_maybe_run(self, *args: Any, **kwargs: Any) -> None:
        pass

    # ── Risk evaluation override ──────────────────────────────────────

    def _evaluate_all_risk(
        self, spread_state: SpreadEdgeState, base_pct_gross: Decimal,
        equity_quote: Decimal, projected_total_quote: Decimal, market: MarketConditions,
    ) -> tuple[list[str], bool, Decimal, Decimal]:
        """Evaluate risk using only shared hard limits (no MM soft-pause gates)."""
        daily_loss_pct, drawdown_pct = self._risk_loss_metrics(equity_quote)
        risk_reasons, risk_hard_stop = self._risk_evaluator.evaluate_all_risk(
            daily_loss_pct=daily_loss_pct,
            drawdown_pct=drawdown_pct,
            base_pct_gross=base_pct_gross,
            turnover_x=spread_state.turnover_x,
            projected_total_quote=projected_total_quote,
            is_perp=self._is_perp,
            margin_ratio=self._margin_ratio,
            startup_position_sync_done=self._startup_position_sync_done,
            position_drift_pct=self._position_drift_pct,
            order_book_stale=market.order_book_stale,
            pending_eod_close=self._pending_eod_close,
        )
        return risk_reasons, risk_hard_stop, daily_loss_pct, drawdown_pct


__all__ = ["DirectionalRuntimeController"]
