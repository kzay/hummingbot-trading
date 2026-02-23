from controllers.ops_guard import GuardState, OpsGuard, OpsSnapshot


def _snapshot(**overrides):
    base = {
        "connector_ready": True,
        "balances_consistent": True,
        "cancel_fail_streak": 0,
        "edge_gate_blocked": False,
        "high_vol": False,
        "market_spread_too_small": False,
        "risk_reasons": [],
        "risk_hard_stop": False,
    }
    base.update(overrides)
    return OpsSnapshot(**base)


def test_running_when_all_ok():
    guard = OpsGuard()
    state = guard.update(_snapshot())
    assert state == GuardState.RUNNING
    assert guard.reasons == []


def test_soft_pause_on_connector_not_ready():
    guard = OpsGuard()
    state = guard.update(_snapshot(connector_ready=False))
    assert state == GuardState.SOFT_PAUSE
    assert "connector_not_ready" in guard.reasons


def test_hard_stop_on_cancel_fail_streak():
    guard = OpsGuard(hard_stop_cancel_fail_streak=3)
    state = guard.update(_snapshot(cancel_fail_streak=3))
    assert state == GuardState.HARD_STOP
    assert "cancel_fail_hard_limit" in guard.reasons


def test_hard_stop_on_risk_hard_stop():
    guard = OpsGuard()
    state = guard.update(_snapshot(risk_hard_stop=True, risk_reasons=["daily_loss_hard_limit"]))
    assert state == GuardState.HARD_STOP
    assert "daily_loss_hard_limit" in guard.reasons


def test_operational_pause_escalation():
    guard = OpsGuard(max_operational_pause_cycles=3)
    assert guard.update(_snapshot(connector_ready=False)) == GuardState.SOFT_PAUSE
    assert guard.update(_snapshot(connector_ready=False)) == GuardState.SOFT_PAUSE
    assert guard.update(_snapshot(connector_ready=False)) == GuardState.HARD_STOP


def test_force_hard_stop():
    guard = OpsGuard()
    state = guard.force_hard_stop("external_kill_switch")
    assert state == GuardState.HARD_STOP
    assert guard.reasons == ["external_kill_switch"]
