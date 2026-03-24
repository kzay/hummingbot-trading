"""Tests for paper_engine_v2 FundingSimulator."""
from decimal import Decimal

from simulation.funding_simulator import FundingSimulator
from simulation.portfolio import PaperPortfolio, PortfolioConfig
from simulation.types import _ZERO, FundingApplied, OrderSide
from tests.controllers.test_paper_engine_v2.conftest import BTC_PERP, BTC_SPOT, make_spec


def _settle_perp(portfolio, qty, price, side: OrderSide = OrderSide.BUY):
    spec = make_spec(BTC_PERP)
    return portfolio.settle_fill(
        instrument_id=BTC_PERP,
        side=side,
        quantity=Decimal(qty),
        price=Decimal(price),
        fee=_ZERO,
        source_bot="test",
        now_ns=0,
        spec=spec,
        leverage=1,
    )


class TestFundingSimulator:
    def _make_portfolio(self, usdt="10000"):
        return PaperPortfolio({"USDT": Decimal(usdt)}, PortfolioConfig())

    def test_applies_funding_at_interval(self):
        sim = FundingSimulator()
        p = self._make_portfolio()
        spec = make_spec(BTC_PERP)
        _settle_perp(p, "1.0", "100")

        instruments = {BTC_PERP.key: (spec, Decimal("0.0001"))}
        # First call sets baseline timestamp, no charge yet
        events = sim.tick(0, p, instruments)
        assert len(events) == 0

        # After 8h interval
        eight_h_ns = 28800 * 1_000_000_000
        events = sim.tick(eight_h_ns, p, instruments)
        assert len(events) == 1
        assert isinstance(events[0], FundingApplied)
        assert events[0].charge_quote > _ZERO

    def test_skips_flat_position(self):
        sim = FundingSimulator()
        p = self._make_portfolio()
        spec = make_spec(BTC_PERP)
        # No position open
        instruments = {BTC_PERP.key: (spec, Decimal("0.0001"))}
        sim.tick(0, p, instruments)  # set baseline
        events = sim.tick(28800 * 1_000_000_000, p, instruments)
        assert len(events) == 0

    def test_skips_spot_instrument(self):
        sim = FundingSimulator()
        p = self._make_portfolio(usdt="10000")
        spec = make_spec(BTC_SPOT)  # spot has funding_interval_s=0
        instruments = {BTC_SPOT.key: (spec, Decimal("0.0001"))}
        events = sim.tick(999_999_999_999, p, instruments)
        assert len(events) == 0

    def test_zero_funding_rate_skipped(self):
        sim = FundingSimulator()
        p = self._make_portfolio()
        spec = make_spec(BTC_PERP)
        _settle_perp(p, "1.0", "100")
        instruments = {BTC_PERP.key: (spec, _ZERO)}
        events = sim.tick(28800 * 1_000_000_000, p, instruments)
        assert len(events) == 0

    def test_funding_debited_from_portfolio(self):
        sim = FundingSimulator()
        p = self._make_portfolio(usdt="10000")
        spec = make_spec(BTC_PERP)
        _settle_perp(p, "1.0", "100")
        instruments = {BTC_PERP.key: (spec, Decimal("0.0001"))}
        sim.tick(0, p, instruments)  # set baseline
        initial_usdt = p.balance("USDT")
        sim.tick(28800 * 1_000_000_000, p, instruments)
        assert p.balance("USDT") < initial_usdt

    def test_funding_accumulates_on_position(self):
        sim = FundingSimulator()
        p = self._make_portfolio(usdt="10000")
        spec = make_spec(BTC_PERP)
        _settle_perp(p, "1.0", "100")
        instruments = {BTC_PERP.key: (spec, Decimal("0.0001"))}
        sim.tick(0, p, instruments)  # set baseline
        sim.tick(28800 * 1_000_000_000, p, instruments)
        pos = p.get_position(BTC_PERP)
        assert pos.funding_paid > _ZERO

    def test_positive_funding_credits_short_position(self):
        sim = FundingSimulator()
        p = self._make_portfolio(usdt="10000")
        spec = make_spec(BTC_PERP)
        _settle_perp(p, "1.0", "100", side=OrderSide.SELL)
        instruments = {BTC_PERP.key: (spec, Decimal("0.0001"))}
        sim.tick(0, p, instruments)
        initial_usdt = p.balance("USDT")
        events = sim.tick(28800 * 1_000_000_000, p, instruments)
        assert len(events) == 1
        assert events[0].charge_quote < _ZERO
        assert p.balance("USDT") > initial_usdt

    def test_negative_funding_credits_long_position(self):
        sim = FundingSimulator()
        p = self._make_portfolio(usdt="10000")
        spec = make_spec(BTC_PERP)
        _settle_perp(p, "1.0", "100", side=OrderSide.BUY)
        instruments = {BTC_PERP.key: (spec, Decimal("-0.0001"))}
        sim.tick(0, p, instruments)
        initial_usdt = p.balance("USDT")
        events = sim.tick(28800 * 1_000_000_000, p, instruments)
        assert len(events) == 1
        assert events[0].charge_quote < _ZERO
        assert p.balance("USDT") > initial_usdt
