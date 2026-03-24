"""Tests for the shared PositionRecoveryGuard module."""
from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

from controllers.position_recovery import PositionRecoveryGuard

_ZERO = Decimal("0")


# ── Unit tests for guard barrier logic ───────────────────────────────


class TestGuardLongPosition:
    """SL/TP/time evaluation for a long position."""

    def _make_guard(self, **overrides) -> PositionRecoveryGuard:
        defaults = dict(
            position_base=Decimal("0.001"),
            avg_entry_price=Decimal("80000"),
            stop_loss_pct=Decimal("0.003"),
            take_profit_pct=Decimal("0.005"),
            time_limit_s=600,
            last_fill_ts=1000.0,
            activated_at=1000.0,
            connector_name="bitget_perpetual_paper_trade",
            trading_pair="BTC-USDT",
            leverage=5,
        )
        defaults.update(overrides)
        return PositionRecoveryGuard(**defaults)

    def test_sl_price_computed_correctly(self):
        g = self._make_guard()
        assert g.sl_price == Decimal("80000") * (1 - Decimal("0.003"))
        assert g.is_long is True

    def test_tp_price_computed_correctly(self):
        g = self._make_guard()
        assert g.tp_price == Decimal("80000") * (1 + Decimal("0.005"))

    def test_no_trigger_when_price_within_range(self):
        g = self._make_guard()
        assert g.check(Decimal("80000"), 1100.0) is None

    def test_sl_triggers_when_price_below(self):
        g = self._make_guard()
        assert g.check(Decimal("79700"), 1100.0) == "recovery_stop_loss"

    def test_tp_triggers_when_price_above(self):
        g = self._make_guard()
        assert g.check(Decimal("80500"), 1100.0) == "recovery_take_profit"

    def test_time_limit_triggers(self):
        g = self._make_guard()
        assert g.check(Decimal("80000"), 1700.0) == "recovery_time_limit"

    def test_time_limit_not_triggered_within_window(self):
        g = self._make_guard()
        assert g.check(Decimal("80000"), 1500.0) is None

    def test_no_trigger_after_close_triggered(self):
        g = self._make_guard()
        g.mark_close_triggered()
        assert g.check(Decimal("79700"), 1100.0) is None

    def test_no_trigger_after_deactivated(self):
        g = self._make_guard()
        g.deactivate("test")
        assert g.check(Decimal("79700"), 1100.0) is None

    def test_no_trigger_on_zero_mid(self):
        g = self._make_guard()
        assert g.check(_ZERO, 1100.0) is None


class TestGuardShortPosition:
    """SL/TP/time evaluation for a short position."""

    def _make_guard(self, **overrides) -> PositionRecoveryGuard:
        defaults = dict(
            position_base=Decimal("-0.001"),
            avg_entry_price=Decimal("80000"),
            stop_loss_pct=Decimal("0.003"),
            take_profit_pct=Decimal("0.005"),
            time_limit_s=600,
            last_fill_ts=1000.0,
            activated_at=1000.0,
            connector_name="bitget_perpetual_paper_trade",
            trading_pair="BTC-USDT",
            leverage=5,
        )
        defaults.update(overrides)
        return PositionRecoveryGuard(**defaults)

    def test_sl_price_computed_for_short(self):
        g = self._make_guard()
        assert g.sl_price == Decimal("80000") * (1 + Decimal("0.003"))
        assert g.is_long is False

    def test_tp_price_computed_for_short(self):
        g = self._make_guard()
        assert g.tp_price == Decimal("80000") * (1 - Decimal("0.005"))

    def test_no_trigger_within_range(self):
        g = self._make_guard()
        assert g.check(Decimal("80000"), 1100.0) is None

    def test_sl_triggers_when_price_above(self):
        g = self._make_guard()
        assert g.check(Decimal("80300"), 1100.0) == "recovery_stop_loss"

    def test_tp_triggers_when_price_below(self):
        g = self._make_guard()
        assert g.check(Decimal("79500"), 1100.0) == "recovery_take_profit"

    def test_time_limit_triggers(self):
        g = self._make_guard()
        assert g.check(Decimal("80000"), 1700.0) == "recovery_time_limit"


class TestGuardOptionalBarriers:
    """Guard behaviour when some barriers are disabled (None/0)."""

    def test_no_sl_configured(self):
        g = PositionRecoveryGuard(
            position_base=Decimal("0.001"),
            avg_entry_price=Decimal("80000"),
            stop_loss_pct=None,
            take_profit_pct=Decimal("0.005"),
            time_limit_s=None,
            last_fill_ts=1000.0,
            connector_name="test",
            trading_pair="BTC-USDT",
            leverage=1,
        )
        assert g.sl_price is None
        assert g.check(Decimal("10000"), 1100.0) is None

    def test_no_tp_configured(self):
        g = PositionRecoveryGuard(
            position_base=Decimal("0.001"),
            avg_entry_price=Decimal("80000"),
            stop_loss_pct=Decimal("0.003"),
            take_profit_pct=None,
            time_limit_s=None,
            last_fill_ts=1000.0,
            connector_name="test",
            trading_pair="BTC-USDT",
            leverage=1,
        )
        assert g.tp_price is None
        assert g.check(Decimal("100000"), 1100.0) is None

    def test_no_time_limit_configured(self):
        g = PositionRecoveryGuard(
            position_base=Decimal("0.001"),
            avg_entry_price=Decimal("80000"),
            stop_loss_pct=None,
            take_profit_pct=None,
            time_limit_s=None,
            last_fill_ts=1000.0,
            connector_name="test",
            trading_pair="BTC-USDT",
            leverage=1,
        )
        assert g.check(Decimal("80000"), 999999.0) is None

    def test_zero_entry_price_skips_barriers(self):
        g = PositionRecoveryGuard(
            position_base=Decimal("0.001"),
            avg_entry_price=_ZERO,
            stop_loss_pct=Decimal("0.003"),
            take_profit_pct=Decimal("0.005"),
            time_limit_s=None,
            last_fill_ts=1000.0,
            connector_name="test",
            trading_pair="BTC-USDT",
            leverage=1,
        )
        assert g.sl_price is None
        assert g.tp_price is None


class TestGuardLifecycle:
    """Deactivation and summary behaviour."""

    def test_deactivate_sets_inactive(self):
        g = PositionRecoveryGuard(
            position_base=Decimal("0.001"),
            avg_entry_price=Decimal("80000"),
            stop_loss_pct=Decimal("0.003"),
            take_profit_pct=Decimal("0.005"),
            time_limit_s=600,
            last_fill_ts=1000.0,
            connector_name="test",
            trading_pair="BTC-USDT",
            leverage=1,
        )
        assert g.active is True
        g.deactivate("test_reason")
        assert g.active is False

    def test_double_deactivate_is_noop(self):
        g = PositionRecoveryGuard(
            position_base=Decimal("0.001"),
            avg_entry_price=Decimal("80000"),
            stop_loss_pct=Decimal("0.003"),
            take_profit_pct=Decimal("0.005"),
            time_limit_s=600,
            last_fill_ts=1000.0,
            connector_name="test",
            trading_pair="BTC-USDT",
            leverage=1,
        )
        g.deactivate("first")
        g.deactivate("second")
        assert g.active is False

    def test_summary_returns_dict(self):
        g = PositionRecoveryGuard(
            position_base=Decimal("0.001"),
            avg_entry_price=Decimal("80000"),
            stop_loss_pct=Decimal("0.003"),
            take_profit_pct=Decimal("0.005"),
            time_limit_s=600,
            last_fill_ts=1000.0,
            connector_name="test",
            trading_pair="BTC-USDT",
            leverage=1,
        )
        s = g.summary()
        assert isinstance(s, dict)
        assert s["active"] is True
        assert s["close_triggered"] is False
        assert s["position"] == 0.001
        assert s["sl_price"] is not None
        assert s["tp_price"] is not None

    def test_last_fill_ts_fallback_to_activated_at(self):
        g = PositionRecoveryGuard(
            position_base=Decimal("0.001"),
            avg_entry_price=Decimal("80000"),
            stop_loss_pct=None,
            take_profit_pct=None,
            time_limit_s=600,
            last_fill_ts=0.0,
            connector_name="test",
            trading_pair="BTC-USDT",
            leverage=1,
        )
        assert g.last_fill_ts == g.activated_at


# ── Mixin integration tests (no HB dependency) ──────────────────────


class _FakeTripleBarrier:
    stop_loss = Decimal("0.003")
    take_profit = Decimal("0.005")
    time_limit = 1800


class _FakeConfig:
    position_recovery_enabled = True
    triple_barrier_config = _FakeTripleBarrier()
    connector_name = "bitget_perpetual_paper_trade"
    trading_pair = "BTC-USDT"
    leverage = 5
    id = "test-ctrl"


class _FakeExecutorInfo:
    def __init__(self, *, is_active: bool = True, is_trading: bool = False, level_id: str = "buy_0", executor_id: str = "ex-1"):
        self.is_active = is_active
        self.is_trading = is_trading
        self.custom_info = {"level_id": level_id}
        self.id = executor_id


class _MixinHarness:
    """Minimal harness exposing PositionMixin methods without full SharedRuntimeKernel."""

    def __init__(self):
        from controllers.position_mixin import PositionMixin
        self.config = _FakeConfig()
        self._position_base = Decimal("0.001")
        self._avg_entry_price = Decimal("80000")
        self._last_fill_ts = 5000.0
        self._recovery_guard = None
        self._recovery_close_emitted = False
        self.executors_info = []
        self._mixin = PositionMixin()

    def filter_executors(self, executors, filter_func):
        return [x for x in executors if filter_func(x)]

    def _quantize_amount(self, amount):
        return amount

    def _get_reference_price(self):
        return Decimal("80000")

    def init_guard(self):
        from controllers.position_mixin import PositionMixin
        PositionMixin._init_recovery_guard(self)

    def build_close_action_raw(self):
        """Call _recovery_close_action without HB imports (just test gating logic)."""
        from controllers.position_mixin import PositionMixin
        return PositionMixin._recovery_close_action(self)


class TestMixinInitRecoveryGuard:
    """Integration tests for _init_recovery_guard in PositionMixin."""

    def test_uses_persisted_last_fill_ts(self):
        h = _MixinHarness()
        h._last_fill_ts = 42000.0
        h.init_guard()
        assert h._recovery_guard is not None
        assert h._recovery_guard.last_fill_ts == 42000.0

    def test_falls_back_to_now_when_no_persisted_ts(self):
        h = _MixinHarness()
        h._last_fill_ts = 0.0
        h.init_guard()
        assert h._recovery_guard is not None
        assert h._recovery_guard.last_fill_ts > 0

    def test_skipped_when_close_already_emitted(self):
        h = _MixinHarness()
        h._recovery_close_emitted = True
        h.init_guard()
        assert h._recovery_guard is None

    def test_skipped_when_active_executors_exist(self):
        h = _MixinHarness()
        h.executors_info = [_FakeExecutorInfo(is_active=True)]
        h.init_guard()
        assert h._recovery_guard is None

    def test_skipped_when_position_flat(self):
        h = _MixinHarness()
        h._position_base = _ZERO
        h.init_guard()
        assert h._recovery_guard is None

    def test_skipped_when_disabled_by_config(self):
        h = _MixinHarness()
        h.config.position_recovery_enabled = False
        h.init_guard()
        assert h._recovery_guard is None

    def test_no_barriers_still_creates_guard(self):
        """Guard is created even with zero barriers (DESIGN-4 logs warning but doesn't block)."""
        h = _MixinHarness()
        h.config.triple_barrier_config = type("TBC", (), {"stop_loss": None, "take_profit": None, "time_limit": None})()
        h.init_guard()
        assert h._recovery_guard is not None
        assert h._recovery_guard.sl_price is None
        assert h._recovery_guard.tp_price is None
        assert h._recovery_guard.time_limit_s is None


class TestMixinCloseActionUsesLivePosition:
    """BUG-1: _recovery_close_action must use self._position_base, not guard snapshot."""

    def test_close_returns_none_when_position_flat_at_close_time(self):
        h = _MixinHarness()
        h.init_guard()
        assert h._recovery_guard is not None
        h._recovery_close_emitted = True
        h._position_base = _ZERO
        result = h.build_close_action_raw()
        assert result is None

    def test_close_returns_none_when_not_emitted(self):
        h = _MixinHarness()
        h.init_guard()
        h._recovery_close_emitted = False
        result = h.build_close_action_raw()
        assert result is None


# ── Regression: time_limit measured from restart, not last_fill_ts ───


def test_time_limit_uses_activated_at_not_last_fill_ts():
    """BUG-FIX: time_limit must be measured from activated_at (restart time),
    not last_fill_ts (which could be hours old from the previous session).

    Scenario: position last filled 9 hours ago, restarted now, time_limit=2400s.
    The guard must NOT fire immediately on first tick just because
    (now - last_fill_ts) >> time_limit_s.
    """
    nine_hours = 9 * 3600
    activated = 100_000.0
    old_fill_ts = activated - nine_hours  # fill was 9 hours before restart

    g = PositionRecoveryGuard(
        position_base=Decimal("0.001"),
        avg_entry_price=Decimal("80000"),
        stop_loss_pct=Decimal("0.003"),
        take_profit_pct=Decimal("0.005"),
        time_limit_s=2400,
        last_fill_ts=old_fill_ts,
        activated_at=activated,
        connector_name="test",
        trading_pair="BTC-USDT",
        leverage=1,
    )

    # First tick right after restart — must NOT fire despite stale fill_ts
    assert g.check(Decimal("80000"), activated + 1.0) is None

    # Still within window at 2399s
    assert g.check(Decimal("80000"), activated + 2399.0) is None

    # At 2401s after restart, time_limit fires
    assert g.check(Decimal("80000"), activated + 2401.0) == "recovery_time_limit"


# ── Isolation contract ────────────────────────────────────────────────


def test_position_recovery_does_not_import_bot_lanes():
    """position_recovery.py must remain strategy-agnostic."""
    path = Path(__file__).resolve().parents[2] / "controllers" / "position_recovery.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    bad = [m for m in modules if m.startswith("controllers.bots.")]
    assert not bad, f"position_recovery.py must not import bot lanes: {bad}"


def test_position_mixin_does_not_import_bot_lanes():
    """position_mixin.py must remain strategy-agnostic."""
    path = Path(__file__).resolve().parents[2] / "controllers" / "position_mixin.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    bad = [m for m in modules if m.startswith("controllers.bots.")]
    assert not bad, f"position_mixin.py must not import bot lanes: {bad}"
