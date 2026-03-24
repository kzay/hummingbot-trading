from decimal import Decimal

import pytest

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


# ------------------------------------------------------------------
# Parametrized boundary tests
# ------------------------------------------------------------------

@pytest.mark.parametrize("daily_loss,expect_hard", [
    (Decimal("0"), False),
    (Decimal("0.029"), False),
    (Decimal("0.03"), False),
    (Decimal("0.031"), True),
    (Decimal("0.10"), True),
])
def test_daily_loss_boundary(daily_loss, expect_hard):
    rp = _policy()
    reasons, hard = rp.check_risk(Decimal("0.5"), Decimal("1"), Decimal("100"), daily_loss, Decimal("0"))
    assert hard is expect_hard
    if expect_hard:
        assert "daily_loss_hard_limit" in reasons


@pytest.mark.parametrize("drawdown,expect_hard", [
    (Decimal("0"), False),
    (Decimal("0.049"), False),
    (Decimal("0.05"), False),
    (Decimal("0.051"), True),
    (Decimal("0.20"), True),
])
def test_drawdown_boundary(drawdown, expect_hard):
    rp = _policy()
    reasons, hard = rp.check_risk(Decimal("0.5"), Decimal("1"), Decimal("100"), Decimal("0"), drawdown)
    assert hard is expect_hard
    if expect_hard:
        assert "drawdown_hard_limit" in reasons


@pytest.mark.parametrize("turnover,expect_hard", [
    (Decimal("0"), False),
    (Decimal("5.9"), False),
    (Decimal("6.0"), False),
    (Decimal("6.01"), True),
    (Decimal("20"), True),
])
def test_turnover_boundary(turnover, expect_hard):
    rp = _policy()
    reasons, hard = rp.check_risk(Decimal("0.5"), turnover, Decimal("100"), Decimal("0"), Decimal("0"))
    assert hard is expect_hard
    if expect_hard:
        assert "daily_turnover_hard_limit" in reasons


@pytest.mark.parametrize("base_pct,reason", [
    (Decimal("0"), "base_pct_below_min"),
    (Decimal("0.14"), "base_pct_below_min"),
    (Decimal("0.15"), None),
    (Decimal("0.50"), None),
    (Decimal("0.90"), None),
    (Decimal("0.91"), "base_pct_above_max"),
    (Decimal("1.00"), "base_pct_above_max"),
])
def test_base_pct_boundary(base_pct, reason):
    rp = _policy()
    reasons, _ = rp.check_risk(base_pct, Decimal("1"), Decimal("100"), Decimal("0"), Decimal("0"))
    if reason:
        assert reason in reasons
    else:
        assert not any(r.startswith("base_pct") for r in reasons)


@pytest.mark.parametrize("notional,expect_cap", [
    (Decimal("999"), False),
    (Decimal("1000"), False),
    (Decimal("1001"), True),
])
def test_projected_notional_boundary(notional, expect_cap):
    rp = _policy()
    reasons, _ = rp.check_risk(Decimal("0.5"), Decimal("1"), notional, Decimal("0"), Decimal("0"))
    if expect_cap:
        assert "projected_total_quote_above_cap" in reasons
    else:
        assert "projected_total_quote_above_cap" not in reasons


@pytest.mark.parametrize("equity,equity_open,equity_peak,exp_loss,exp_dd", [
    (Decimal("1000"), Decimal("1000"), Decimal("1000"), Decimal("0"), Decimal("0")),
    (Decimal("1100"), Decimal("1000"), Decimal("1100"), Decimal("0"), Decimal("0")),
    (Decimal("1100"), Decimal("1000"), Decimal("1000"), Decimal("0"), Decimal("0")),
    (Decimal("500"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")),
])
def test_loss_metrics_boundaries(equity, equity_open, equity_peak, exp_loss, exp_dd):
    loss, dd = RiskPolicy.loss_metrics(equity, equity_open, equity_peak)
    assert loss == exp_loss
    assert dd == exp_dd
