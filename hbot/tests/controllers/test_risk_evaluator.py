from __future__ import annotations

from decimal import Decimal

import pytest

from controllers.ops_guard import GuardState
from controllers.risk_evaluator import RiskEvaluator
from controllers.runtime.risk_context import RuntimeRiskDecision

_ZERO = Decimal("0")
_D = Decimal


def _make_evaluator(**overrides) -> RiskEvaluator:
    defaults = dict(
        min_base_pct=_D("0.30"),
        max_base_pct=_D("0.70"),
        max_total_notional_quote=_D("1000"),
        max_daily_turnover_x_hard=_D("10"),
        max_daily_loss_pct_hard=_D("0.05"),
        max_drawdown_pct_hard=_D("0.10"),
        edge_state_hold_s=10,
        margin_ratio_hard_stop_pct=_D("0.10"),
        margin_ratio_soft_pause_pct=_D("0.20"),
        position_drift_soft_pause_pct=_D("0.05"),
    )
    defaults.update(overrides)
    return RiskEvaluator(**defaults)


# ------------------------------------------------------------------
# risk_loss_metrics (stateless)
# ------------------------------------------------------------------

class TestRiskLossMetrics:
    def test_normal_loss(self):
        loss, dd = RiskEvaluator.risk_loss_metrics(_D("950"), _D("1000"), _D("1050"))
        assert loss == _D("0.05")
        assert dd == (_D("1050") - _D("950")) / _D("1050")

    def test_no_loss_when_profitable(self):
        loss, dd = RiskEvaluator.risk_loss_metrics(_D("1100"), _D("1000"), _D("1100"))
        assert loss == _ZERO
        assert dd == _ZERO

    def test_zero_equity_open_no_divide_error(self):
        loss, dd = RiskEvaluator.risk_loss_metrics(_D("500"), _ZERO, _D("1000"))
        assert loss == _ZERO

    def test_zero_equity_peak_no_divide_error(self):
        loss, dd = RiskEvaluator.risk_loss_metrics(_D("500"), _D("1000"), _ZERO)
        assert dd == _ZERO

    def test_both_zero_no_crash(self):
        loss, dd = RiskEvaluator.risk_loss_metrics(_D("500"), _ZERO, _ZERO)
        assert loss == _ZERO
        assert dd == _ZERO

    def test_nan_equity_treated_as_worst_case(self):
        loss, dd = RiskEvaluator.risk_loss_metrics(Decimal("NaN"), _D("1000"), _D("1000"))
        assert loss == _D("1")  # 100% loss — fail-closed

    def test_nan_equity_open_safe(self):
        loss, dd = RiskEvaluator.risk_loss_metrics(_D("900"), Decimal("NaN"), _D("1000"))
        assert loss == _ZERO  # sanitized to 0, so daily_equity_open <= 0

    def test_nan_peak_safe(self):
        loss, dd = RiskEvaluator.risk_loss_metrics(_D("900"), _D("1000"), Decimal("NaN"))
        assert dd == _ZERO  # sanitized to 0, so daily_equity_peak <= 0

    def test_inf_equity_treated_as_worst_case(self):
        loss, dd = RiskEvaluator.risk_loss_metrics(Decimal("Infinity"), _D("1000"), _D("1000"))
        assert loss == _ZERO or loss == _D("1")  # sanitized to 0 -> treated as zero


# ------------------------------------------------------------------
# risk_policy_checks
# ------------------------------------------------------------------

class TestRiskPolicyChecks:
    def test_all_within_limits(self):
        ev = _make_evaluator()
        reasons, hard = ev.risk_policy_checks(_D("0.50"), _D("1"), _D("100"), _D("0.01"), _D("0.02"))
        assert reasons == []
        assert hard is False

    def test_base_pct_below_min(self):
        ev = _make_evaluator()
        reasons, hard = ev.risk_policy_checks(_D("0.20"), _D("1"), _D("100"), _ZERO, _ZERO)
        assert "base_pct_below_min" in reasons
        assert hard is False

    def test_base_pct_above_max(self):
        ev = _make_evaluator()
        reasons, hard = ev.risk_policy_checks(_D("0.80"), _D("1"), _D("100"), _ZERO, _ZERO)
        assert "base_pct_above_max" in reasons
        assert hard is False

    def test_projected_total_above_cap(self):
        ev = _make_evaluator()
        reasons, hard = ev.risk_policy_checks(_D("0.50"), _D("1"), _D("2000"), _ZERO, _ZERO)
        assert "projected_total_quote_above_cap" in reasons
        assert hard is False

    def test_cap_disabled_when_zero(self):
        ev = _make_evaluator(max_total_notional_quote=_ZERO)
        reasons, _ = ev.risk_policy_checks(_D("0.50"), _D("1"), _D("999999"), _ZERO, _ZERO)
        assert "projected_total_quote_above_cap" not in reasons

    def test_daily_turnover_hard(self):
        ev = _make_evaluator()
        reasons, hard = ev.risk_policy_checks(_D("0.50"), _D("15"), _D("100"), _ZERO, _ZERO)
        assert "daily_turnover_hard_limit" in reasons
        assert hard is True

    def test_turnover_disabled_when_zero(self):
        ev = _make_evaluator(max_daily_turnover_x_hard=_ZERO)
        reasons, hard = ev.risk_policy_checks(_D("0.50"), _D("999"), _D("100"), _ZERO, _ZERO)
        assert "daily_turnover_hard_limit" not in reasons
        assert hard is False

    def test_daily_loss_hard(self):
        ev = _make_evaluator()
        reasons, hard = ev.risk_policy_checks(_D("0.50"), _D("1"), _D("100"), _D("0.06"), _ZERO)
        assert "daily_loss_hard_limit" in reasons
        assert hard is True

    def test_drawdown_hard(self):
        ev = _make_evaluator()
        reasons, hard = ev.risk_policy_checks(_D("0.50"), _D("1"), _D("100"), _ZERO, _D("0.12"))
        assert "drawdown_hard_limit" in reasons
        assert hard is True

    def test_multiple_hard_reasons(self):
        ev = _make_evaluator()
        reasons, hard = ev.risk_policy_checks(_D("0.50"), _D("15"), _D("100"), _D("0.06"), _D("0.12"))
        assert "daily_turnover_hard_limit" in reasons
        assert "daily_loss_hard_limit" in reasons
        assert "drawdown_hard_limit" in reasons
        assert hard is True

    @pytest.mark.parametrize("base_pct,expected_reason", [
        (_D("0.29"), "base_pct_below_min"),
        (_D("0.30"), None),
        (_D("0.70"), None),
        (_D("0.71"), "base_pct_above_max"),
    ])
    def test_base_pct_boundaries(self, base_pct, expected_reason):
        ev = _make_evaluator()
        reasons, _ = ev.risk_policy_checks(base_pct, _D("1"), _D("100"), _ZERO, _ZERO)
        if expected_reason:
            assert expected_reason in reasons
        else:
            assert not any(r.startswith("base_pct") for r in reasons)


# ------------------------------------------------------------------
# evaluate_all_risk (policy + margin + operational)
# ------------------------------------------------------------------

class TestEvaluateAllRisk:
    def _safe_defaults(self):
        return dict(
            daily_loss_pct=_ZERO,
            drawdown_pct=_ZERO,
            base_pct_gross=_D("0.50"),
            turnover_x=_D("1"),
            projected_total_quote=_D("100"),
            is_perp=True,
            margin_ratio=_D("0.50"),
            startup_position_sync_done=True,
            position_drift_pct=_ZERO,
            order_book_stale=False,
            pending_eod_close=False,
        )

    def test_clean_state(self):
        ev = _make_evaluator()
        reasons, hard = ev.evaluate_all_risk(**self._safe_defaults())
        assert reasons == []
        assert hard is False

    def test_margin_critical_hard_stop(self):
        ev = _make_evaluator()
        args = self._safe_defaults()
        args["margin_ratio"] = _D("0.05")
        reasons, hard = ev.evaluate_all_risk(**args)
        assert "margin_ratio_critical" in reasons
        assert hard is True

    def test_margin_warning_soft_pause(self):
        ev = _make_evaluator()
        args = self._safe_defaults()
        args["margin_ratio"] = _D("0.15")
        reasons, hard = ev.evaluate_all_risk(**args)
        assert "margin_ratio_warning" in reasons
        assert hard is False

    def test_margin_ignored_for_spot(self):
        ev = _make_evaluator()
        args = self._safe_defaults()
        args["is_perp"] = False
        args["margin_ratio"] = _D("0.01")
        reasons, _ = ev.evaluate_all_risk(**args)
        assert "margin_ratio_critical" not in reasons
        assert "margin_ratio_warning" not in reasons

    def test_startup_sync_pending(self):
        ev = _make_evaluator()
        args = self._safe_defaults()
        args["startup_position_sync_done"] = False
        reasons, _ = ev.evaluate_all_risk(**args)
        assert "startup_position_sync_pending" in reasons

    def test_position_drift_high(self):
        ev = _make_evaluator()
        args = self._safe_defaults()
        args["position_drift_pct"] = _D("0.10")
        reasons, _ = ev.evaluate_all_risk(**args)
        assert "position_drift_high" in reasons

    def test_order_book_stale(self):
        ev = _make_evaluator()
        args = self._safe_defaults()
        args["order_book_stale"] = True
        reasons, _ = ev.evaluate_all_risk(**args)
        assert "order_book_stale" in reasons

    def test_pending_eod_close(self):
        ev = _make_evaluator()
        args = self._safe_defaults()
        args["pending_eod_close"] = True
        reasons, _ = ev.evaluate_all_risk(**args)
        assert "eod_close_pending" in reasons


# ------------------------------------------------------------------
# build_runtime_risk_decision
# ------------------------------------------------------------------

class TestBuildRuntimeRiskDecision:
    def test_returns_dataclass(self):
        ev = _make_evaluator()
        decision = ev.build_runtime_risk_decision(
            daily_loss_pct=_D("0.01"),
            drawdown_pct=_D("0.02"),
            base_pct_gross=_D("0.50"),
            turnover_x=_D("1"),
            projected_total_quote=_D("100"),
            is_perp=False,
            margin_ratio=_D("1"),
            startup_position_sync_done=True,
            position_drift_pct=_ZERO,
            order_book_stale=False,
            pending_eod_close=False,
            guard_state=GuardState.RUNNING,
        )
        assert isinstance(decision, RuntimeRiskDecision)
        assert decision.risk_hard_stop is False
        assert decision.risk_reasons == []
        assert decision.guard_state == GuardState.RUNNING

    def test_hard_stop_propagated(self):
        ev = _make_evaluator()
        decision = ev.build_runtime_risk_decision(
            daily_loss_pct=_D("0.10"),
            drawdown_pct=_ZERO,
            base_pct_gross=_D("0.50"),
            turnover_x=_D("1"),
            projected_total_quote=_D("100"),
            is_perp=False,
            margin_ratio=_D("1"),
            startup_position_sync_done=True,
            position_drift_pct=_ZERO,
            order_book_stale=False,
            pending_eod_close=False,
            guard_state=GuardState.SOFT_PAUSE,
        )
        assert decision.risk_hard_stop is True
        assert "daily_loss_hard_limit" in decision.risk_reasons


# ------------------------------------------------------------------
# edge_gate_update (stateful hysteresis)
# ------------------------------------------------------------------

class TestEdgeGateUpdate:
    def test_initially_unblocked(self):
        ev = _make_evaluator(edge_state_hold_s=10)
        assert ev.edge_gate_blocked is False

    def test_blocks_below_threshold_after_hold(self):
        ev = _make_evaluator(edge_state_hold_s=5)
        ev.edge_gate_update(100.0, _D("-0.01"), _D("0.001"), _D("0.002"))
        assert ev.edge_gate_blocked is False
        ev.edge_gate_update(106.0, _D("-0.01"), _D("0.001"), _D("0.002"))
        assert ev.edge_gate_blocked is True

    def test_no_block_within_hold_period(self):
        ev = _make_evaluator(edge_state_hold_s=10)
        ev.edge_gate_update(100.0, _D("-0.01"), _D("0.001"), _D("0.002"))
        assert ev.edge_gate_blocked is False
        ev.edge_gate_update(104.0, _D("-0.01"), _D("0.001"), _D("0.002"))
        assert ev.edge_gate_blocked is False

    def test_unblock_above_resume_after_hold(self):
        ev = _make_evaluator(edge_state_hold_s=5)
        ev.edge_gate_update(100.0, _D("-0.01"), _D("0.001"), _D("0.002"))
        ev.edge_gate_update(106.0, _D("-0.01"), _D("0.001"), _D("0.002"))
        assert ev.edge_gate_blocked is True

        ev.edge_gate_update(107.0, _D("0.005"), _D("0.001"), _D("0.002"))
        assert ev.edge_gate_blocked is True

        ev.edge_gate_update(112.0, _D("0.005"), _D("0.001"), _D("0.002"))
        assert ev.edge_gate_blocked is False

    def test_no_unblock_if_edge_below_resume(self):
        ev = _make_evaluator(edge_state_hold_s=5)
        ev.edge_gate_update(100.0, _D("-0.01"), _D("0.001"), _D("0.002"))
        ev.edge_gate_update(106.0, _D("-0.01"), _D("0.001"), _D("0.002"))
        assert ev.edge_gate_blocked is True

        ev.edge_gate_update(112.0, _D("0.0015"), _D("0.001"), _D("0.002"))
        assert ev.edge_gate_blocked is True

    def test_hold_floor_is_5_seconds(self):
        ev = _make_evaluator(edge_state_hold_s=0)
        ev.edge_gate_update(100.0, _D("-0.01"), _D("0.001"), _D("0.002"))
        ev.edge_gate_update(104.0, _D("-0.01"), _D("0.001"), _D("0.002"))
        assert ev.edge_gate_blocked is False
        ev.edge_gate_update(106.0, _D("-0.01"), _D("0.001"), _D("0.002"))
        assert ev.edge_gate_blocked is True

    def test_reset_clears_state(self):
        ev = _make_evaluator(edge_state_hold_s=5)
        ev.edge_gate_update(100.0, _D("-0.01"), _D("0.001"), _D("0.002"))
        ev.edge_gate_update(106.0, _D("-0.01"), _D("0.001"), _D("0.002"))
        assert ev.edge_gate_blocked is True

        ev.reset_edge_gate(now_ts=200.0)
        assert ev.edge_gate_blocked is False
