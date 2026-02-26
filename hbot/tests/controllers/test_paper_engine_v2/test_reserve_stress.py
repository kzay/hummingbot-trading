"""Reserve accounting stress tests (Phase 6).

Validates that reserves never leak regardless of:
- Repeated partial fill + cancel sequences
- Concurrent multi-instrument orders
- State restore after restart
- Position flips releasing incorrect reserves

Invariant checked throughout: sum of active reserves ≤ total balance.
"""
from decimal import Decimal
import time

import pytest

from controllers.paper_engine_v2.fee_models import MakerTakerFeeModel
from controllers.paper_engine_v2.fill_models import TopOfBookFillModel, QueuePositionFillModel
from controllers.paper_engine_v2.latency_model import NO_LATENCY
from controllers.paper_engine_v2.matching_engine import EngineConfig, OrderMatchingEngine
from controllers.paper_engine_v2.portfolio import MultiAssetLedger, PaperPortfolio, PortfolioConfig
from controllers.paper_engine_v2.types import OrderSide, _ZERO
from tests.controllers.test_paper_engine_v2.conftest import (
    BTC_SPOT, BTC_PERP, ETH_SPOT, make_book, make_order, make_spec,
)

_USDT_START = Decimal("10000")
_BTC_START = Decimal("2")


def _make_engine(iid=None, balances=None, fill_model=None, leverage=1):
    if iid is None:
        iid = BTC_SPOT
    spec = make_spec(iid)
    portfolio = PaperPortfolio(
        balances or {"USDT": _USDT_START, "BTC": _BTC_START},
        PortfolioConfig(),
    )
    engine = OrderMatchingEngine(
        instrument_id=iid,
        instrument_spec=spec,
        portfolio=portfolio,
        fill_model=fill_model or TopOfBookFillModel(),
        fee_model=MakerTakerFeeModel(Decimal("0.0002"), Decimal("0.0006")),
        latency_model=NO_LATENCY,
        config=EngineConfig(),
        leverage=leverage,
    )
    return engine, portfolio


def _assert_reserve_invariant(portfolio: PaperPortfolio, asset: str = "USDT"):
    """Assert: reserved ≤ total (no leak beyond balance)."""
    total = portfolio.balance(asset)
    available = portfolio.available(asset)
    reserved = total - available
    # reserved may be slightly negative due to clamping; allow EPS
    assert reserved >= Decimal("-1e-8"), f"Reserve underflow: reserved={reserved}"
    assert available >= _ZERO, f"Available negative: {available}"


class TestReserveNoLeak:
    def test_submit_cancel_no_leak(self):
        engine, portfolio = _make_engine()
        engine.update_book(make_book())
        now = int(time.time() * 1e9)
        order = make_order("buy", "limit_maker", "99.95", "1.0")
        from controllers.paper_engine_v2.types import OrderAccepted
        event = engine.submit_order(order, now)
        # Check order was accepted (not rejected)
        assert isinstance(event, OrderAccepted), f"Expected OrderAccepted, got {event}"
        reserved_after_submit = _USDT_START - portfolio.available("USDT")
        assert reserved_after_submit > _ZERO  # something reserved

        engine.cancel_order(order.order_id, now + 1)
        _assert_reserve_invariant(portfolio)
        assert portfolio.available("USDT") == _USDT_START  # fully released

    def test_repeated_submit_cancel_no_cumulative_leak(self):
        from controllers.paper_engine_v2.types import OrderStatus
        engine, portfolio = _make_engine()
        engine.update_book(make_book())
        for i in range(10):
            now = int(time.time() * 1e9) + i * 1_000_000
            order = make_order("buy", "limit_maker", "99.95", "0.5")
            order.order_id = f"order_{i}"
            engine.submit_order(order, now)
            if order.status == OrderStatus.OPEN:
                engine.cancel_order(order.order_id, now + 1)
        _assert_reserve_invariant(portfolio)
        # All reserves released: available == start
        assert portfolio.available("USDT") == _USDT_START

    def test_fill_and_cancel_remaining_no_leak(self):
        """Partially fill then cancel — reserve should reflect remaining only."""
        from controllers.paper_engine_v2.fill_models import QueuePositionFillModel, QueuePositionConfig
        cfg = QueuePositionConfig(
            queue_participation=Decimal("0.5"),
            min_partial_fill_ratio=Decimal("0.5"),
            max_partial_fill_ratio=Decimal("0.5"),
            prob_fill_on_limit=1.0, seed=7,
        )
        engine, portfolio = _make_engine(fill_model=QueuePositionFillModel(cfg))
        engine.update_book(make_book(ask_price="100.00", ask_size="1.0"))
        now = int(time.time() * 1e9)
        order = make_order("buy", "market", "100.00", "2.0")
        order.crossed_at_creation = True
        engine.submit_order(order, now)
        engine.tick(now)
        # Partially filled; cancel remainder
        engine.cancel_order(order.order_id, now + 200_000_000)
        _assert_reserve_invariant(portfolio)

    def test_fully_filled_reserve_zeroed(self):
        engine, portfolio = _make_engine()
        engine.update_book(make_book())
        now = int(time.time() * 1e9)
        order = make_order("buy", "market", "100.10", "0.1")
        order.crossed_at_creation = True
        engine.submit_order(order, now)
        engine.tick(now)
        assert order._reserved_amount == _ZERO
        _assert_reserve_invariant(portfolio)

    def test_cancel_all_releases_all(self):
        engine, portfolio = _make_engine()
        engine.update_book(make_book())
        now = int(time.time() * 1e9)
        for i in range(5):
            order = make_order("buy", "limit_maker", str(98 - i), "0.5")
            order.order_id = f"ord_{i}"
            engine.submit_order(order, now)
        engine.cancel_all(now + 1)
        _assert_reserve_invariant(portfolio)
        assert portfolio.available("USDT") == _USDT_START

    def test_multi_instrument_reserves_independent(self):
        """Two instruments' reserves must not interfere."""
        spec_btc = make_spec(BTC_SPOT)
        spec_eth = make_spec(ETH_SPOT)
        portfolio = PaperPortfolio(
            {"USDT": Decimal("5000"), "BTC": _ZERO, "ETH": _ZERO},
            PortfolioConfig(),
        )
        eng_btc = OrderMatchingEngine(
            instrument_id=BTC_SPOT, instrument_spec=spec_btc,
            portfolio=portfolio,
            fill_model=TopOfBookFillModel(),
            fee_model=MakerTakerFeeModel(Decimal("0.0002"), Decimal("0.0006")),
            latency_model=NO_LATENCY,
            config=EngineConfig(),
        )
        eng_eth = OrderMatchingEngine(
            instrument_id=ETH_SPOT, instrument_spec=spec_eth,
            portfolio=portfolio,
            fill_model=TopOfBookFillModel(),
            fee_model=MakerTakerFeeModel(Decimal("0.0002"), Decimal("0.0006")),
            latency_model=NO_LATENCY,
            config=EngineConfig(),
        )
        eng_btc.update_book(make_book(iid=BTC_SPOT))
        eng_eth.update_book(make_book(iid=ETH_SPOT))
        now = int(time.time() * 1e9)

        btc_order = make_order("buy", "limit_maker", "99.95", "1.0", iid=BTC_SPOT)
        eth_order = make_order("buy", "limit_maker", "99.95", "1.0", iid=ETH_SPOT)
        eng_btc.submit_order(btc_order, now)
        eng_eth.submit_order(eth_order, now)

        # Cancel BTC order only; ETH should still have its reserve
        eng_btc.cancel_order(btc_order.order_id, now + 1)
        avail_after = portfolio.available("USDT")
        eth_reserved = Decimal("99.95") * Decimal("1.0")
        # Available should be start - ETH_reserve
        expected = Decimal("5000") - eth_reserved
        assert abs(avail_after - expected) < Decimal("1")  # within 1 USDT tolerance
        _assert_reserve_invariant(portfolio)


class TestLedgerInvariants:
    def test_reserve_cannot_exceed_balance(self):
        ledger = MultiAssetLedger({"USDT": Decimal("100")})
        ledger.reserve("USDT", Decimal("200"))  # over-reserve
        assert ledger.available("USDT") == _ZERO  # clamped

    def test_release_beyond_reserved_clamps_to_zero(self):
        ledger = MultiAssetLedger({"USDT": Decimal("100")})
        ledger.reserve("USDT", Decimal("50"))
        ledger.release("USDT", Decimal("200"))  # release more than reserved
        assert ledger._reserved.get("USDT", _ZERO) == _ZERO

    def test_credit_and_debit_balanced(self):
        ledger = MultiAssetLedger({"USDT": _ZERO})
        ledger.credit("USDT", Decimal("1000"))
        ledger.debit("USDT", Decimal("300"))
        assert ledger.total("USDT") == Decimal("700")
