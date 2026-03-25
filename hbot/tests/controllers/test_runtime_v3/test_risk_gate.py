"""Tests for v3 risk gate — each layer + composed gate."""

from __future__ import annotations

from decimal import Decimal

import pytest

from controllers.runtime.v3.risk.bot_gate import BotRiskConfig, BotRiskGate
from controllers.runtime.v3.risk.desk_risk_gate import DeskRiskGate
from controllers.runtime.v3.risk.portfolio_gate import PortfolioRiskGate
from controllers.runtime.v3.risk.signal_gate import SignalRiskConfig, SignalRiskGate
from controllers.runtime.v3.signals import SignalLevel, TradingSignal
from controllers.runtime.v3.types import EquitySnapshot, MarketSnapshot, PositionSnapshot

_ZERO = Decimal("0")


def _snap(
    daily_loss_pct: Decimal = _ZERO,
    drawdown_pct: Decimal = _ZERO,
    turnover_x: Decimal = _ZERO,
    **config_overrides,
) -> MarketSnapshot:
    return MarketSnapshot(
        mid=Decimal("65000"),
        equity=EquitySnapshot(
            equity_quote=Decimal("5000"),
            daily_loss_pct=daily_loss_pct,
            max_drawdown_pct=drawdown_pct,
            daily_turnover_x=turnover_x,
        ),
        position=PositionSnapshot(is_perp=False),
        config=config_overrides,
    )


def _signal(direction: str = "buy", conviction: str = "0.8") -> TradingSignal:
    return TradingSignal(
        family="directional",
        direction=direction,
        conviction=Decimal(conviction),
        levels=(
            SignalLevel(side=direction, spread_pct=Decimal("0.001"), size_quote=Decimal("100")),
        ),
    )


# ── Portfolio gate ───────────────────────────────────────────────────


class TestPortfolioRiskGate:
    def test_approve_without_redis(self):
        gate = PortfolioRiskGate(redis_client=None)
        d = gate.evaluate(_signal(), _snap())
        assert d.approved is True

    def test_latched_hard_stop(self):
        gate = PortfolioRiskGate()
        gate._hard_stop_latched = True
        d = gate.evaluate(_signal(), _snap())
        assert d.approved is False
        assert d.reason == "portfolio_hard_stop_latched"

    def test_reset_clears_latch(self):
        gate = PortfolioRiskGate()
        gate._hard_stop_latched = True
        gate.reset()
        d = gate.evaluate(_signal(), _snap())
        assert d.approved is True


# ── Bot gate ─────────────────────────────────────────────────────────


class TestBotRiskGate:
    def test_approve_within_limits(self):
        gate = BotRiskGate()
        d = gate.evaluate(_signal(), _snap())
        assert d.approved is True

    def test_daily_loss_hard_stop(self):
        gate = BotRiskGate(BotRiskConfig(max_daily_loss_pct_hard=Decimal("0.02")))
        d = gate.evaluate(_signal(), _snap(daily_loss_pct=Decimal("0.025")))
        assert d.approved is False
        assert d.reason == "daily_loss_hard_stop"

    def test_drawdown_hard_stop(self):
        gate = BotRiskGate(BotRiskConfig(max_drawdown_pct_hard=Decimal("0.035")))
        d = gate.evaluate(_signal(), _snap(drawdown_pct=Decimal("0.04")))
        assert d.approved is False
        assert d.reason == "drawdown_hard_stop"

    def test_turnover_hard_stop(self):
        gate = BotRiskGate(BotRiskConfig(max_daily_turnover_x_hard=Decimal("14")))
        d = gate.evaluate(_signal(), _snap(turnover_x=Decimal("15")))
        assert d.approved is False
        assert d.reason == "turnover_hard_stop"

    def test_turnover_soft_cap_reduces_sizing(self):
        cfg = BotRiskConfig(
            max_daily_turnover_x_hard=Decimal("10"),
            turnover_soft_cap_ratio=Decimal("0.80"),
        )
        gate = BotRiskGate(cfg)
        # turnover_x=9 is 90% of hard cap (10), above soft cap (8)
        d = gate.evaluate(_signal(), _snap(turnover_x=Decimal("9")))

        assert d.approved is True
        assert d.reason == "turnover_soft_cap"
        assert d.modified_signal is not None
        # Remaining ratio = (10-9)/(10-8) = 0.5, so size halved
        assert d.modified_signal.levels[0].size_quote == Decimal("50")


# ── Signal gate ──────────────────────────────────────────────────────


class TestSignalRiskGate:
    def test_approve_by_default(self):
        gate = SignalRiskGate()
        d = gate.evaluate(_signal(), _snap())
        assert d.approved is True

    def test_edge_gate_blocks(self):
        cfg = SignalRiskConfig(min_net_edge_bps=Decimal("5.5"))
        gate = SignalRiskGate(cfg)
        d = gate.evaluate(_signal(), _snap(net_edge_bps=Decimal("3.0")))
        assert d.approved is False
        assert d.reason == "edge_gate_blocked"

    def test_edge_gate_hysteresis_resume(self):
        cfg = SignalRiskConfig(
            min_net_edge_bps=Decimal("5.5"),
            edge_resume_bps=Decimal("6.0"),
        )
        gate = SignalRiskGate(cfg)

        # Block
        gate.evaluate(_signal(), _snap(net_edge_bps=Decimal("3.0")))
        assert gate._edge_blocked

        # Still blocked at 5.8 (below resume)
        d = gate.evaluate(_signal(), _snap(net_edge_bps=Decimal("5.8")))
        assert d.approved is False

        # Resumes at 6.5 (above resume)
        d = gate.evaluate(_signal(), _snap(net_edge_bps=Decimal("6.5")))
        assert d.approved is True
        assert not gate._edge_blocked

    def test_adverse_fill_ratio_blocks(self):
        cfg = SignalRiskConfig(adverse_fill_ratio_threshold=Decimal("0.30"))
        gate = SignalRiskGate(cfg)
        d = gate.evaluate(_signal(), _snap(adverse_fill_ratio=Decimal("0.35")))
        assert d.approved is False
        assert d.reason == "adverse_fill_ratio_high"

    def test_cooldown_blocks_rapid_signals(self):
        cfg = SignalRiskConfig(signal_cooldown_s=300.0)
        gate = SignalRiskGate(cfg)

        # First signal passes
        d1 = gate.evaluate(_signal(direction="buy"), _snap())
        assert d1.approved is True

        # Second signal within cooldown is blocked
        d2 = gate.evaluate(_signal(direction="buy"), _snap())
        assert d2.approved is False
        assert d2.reason == "signal_cooldown_active"

    def test_cooldown_per_side(self):
        cfg = SignalRiskConfig(signal_cooldown_s=300.0)
        gate = SignalRiskGate(cfg)

        # Buy passes
        d1 = gate.evaluate(_signal(direction="buy"), _snap())
        assert d1.approved is True

        # Sell on different side also passes
        d2 = gate.evaluate(_signal(direction="sell"), _snap())
        assert d2.approved is True

    def test_reset_cooldown(self):
        gate = SignalRiskGate(SignalRiskConfig(signal_cooldown_s=300.0))
        gate.evaluate(_signal(direction="buy"), _snap())
        gate.reset_cooldown("buy")
        d = gate.evaluate(_signal(direction="buy"), _snap())
        assert d.approved is True


# ── Composed DeskRiskGate ────────────────────────────────────────────


class TestDeskRiskGate:
    def test_all_layers_approve(self):
        gate = DeskRiskGate(
            portfolio=PortfolioRiskGate(),
            bot=BotRiskGate(),
            signal=SignalRiskGate(),
        )
        d = gate.evaluate(_signal(), _snap())
        assert d.approved is True

    def test_portfolio_rejects_short_circuits(self):
        pgate = PortfolioRiskGate()
        pgate._hard_stop_latched = True
        gate = DeskRiskGate(
            portfolio=pgate,
            bot=BotRiskGate(),
            signal=SignalRiskGate(),
        )
        d = gate.evaluate(_signal(), _snap())
        assert d.approved is False
        assert d.layer == "portfolio"

    def test_bot_rejects_skips_signal(self):
        gate = DeskRiskGate(
            portfolio=PortfolioRiskGate(),
            bot=BotRiskGate(BotRiskConfig(max_daily_loss_pct_hard=Decimal("0.01"))),
            signal=SignalRiskGate(),
        )
        d = gate.evaluate(_signal(), _snap(daily_loss_pct=Decimal("0.02")))
        assert d.approved is False
        assert d.layer == "bot"

    def test_bot_modifies_signal_flows_to_signal_layer(self):
        cfg = BotRiskConfig(
            max_daily_turnover_x_hard=Decimal("10"),
            turnover_soft_cap_ratio=Decimal("0.80"),
        )
        gate = DeskRiskGate(
            portfolio=PortfolioRiskGate(),
            bot=BotRiskGate(cfg),
            signal=SignalRiskGate(),
        )
        d = gate.evaluate(_signal(), _snap(turnover_x=Decimal("9")))
        assert d.approved is True
        # Signal was modified (reduced sizing)
        assert d.modified_signal is not None
