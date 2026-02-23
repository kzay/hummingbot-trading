from decimal import Decimal

from controllers.risk_policy import RiskPolicy


def _policy(**overrides) -> RiskPolicy:
    defaults = dict(
        min_base_pct=Decimal("0.15"),
        max_base_pct=Decimal("0.90"),
        max_total_notional_quote=Decimal("1000"),
        max_daily_turnover_x_hard=Decimal("6.0"),
        max_daily_loss_pct_hard=Decimal("0.03"),
        max_drawdown_pct_hard=Decimal("0.05"),
        edge_state_hold_s=60,
    )
    defaults.update(overrides)
    return RiskPolicy(**defaults)


def test_no_risk_issues_when_within_limits():
    rp = _policy()
    reasons, hard = rp.check_risk(
        base_pct=Decimal("0.5"),
        turnover_x=Decimal("1.0"),
        projected_total_quote=Decimal("500"),
        daily_loss_pct=Decimal("0.01"),
        drawdown_pct=Decimal("0.02"),
    )
    assert reasons == []
    assert hard is False


def test_daily_loss_triggers_hard_stop():
    rp = _policy()
    reasons, hard = rp.check_risk(
        base_pct=Decimal("0.5"),
        turnover_x=Decimal("1.0"),
        projected_total_quote=Decimal("500"),
        daily_loss_pct=Decimal("0.04"),
        drawdown_pct=Decimal("0.02"),
    )
    assert "daily_loss_hard_limit" in reasons
    assert hard is True


def test_drawdown_triggers_hard_stop():
    rp = _policy()
    reasons, hard = rp.check_risk(
        base_pct=Decimal("0.5"),
        turnover_x=Decimal("1.0"),
        projected_total_quote=Decimal("500"),
        daily_loss_pct=Decimal("0.01"),
        drawdown_pct=Decimal("0.06"),
    )
    assert "drawdown_hard_limit" in reasons
    assert hard is True


def test_turnover_triggers_hard_stop():
    rp = _policy()
    reasons, hard = rp.check_risk(
        base_pct=Decimal("0.5"),
        turnover_x=Decimal("7.0"),
        projected_total_quote=Decimal("500"),
        daily_loss_pct=Decimal("0"),
        drawdown_pct=Decimal("0"),
    )
    assert "daily_turnover_hard_limit" in reasons
    assert hard is True


def test_base_pct_below_min_is_soft_warning():
    rp = _policy()
    reasons, hard = rp.check_risk(
        base_pct=Decimal("0.10"),
        turnover_x=Decimal("1.0"),
        projected_total_quote=Decimal("500"),
        daily_loss_pct=Decimal("0"),
        drawdown_pct=Decimal("0"),
    )
    assert "base_pct_below_min" in reasons
    assert hard is False


def test_loss_metrics_computation():
    daily_loss, drawdown = RiskPolicy.loss_metrics(
        equity_quote=Decimal("9500"),
        daily_equity_open=Decimal("10000"),
        daily_equity_peak=Decimal("10200"),
    )
    assert daily_loss == Decimal("0.05")
    expected_dd = (Decimal("10200") - Decimal("9500")) / Decimal("10200")
    assert drawdown == expected_dd


def test_edge_gate_blocks_on_low_edge():
    rp = _policy(edge_state_hold_s=0)
    rp._edge_gate_changed_ts = 90.0
    rp.edge_gate_update(100.0, Decimal("-0.001"), Decimal("0.0002"), Decimal("0.0003"))
    assert rp.edge_gate_blocked is True


def test_edge_gate_unblocks_on_high_edge():
    rp = _policy(edge_state_hold_s=0)
    rp._edge_gate_blocked = True
    rp._edge_gate_changed_ts = 90.0
    rp.edge_gate_update(100.0, Decimal("0.001"), Decimal("0.0002"), Decimal("0.0003"))
    assert rp.edge_gate_blocked is False


def test_edge_gate_holds_during_timer():
    rp = _policy(edge_state_hold_s=60)
    rp._edge_gate_changed_ts = 90.0
    rp.edge_gate_update(100.0, Decimal("-0.001"), Decimal("0.0002"), Decimal("0.0003"))
    assert rp.edge_gate_blocked is False
