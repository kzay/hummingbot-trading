"""Tests for risk guard mechanisms in the runtime kernel supervisory mixin.

Uses importorskip for HB-dependent tests since the kernel controller
imports hummingbot framework types.
"""
from __future__ import annotations

import time
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

hb = pytest.importorskip("hummingbot", reason="hummingbot required for kernel tests")


def _make_controller():
    """Build a minimal controller with supervisory mixin attributes."""
    from controllers.runtime.kernel.config import EppV24Config
    from controllers.runtime.kernel.supervisory_mixin import SupervisoryMixin

    ctrl = MagicMock(spec=SupervisoryMixin)
    ctrl._external_soft_pause = False
    ctrl._external_pause_reason = ""
    ctrl._last_intent_ts = 0.0
    ctrl._last_intent_action = ""
    ctrl._last_intent_source = ""
    ctrl._regime_override = None
    ctrl._regime_override_expires_ts = 0.0
    ctrl._ml_regime = None
    ctrl._ml_direction_hint = None
    ctrl._ml_direction_hint_confidence = Decimal("0")
    ctrl._ml_direction_hint_expires_ts = 0.0
    ctrl._ml_sizing_hint = None
    ctrl._ml_sizing_hint_expires_ts = 0.0
    ctrl._target_base_pct_override = None
    ctrl._target_base_pct_override_expires_ts = 0.0
    ctrl._daily_pnl_target_pct_override = None
    ctrl._daily_pnl_target_pct_override_expires_ts = 0.0
    ctrl.force_hard_stop = False
    ctrl.market_data_provider = MagicMock()
    ctrl.market_data_provider.time.return_value = time.time()
    ctrl.config = MagicMock()
    ctrl.config.id = "test_ctrl"
    ctrl.config.trading_pair = "BTC-USDT"
    ctrl.config.instance_name = "bot1"
    return ctrl


class TestSoftPause:
    def test_set_external_soft_pause_activates(self):
        from controllers.runtime.kernel.supervisory_mixin import SupervisoryMixin

        ctrl = _make_controller()
        SupervisoryMixin.set_external_soft_pause(ctrl, True, "test_reason")
        assert ctrl._external_soft_pause is True
        assert ctrl._external_pause_reason == "test_reason"

    def test_set_external_soft_pause_deactivates(self):
        from controllers.runtime.kernel.supervisory_mixin import SupervisoryMixin

        ctrl = _make_controller()
        SupervisoryMixin.set_external_soft_pause(ctrl, True, "test")
        SupervisoryMixin.set_external_soft_pause(ctrl, False, "")
        assert ctrl._external_soft_pause is False

    def test_soft_pause_default_reason(self):
        from controllers.runtime.kernel.supervisory_mixin import SupervisoryMixin

        ctrl = _make_controller()
        SupervisoryMixin.set_external_soft_pause(ctrl, True, "")
        assert ctrl._external_pause_reason == "external_intent"


class TestExecutionIntent:
    def test_soft_pause_intent(self):
        from controllers.runtime.kernel.supervisory_mixin import SupervisoryMixin

        ctrl = _make_controller()
        ok, msg = SupervisoryMixin.apply_execution_intent(ctrl, {"action": "soft_pause"})
        assert ok is True
        assert ctrl._external_soft_pause is True

    def test_resume_intent(self):
        from controllers.runtime.kernel.supervisory_mixin import SupervisoryMixin

        ctrl = _make_controller()
        ctrl._external_soft_pause = True
        ok, msg = SupervisoryMixin.apply_execution_intent(ctrl, {"action": "resume"})
        assert ok is True
        assert ctrl._external_soft_pause is False

    def test_unsupported_action_returns_false(self):
        from controllers.runtime.kernel.supervisory_mixin import SupervisoryMixin

        ctrl = _make_controller()
        ok, msg = SupervisoryMixin.apply_execution_intent(ctrl, {"action": "nonexistent_action"})
        assert ok is False

    def test_set_target_base_pct_validates(self):
        from controllers.runtime.kernel.supervisory_mixin import SupervisoryMixin

        ctrl = _make_controller()
        ok, msg = SupervisoryMixin.apply_execution_intent(
            ctrl, {"action": "set_target_base_pct", "value": "0.5"}
        )
        assert ok is True

    def test_set_target_base_pct_rejects_invalid(self):
        from controllers.runtime.kernel.supervisory_mixin import SupervisoryMixin

        ctrl = _make_controller()
        ok, msg = SupervisoryMixin.apply_execution_intent(
            ctrl, {"action": "set_target_base_pct", "value": "not_a_number"}
        )
        assert ok is False

    def test_kill_switch_intent(self):
        from controllers.runtime.kernel.supervisory_mixin import SupervisoryMixin

        ctrl = _make_controller()
        ok, msg = SupervisoryMixin.apply_execution_intent(ctrl, {"action": "kill_switch"})
        assert ok is True
        assert ctrl.force_hard_stop is True

    def test_adverse_skip_tick_intent(self):
        from controllers.runtime.kernel.supervisory_mixin import SupervisoryMixin

        ctrl = _make_controller()
        ctrl._adverse_skip_until_ts = 0.0
        ok, msg = SupervisoryMixin.apply_execution_intent(ctrl, {"action": "adverse_skip_tick"})
        assert ok is True

    def test_multiple_soft_pause_resume_cycle(self):
        from controllers.runtime.kernel.supervisory_mixin import SupervisoryMixin

        ctrl = _make_controller()
        SupervisoryMixin.set_external_soft_pause(ctrl, True, "gate_a")
        assert ctrl._external_soft_pause is True
        SupervisoryMixin.set_external_soft_pause(ctrl, False, "")
        assert ctrl._external_soft_pause is False
        SupervisoryMixin.set_external_soft_pause(ctrl, True, "gate_b")
        assert ctrl._external_pause_reason == "gate_b"
