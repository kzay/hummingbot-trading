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


def test_cancel_fail_hard_stop_resets_operational_counter():
    """Counter must reset on HARD_STOP so recovery doesn't re-escalate."""
    guard = OpsGuard(max_operational_pause_cycles=3, hard_stop_cancel_fail_streak=3)
    # Accumulate 2 operational pause cycles
    guard.update(_snapshot(connector_ready=False))
    guard.update(_snapshot(connector_ready=False))
    assert guard._operational_pause_cycles == 2
    # HARD_STOP via cancel-fail should reset counter
    guard.update(_snapshot(cancel_fail_streak=3))
    assert guard.state == GuardState.HARD_STOP
    assert guard._operational_pause_cycles == 0


def test_risk_hard_stop_resets_operational_counter():
    guard = OpsGuard(max_operational_pause_cycles=3)
    guard.update(_snapshot(connector_ready=False))
    assert guard._operational_pause_cycles == 1
    guard.update(_snapshot(risk_hard_stop=True, risk_reasons=["daily_loss"]))
    assert guard.state == GuardState.HARD_STOP
    assert guard._operational_pause_cycles == 0


def test_force_hard_stop_resets_operational_counter():
    guard = OpsGuard(max_operational_pause_cycles=3)
    guard.update(_snapshot(connector_ready=False))
    guard.update(_snapshot(connector_ready=False))
    assert guard._operational_pause_cycles == 2
    guard.force_hard_stop("manual")
    assert guard._operational_pause_cycles == 0


def test_clean_recovery_after_hard_stop():
    """After HARD_STOP + recovery, operational counter should be fresh."""
    guard = OpsGuard(max_operational_pause_cycles=3, hard_stop_cancel_fail_streak=3)
    guard.update(_snapshot(connector_ready=False))
    guard.update(_snapshot(connector_ready=False))
    guard.update(_snapshot(cancel_fail_streak=3))
    assert guard.state == GuardState.HARD_STOP
    # Recovery: all ok
    guard.update(_snapshot())
    assert guard.state == GuardState.RUNNING
    # Now 2 operational pauses should NOT escalate (counter was reset)
    guard.update(_snapshot(connector_ready=False))
    guard.update(_snapshot(connector_ready=False))
    assert guard.state == GuardState.SOFT_PAUSE
    assert guard._operational_pause_cycles == 2
