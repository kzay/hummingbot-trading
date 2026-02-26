"""Tests for the promoted RiskEngine (Phase 3).

Covers:
- Margin level assessment (SAFE/WARN/CRITICAL/LIQUIDATE/BANKRUPT)
- Pre-trade checks (drawdown, notional cap, exposure cap, margin block)
- Liquidation ladder: LIQUIDATE -> reduce actions, BANKRUPT -> force-close
- Integration via PaperPortfolio.evaluate_risk()
"""
from decimal import Decimal

import pytest

from controllers.paper_engine_v2.risk_engine import (
    LiquidationAction,
    MarginLevel,
    RiskConfig,
    RiskEngine,
    RiskDecision,
)
from controllers.paper_engine_v2.types import (
    InstrumentId,
    OrderSide,
    PaperOrder,
    PaperOrderType,
    OrderStatus,
)

_Z = Decimal("0")
_ONE = Decimal("1")

BTC_PERP = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")


def _order(qty="1", price="100", side="buy"):
    from time import time_ns
    return PaperOrder(
        order_id="test",
        instrument_id=BTC_PERP,
        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
        order_type=PaperOrderType.LIMIT,
        price=Decimal(price),
        quantity=Decimal(qty),
        status=OrderStatus.OPEN,
        created_at_ns=time_ns(),
        updated_at_ns=time_ns(),
    )


def _engine(config=None) -> RiskEngine:
    return RiskEngine(config or RiskConfig())


# ---------------------------------------------------------------------------
# Margin level assessment
# ---------------------------------------------------------------------------

class TestMarginLevelAssessment:
    def test_safe_when_no_margin(self):
        eng = _engine()
        assert eng.assess_margin_level(Decimal("1000"), _Z) == MarginLevel.SAFE

    def test_safe_above_warn(self):
        # warn threshold = 3x; ratio = 1000/100 = 10x → SAFE
        eng = _engine()
        assert eng.assess_margin_level(Decimal("1000"), Decimal("100")) == MarginLevel.SAFE

    def test_warn_below_warn_threshold(self):
        # warn at ratio < 3; ratio = 200/100 = 2
        eng = _engine()
        assert eng.assess_margin_level(Decimal("200"), Decimal("100")) == MarginLevel.WARN

    def test_critical_below_critical(self):
        # critical at ratio < 1.5; ratio = 130/100 = 1.3
        eng = _engine()
        assert eng.assess_margin_level(Decimal("130"), Decimal("100")) == MarginLevel.CRITICAL

    def test_liquidate_below_liquidate(self):
        # liquidate at ratio < 1.1; ratio = 105/100 = 1.05
        eng = _engine()
        assert eng.assess_margin_level(Decimal("105"), Decimal("100")) == MarginLevel.LIQUIDATE

    def test_bankrupt_at_zero_equity(self):
        eng = _engine()
        assert eng.assess_margin_level(_Z, Decimal("100")) == MarginLevel.BANKRUPT

    def test_bankrupt_negative_equity(self):
        eng = _engine()
        assert eng.assess_margin_level(Decimal("-10"), Decimal("100")) == MarginLevel.BANKRUPT


# ---------------------------------------------------------------------------
# Pre-trade checks
# ---------------------------------------------------------------------------

class TestPreTrade:
    def _check(self, qty="1", price="100", peak_equity="1000", equity="1000",
               pos_abs_qty="0", net_exposure="0", margin_level=MarginLevel.SAFE, side="buy"):
        eng = _engine()
        from tests.controllers.test_paper_engine_v2.conftest import make_spec
        spec = make_spec(BTC_PERP)
        return eng.check_order(
            order=_order(qty, price, side),
            spec=spec,
            portfolio_equity=Decimal(equity),
            portfolio_peak_equity=Decimal(peak_equity),
            position_abs_qty=Decimal(pos_abs_qty),
            net_exposure_quote=Decimal(net_exposure),
            mid_price=Decimal(price),
            margin_level=margin_level,
        )

    def test_allowed_normal(self):
        result = self._check()
        assert result.allowed is True

    def test_drawdown_hard_stop(self):
        # equity=100, peak=1000 → dd=90% > 10%
        result = self._check(equity="100", peak_equity="1000")
        assert result.allowed is False
        assert "drawdown_hard_stop" in result.reason

    def test_blocked_on_critical_margin(self):
        result = self._check(margin_level=MarginLevel.CRITICAL)
        assert result.allowed is False
        assert "critical" in result.reason

    def test_blocked_on_liquidate_margin(self):
        result = self._check(margin_level=MarginLevel.LIQUIDATE)
        assert result.allowed is False

    def test_blocked_on_bankrupt(self):
        result = self._check(margin_level=MarginLevel.BANKRUPT)
        assert result.allowed is False

    def test_position_notional_cap(self):
        # cfg max_position_notional = 10000; (9999 + 1) * 100 = 1_000_000
        result = self._check(qty="100", price="100", pos_abs_qty="9999")
        assert result.allowed is False
        assert "position_notional_cap" in result.reason

    def test_net_exposure_cap(self):
        # cfg max_net_exposure = 50000; net=49999 + 100*100 = 59999
        result = self._check(qty="100", price="100", net_exposure="49999")
        assert result.allowed is False
        assert "net_exposure_cap" in result.reason


# ---------------------------------------------------------------------------
# Liquidation ladder
# ---------------------------------------------------------------------------

class TestLiquidationLadder:
    def _positions(self, qty="1"):
        return {BTC_PERP.key: (Decimal(qty), BTC_PERP)}

    def test_safe_no_actions(self):
        eng = _engine()
        level, actions = eng.evaluate(
            equity=Decimal("1000"),
            maintenance_margin=Decimal("100"),
            positions=self._positions(),
        )
        assert level == MarginLevel.SAFE
        assert actions == []

    def test_liquidate_produces_reduce_action(self):
        eng = _engine()
        # ratio = 105/100 = 1.05 → LIQUIDATE
        level, actions = eng.evaluate(
            equity=Decimal("105"),
            maintenance_margin=Decimal("100"),
            positions=self._positions("2"),
        )
        assert level == MarginLevel.LIQUIDATE
        assert len(actions) == 1
        a = actions[0]
        assert a.side == OrderSide.SELL   # reducing long
        assert a.quantity == Decimal("1")  # 50% of 2
        assert a.level == MarginLevel.LIQUIDATE

    def test_liquidate_short_position(self):
        eng = _engine()
        level, actions = eng.evaluate(
            equity=Decimal("105"),
            maintenance_margin=Decimal("100"),
            positions={BTC_PERP.key: (Decimal("-2"), BTC_PERP)},
        )
        assert level == MarginLevel.LIQUIDATE
        assert actions[0].side == OrderSide.BUY

    def test_bankrupt_force_closes_all(self):
        eng = _engine()
        positions = {
            BTC_PERP.key: (Decimal("3"), BTC_PERP),
        }
        level, actions = eng.evaluate(
            equity=_Z,
            maintenance_margin=Decimal("100"),
            positions=positions,
        )
        assert level == MarginLevel.BANKRUPT
        assert len(actions) == 1
        assert actions[0].quantity == Decimal("3")
        assert actions[0].level == MarginLevel.BANKRUPT

    def test_no_actions_on_flat_positions(self):
        eng = _engine()
        level, actions = eng.evaluate(
            equity=Decimal("105"),
            maintenance_margin=Decimal("100"),
            positions={BTC_PERP.key: (_Z, BTC_PERP)},
        )
        assert actions == []

    def test_risk_reason_string_for_critical(self):
        eng = _engine()
        reason = eng.margin_level_to_risk_reason(MarginLevel.CRITICAL)
        assert reason == "margin_critical"

    def test_risk_reason_string_safe_is_empty(self):
        eng = _engine()
        assert eng.margin_level_to_risk_reason(MarginLevel.SAFE) == ""


# ---------------------------------------------------------------------------
# Integration via PaperPortfolio.evaluate_risk()
# ---------------------------------------------------------------------------

class TestPortfolioRiskIntegration:
    def test_safe_on_fresh_portfolio(self):
        from controllers.paper_engine_v2.portfolio import PaperPortfolio, PortfolioConfig
        p = PaperPortfolio({"USDT": Decimal("1000")}, PortfolioConfig())
        level, actions = p.evaluate_risk()
        assert level == MarginLevel.SAFE
        assert actions == []

    def test_margin_level_accessible(self):
        from controllers.paper_engine_v2.portfolio import PaperPortfolio, PortfolioConfig
        p = PaperPortfolio({"USDT": Decimal("1000")}, PortfolioConfig())
        _ = p.evaluate_risk()
        assert p.margin_level == MarginLevel.SAFE

    def test_risk_reasons_string_empty_when_safe(self):
        from controllers.paper_engine_v2.portfolio import PaperPortfolio, PortfolioConfig
        p = PaperPortfolio({"USDT": Decimal("1000")}, PortfolioConfig())
        assert p.risk_reasons() == ""
