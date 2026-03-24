"""Tests for quoting mixin — spread computation, order sizing, level management.

Uses importorskip for HB-dependent tests since the kernel controller
imports hummingbot framework types.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

hb = pytest.importorskip("hummingbot", reason="hummingbot required for kernel tests")


class TestGetLevelsToExecute:
    def test_empty_when_derisk_taker_active(self):
        from controllers.runtime.kernel.quoting_mixin import QuotingMixin

        ctrl = MagicMock()
        ctrl._force_derisk_taker = True
        ctrl._recovery_close_emitted = False
        result = QuotingMixin.get_levels_to_execute(ctrl)
        assert result == []

    def test_empty_when_recovery_close_emitted(self):
        from controllers.runtime.kernel.quoting_mixin import QuotingMixin

        ctrl = MagicMock()
        ctrl._force_derisk_taker = False
        ctrl._recovery_close_emitted = True
        result = QuotingMixin.get_levels_to_execute(ctrl)
        assert result == []

    def test_respects_max_active_executors(self):
        from controllers.runtime.kernel.quoting_mixin import QuotingMixin

        ctrl = MagicMock()
        ctrl._force_derisk_taker = False
        ctrl._recovery_close_emitted = False
        ctrl.config.max_active_executors = 2
        ctrl.config.selective_quoting_enabled = False
        ctrl.config.level_cooldown_s = 0.0
        ctrl._recently_issued_levels = {}
        ctrl._open_order_level_ids = set()
        ctrl.market_data_provider.time.return_value = 1000.0
        active = [MagicMock(is_active=True, custom_info={"level_id": f"L{i}"}) for i in range(2)]
        ctrl.filter_executors.return_value = active
        result = QuotingMixin.get_levels_to_execute(ctrl)
        assert len(result) == 0


class TestDelegateAPIs:
    def test_build_runtime_execution_plan_delegates(self):
        from controllers.runtime.kernel.quoting_mixin import QuotingMixin

        ctrl = MagicMock()
        adapter = MagicMock()
        adapter.build_execution_plan.return_value = "plan"
        with patch("controllers.runtime.kernel.quoting_mixin._runtime_family_adapter", return_value=adapter):
            result = QuotingMixin.build_runtime_execution_plan(ctrl, MagicMock())
            assert result == "plan"

    def test_get_executor_config_delegates(self):
        from controllers.runtime.kernel.quoting_mixin import QuotingMixin

        ctrl = MagicMock()
        adapter = MagicMock()
        adapter.get_executor_config.return_value = "config_obj"
        with patch("controllers.runtime.kernel.quoting_mixin._runtime_family_adapter", return_value=adapter):
            result = QuotingMixin.get_executor_config(ctrl, "buy_0", Decimal("50000"), Decimal("0.001"))
            assert result == "config_obj"

    def test_get_price_and_amount_delegates(self):
        from controllers.runtime.kernel.quoting_mixin import QuotingMixin

        ctrl = MagicMock()
        adapter = MagicMock()
        adapter.get_price_and_amount.return_value = (Decimal("50000"), Decimal("0.001"))
        with patch("controllers.runtime.kernel.quoting_mixin._runtime_family_adapter", return_value=adapter):
            price, amount = QuotingMixin.get_price_and_amount(ctrl, "buy_0")
            assert price == Decimal("50000")
            assert amount == Decimal("0.001")
