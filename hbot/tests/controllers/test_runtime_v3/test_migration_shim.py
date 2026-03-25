"""Tests for the v3 migration shim — per-bot extraction, shadow mode."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from controllers.runtime.v3.migration_shim import (
    ShadowComparator,
    StrategyMigrationShim,
)
from controllers.runtime.v3.signals import TelemetrySchema, TradingSignal
from controllers.runtime.v3.types import MarketSnapshot

_ZERO = Decimal("0")
_SNAP = MarketSnapshot(mid=Decimal("65000"))


def _mock_ctrl(**attrs):
    ctrl = MagicMock()
    for k, v in attrs.items():
        setattr(ctrl, k, v)
    return ctrl


# ── Bot1 extraction ──────────────────────────────────────────────────


class TestBot1Shim:
    def test_two_sided(self):
        ctrl = _mock_ctrl(
            _alpha_policy_state="maker_two_sided",
            _alpha_policy_reason="normal",
            _alpha_maker_score=Decimal("0.7"),
            _alpha_aggressive_score=_ZERO,
        )
        shim = StrategyMigrationShim(ctrl, "bot1")
        sig = shim.evaluate(_SNAP)

        assert sig.family == "mm_grid"
        assert sig.direction == "both"
        assert sig.conviction == Decimal("0.7")

    def test_no_trade(self):
        ctrl = _mock_ctrl(
            _alpha_policy_state="no_trade",
            _alpha_policy_reason="edge_blocked",
            _alpha_maker_score=_ZERO,
            _alpha_aggressive_score=_ZERO,
        )
        shim = StrategyMigrationShim(ctrl, "bot1")
        sig = shim.evaluate(_SNAP)

        assert sig.family == "no_trade"
        assert sig.reason == "edge_blocked"

    def test_bias_buy(self):
        ctrl = _mock_ctrl(
            _alpha_policy_state="maker_bias_buy",
            _alpha_policy_reason="skew",
            _alpha_maker_score=Decimal("0.6"),
            _alpha_aggressive_score=_ZERO,
        )
        shim = StrategyMigrationShim(ctrl, "bot1")
        sig = shim.evaluate(_SNAP)
        assert sig.direction == "buy"


# ── Bot5 extraction ──────────────────────────────────────────────────


class TestBot5Shim:
    def test_directional_signal(self):
        ctrl = _mock_ctrl(
            _bot5_flow_state={
                "direction": "buy",
                "conviction": Decimal("0.85"),
                "target_net_base_pct": Decimal("0.05"),
                "directional_allowed": True,
                "bias_active": True,
                "reason": "directional_buy",
            }
        )
        shim = StrategyMigrationShim(ctrl, "bot5")
        sig = shim.evaluate(_SNAP)

        assert sig.family == "hybrid"
        assert sig.direction == "buy"
        assert sig.conviction == Decimal("0.85")
        assert sig.target_net_base_pct == Decimal("0.05")

    def test_no_flow_state(self):
        ctrl = _mock_ctrl(_bot5_flow_state={})
        shim = StrategyMigrationShim(ctrl, "bot5")
        sig = shim.evaluate(_SNAP)
        assert sig.family == "no_trade"

    def test_off_direction(self):
        ctrl = _mock_ctrl(
            _bot5_flow_state={
                "direction": "off",
                "conviction": _ZERO,
                "directional_allowed": False,
                "bias_active": False,
                "reason": "no_flow",
            }
        )
        shim = StrategyMigrationShim(ctrl, "bot5")
        sig = shim.evaluate(_SNAP)
        assert sig.family == "no_trade"


# ── Bot6 extraction ──────────────────────────────────────────────────


class TestBot6Shim:
    def test_directional_signal(self):
        ctrl = _mock_ctrl(
            _bot6_signal_state={
                "direction": "sell",
                "directional_allowed": True,
                "active_score": 7,
                "target_net_base_pct": Decimal("-0.08"),
                "reason": "bearish_cvd_divergence",
            }
        )
        shim = StrategyMigrationShim(ctrl, "bot6")
        sig = shim.evaluate(_SNAP)

        assert sig.family == "directional"
        assert sig.direction == "sell"
        assert sig.conviction == Decimal("0.7")  # 7/10
        assert sig.target_net_base_pct == Decimal("-0.08")

    def test_no_signal(self):
        ctrl = _mock_ctrl(
            _bot6_signal_state={
                "direction": "off",
                "directional_allowed": False,
                "reason": "no_trend",
            }
        )
        shim = StrategyMigrationShim(ctrl, "bot6")
        sig = shim.evaluate(_SNAP)
        assert sig.family == "no_trade"


# ── Bot7 extraction ──────────────────────────────────────────────────


class TestBot7Shim:
    def test_active_pullback(self):
        ctrl = _mock_ctrl(
            _pb_state={
                "active": True,
                "side": "buy",
                "signal_score": Decimal("0.82"),
                "target_net_base_pct": Decimal("0.04"),
                "grid_levels": 2,
                "grid_spacing_pct": Decimal("0.001"),
                "reason": "pullback_buy",
            }
        )
        shim = StrategyMigrationShim(ctrl, "bot7")
        sig = shim.evaluate(_SNAP)

        assert sig.family == "directional"
        assert sig.direction == "buy"
        assert sig.conviction == Decimal("0.82")
        assert len(sig.levels) == 2
        assert sig.levels[0].side == "buy"

    def test_inactive(self):
        ctrl = _mock_ctrl(
            _pb_state={
                "active": False,
                "side": "off",
                "reason": "no_pullback_zone",
            }
        )
        shim = StrategyMigrationShim(ctrl, "bot7")
        sig = shim.evaluate(_SNAP)
        assert sig.family == "no_trade"
        assert sig.reason == "no_pullback_zone"


# ── Invalid bot ID ───────────────────────────────────────────────────


class TestInvalidBotId:
    def test_unknown_bot_raises(self):
        with pytest.raises(ValueError, match="No extractor"):
            StrategyMigrationShim(MagicMock(), "bot99")


# ── Shadow mode ──────────────────────────────────────────────────────


class _FakeNative:
    def evaluate(self, snap):
        return TradingSignal(
            family="directional",
            direction="buy",
            conviction=Decimal("0.80"),
        )

    def warmup_bars_required(self):
        return 100

    def telemetry_schema(self):
        return TelemetrySchema()


class TestShadowComparator:
    def test_no_divergence(self):
        ctrl = _mock_ctrl(
            _pb_state={
                "active": True,
                "side": "buy",
                "signal_score": Decimal("0.80"),
                "target_net_base_pct": _ZERO,
                "grid_levels": 1,
                "grid_spacing_pct": Decimal("0.001"),
                "reason": "test",
            }
        )
        shim = StrategyMigrationShim(ctrl, "bot7")
        native = _FakeNative()
        comparator = ShadowComparator(shim, native, instance_name="test")

        sig = comparator.evaluate(_SNAP)
        assert sig.family == "directional"  # Shim's signal
        assert comparator._divergent_ticks == 0

    def test_detects_conviction_divergence(self):
        ctrl = _mock_ctrl(
            _pb_state={
                "active": True,
                "side": "buy",
                "signal_score": Decimal("0.50"),  # Different from native 0.80
                "target_net_base_pct": _ZERO,
                "grid_levels": 1,
                "grid_spacing_pct": Decimal("0.001"),
                "reason": "test",
            }
        )
        shim = StrategyMigrationShim(ctrl, "bot7")
        native = _FakeNative()
        comparator = ShadowComparator(
            shim, native,
            divergence_threshold=Decimal("0.05"),
            instance_name="test",
        )

        comparator.evaluate(_SNAP)
        assert comparator._divergent_ticks == 1
        assert comparator.divergence_ratio > _ZERO

    def test_stats(self):
        ctrl = _mock_ctrl(
            _pb_state={
                "active": True,
                "side": "buy",
                "signal_score": Decimal("0.80"),
                "target_net_base_pct": _ZERO,
                "grid_levels": 1,
                "grid_spacing_pct": Decimal("0.001"),
                "reason": "test",
            }
        )
        shim = StrategyMigrationShim(ctrl, "bot7")
        comparator = ShadowComparator(shim, _FakeNative())

        for _ in range(10):
            comparator.evaluate(_SNAP)

        stats = comparator.stats
        assert stats["total_ticks"] == 10

    def test_warmup_takes_max(self):
        ctrl = _mock_ctrl(_pb_state={}, config=MagicMock(warmup_bars=150))
        shim = StrategyMigrationShim(ctrl, "bot7")
        native = _FakeNative()  # warmup=100
        comparator = ShadowComparator(shim, native)
        assert comparator.warmup_bars_required() == 150
