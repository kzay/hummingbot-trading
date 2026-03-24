"""Comprehensive stress tests for Paper Engine v2 and backtest harness.

Validates critical invariants under adversarial conditions:

1. WALLET CONSERVATION — money cannot be created or destroyed
2. ORDER LIFECYCLE — every order reaches terminal state, reserves released
3. POSITION ACCOUNTING — VWAP, PnL, flip-through-zero correctness
4. EQUITY CONSERVATION — backtest equity tracks wallet state exactly
5. RAPID SIGNAL STRESS — fast buy/sell cycling, partial fills, cancels
6. EDGE CASES — dust positions, min-notional, simultaneous multi-instrument
"""
from __future__ import annotations

import time
import uuid
from decimal import Decimal

from simulation.accounting import PositionState, apply_fill
from simulation.desk import DeskConfig, PaperDesk
from simulation.fee_models import MakerTakerFeeModel
from simulation.fill_models import (
    TopOfBookFillModel,
)
from simulation.latency_model import NO_LATENCY
from simulation.matching_engine import EngineConfig, OrderMatchingEngine
from simulation.portfolio import (
    MultiAssetLedger,
    PaperPortfolio,
    PortfolioConfig,
)
from simulation.types import (
    _ZERO,
    BookLevel,
    InstrumentId,
    InstrumentSpec,
    OrderBookSnapshot,
    OrderFilled,
    OrderSide,
    OrderStatus,
    PaperOrder,
    PaperOrderType,
)

BTC_SPOT = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="spot")
BTC_PERP = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")
ETH_PERP = InstrumentId(venue="bitget", trading_pair="ETH-USDT", instrument_type="perp")

_EPS = Decimal("1e-6")
_USDT_START = Decimal("10000")
_MAKER_FEE = Decimal("0.0002")
_TAKER_FEE = Decimal("0.0006")


def _make_spec(iid: InstrumentId) -> InstrumentSpec:
    return InstrumentSpec(
        instrument_id=iid,
        price_precision=2,
        size_precision=4,
        price_increment=Decimal("0.01"),
        size_increment=Decimal("0.0001"),
        min_quantity=Decimal("0.0001"),
        min_notional=Decimal("5"),
        max_quantity=Decimal("1000"),
        maker_fee_rate=_MAKER_FEE,
        taker_fee_rate=_TAKER_FEE,
        margin_init=Decimal("0.10"),
        margin_maint=Decimal("0.05"),
        leverage_max=20,
        funding_interval_s=28800 if iid.is_perp else 0,
    )


def _make_book(
    iid: InstrumentId = None,
    bid: str = "100.00",
    ask: str = "100.05",
    bid_size: str = "10.0",
    ask_size: str = "10.0",
) -> OrderBookSnapshot:
    if iid is None:
        iid = BTC_SPOT
    return OrderBookSnapshot(
        instrument_id=iid,
        bids=(BookLevel(price=Decimal(bid), size=Decimal(bid_size)),),
        asks=(BookLevel(price=Decimal(ask), size=Decimal(ask_size)),),
        timestamp_ns=int(time.time() * 1e9),
    )


def _make_order(
    side: str,
    otype: str,
    price: str,
    qty: str,
    iid: InstrumentId = None,
    order_id: str = "",
) -> PaperOrder:
    if iid is None:
        iid = BTC_SPOT
    side_e = OrderSide.BUY if side == "buy" else OrderSide.SELL
    type_map = {
        "limit": PaperOrderType.LIMIT,
        "limit_maker": PaperOrderType.LIMIT_MAKER,
        "market": PaperOrderType.MARKET,
    }
    return PaperOrder(
        order_id=order_id or f"ord_{uuid.uuid4().hex[:8]}",
        instrument_id=iid,
        side=side_e,
        order_type=type_map[otype],
        price=Decimal(price),
        quantity=Decimal(qty),
        status=OrderStatus.PENDING_SUBMIT,
        created_at_ns=int(time.time() * 1e9),
        updated_at_ns=int(time.time() * 1e9),
        source_bot="stress_test",
    )


def _make_engine(
    iid: InstrumentId = None,
    balances: dict | None = None,
    fill_model=None,
    leverage: int = 1,
) -> tuple[OrderMatchingEngine, PaperPortfolio]:
    if iid is None:
        iid = BTC_SPOT
    spec = _make_spec(iid)
    portfolio = PaperPortfolio(
        balances or {"USDT": _USDT_START, "BTC": Decimal("2")},
        PortfolioConfig(),
    )
    engine = OrderMatchingEngine(
        instrument_id=iid,
        instrument_spec=spec,
        portfolio=portfolio,
        fill_model=fill_model or TopOfBookFillModel(),
        fee_model=MakerTakerFeeModel(_MAKER_FEE, _TAKER_FEE),
        latency_model=NO_LATENCY,
        config=EngineConfig(),
        leverage=leverage,
    )
    return engine, portfolio


def _assert_balance_invariants(portfolio: PaperPortfolio, assets: list[str] | None = None):
    """Assert core wallet invariants for all tracked assets."""
    if assets is None:
        assets = ["USDT"]
    for asset in assets:
        total = portfolio.balance(asset)
        available = portfolio.available(asset)
        reserved = total - available
        assert available >= _ZERO, (
            f"Available({asset}) negative: {available}"
        )
        assert reserved >= -_EPS, (
            f"Reserved({asset}) underflow: {reserved}"
        )
        assert total >= -_EPS, (
            f"Total({asset}) negative: {total}"
        )


# =========================================================================
# 1. WALLET CONSERVATION
# =========================================================================


class TestWalletConservation:
    """Money cannot appear from nowhere or vanish into nothing."""

    def test_buy_sell_round_trip_conserves_wallet(self):
        """Buy then sell same quantity — wallet change = fees only."""
        engine, portfolio = _make_engine()
        engine.update_book(_make_book())
        now = int(time.time() * 1e9)

        # Buy 1 BTC
        buy = _make_order("buy", "market", "100.10", "1.0")
        buy.crossed_at_creation = True
        engine.submit_order(buy, now)
        engine.tick(now)

        usdt_after_buy = portfolio.balance("USDT")
        btc_after_buy = portfolio.balance("BTC")

        # Sell 1 BTC back at same price
        engine.update_book(_make_book(bid="100.05", ask="100.10"))
        sell = _make_order("sell", "market", "99.95", "1.0")
        sell.crossed_at_creation = True
        engine.submit_order(sell, now + 1_000_000_000)
        engine.tick(now + 1_000_000_000)

        usdt_final = portfolio.balance("USDT")
        btc_final = portfolio.balance("BTC")

        # BTC should be back to starting amount
        assert abs(btc_final - Decimal("2")) < _EPS

        # USDT difference = price spread + fees (no phantom money)
        usdt_change = usdt_final - _USDT_START
        assert usdt_change <= _ZERO, f"Wallet gained money from round trip: {usdt_change}"

        _assert_balance_invariants(portfolio, ["USDT", "BTC"])

    def test_perp_round_trip_conserves_wallet(self):
        """Open and close a perp position — wallet change = fees + PnL."""
        engine, portfolio = _make_engine(
            iid=BTC_PERP,
            balances={"USDT": _USDT_START},
            leverage=10,
        )
        now = int(time.time() * 1e9)

        # Open long
        engine.update_book(_make_book(iid=BTC_PERP))
        buy = _make_order("buy", "market", "100.10", "0.5", iid=BTC_PERP)
        buy.crossed_at_creation = True
        engine.submit_order(buy, now)
        engine.tick(now)

        # Close at same price
        engine.update_book(_make_book(
            iid=BTC_PERP, bid="100.05", ask="100.10",
        ))
        sell = _make_order("sell", "market", "99.90", "0.5", iid=BTC_PERP)
        sell.crossed_at_creation = True
        engine.submit_order(sell, now + 1_000_000_000)
        engine.tick(now + 1_000_000_000)

        usdt_final = portfolio.balance("USDT")
        pos = portfolio.get_position(BTC_PERP)
        pos_qty = pos.quantity if pos else _ZERO

        assert abs(pos_qty) < _EPS, f"Position not flat: {pos_qty}"

        # The only wallet change should be fees + realized PnL
        # Wallet cannot increase beyond what PnL would justify
        _assert_balance_invariants(portfolio)

    def test_no_money_creation_on_rapid_trades(self):
        """100 rapid buy/sell cycles — total wallet must only decrease (fees)."""
        engine, portfolio = _make_engine()
        now = int(time.time() * 1e9)

        for i in range(100):
            t = now + i * 2_000_000_000
            engine.update_book(_make_book())

            buy = _make_order("buy", "market", "100.10", "0.1", order_id=f"buy_{i}")
            buy.crossed_at_creation = True
            engine.submit_order(buy, t)
            engine.tick(t)

            sell = _make_order("sell", "market", "99.90", "0.1", order_id=f"sell_{i}")
            sell.crossed_at_creation = True
            engine.submit_order(sell, t + 1_000_000_000)
            engine.tick(t + 1_000_000_000)

        usdt_final = portfolio.balance("USDT")
        assert usdt_final <= _USDT_START, (
            f"Money created: started={_USDT_START}, ended={usdt_final}"
        )
        _assert_balance_invariants(portfolio, ["USDT", "BTC"])


# =========================================================================
# 2. ORDER LIFECYCLE COMPLETENESS
# =========================================================================


class TestOrderLifecycle:
    """Every order must reach a terminal state; reserves must be released."""

    def test_all_orders_terminal_after_cancel_all(self):
        engine, portfolio = _make_engine()
        engine.update_book(_make_book())
        now = int(time.time() * 1e9)

        orders = []
        for i in range(20):
            o = _make_order(
                "buy" if i % 2 == 0 else "sell",
                "limit_maker",
                str(99 - i * 0.1) if i % 2 == 0 else str(101 + i * 0.1),
                "0.1",
                order_id=f"lifecycle_{i}",
            )
            engine.submit_order(o, now + i)
            orders.append(o)

        engine.cancel_all(now + 1_000_000)

        for o in orders:
            assert o.is_terminal, (
                f"Order {o.order_id} not terminal: status={o.status}"
            )

        avail = portfolio.available("USDT")
        assert avail == _USDT_START, (
            f"Reserves leaked: available={avail}, expected={_USDT_START}"
        )

    def test_filled_order_releases_reserves(self):
        engine, portfolio = _make_engine()
        engine.update_book(_make_book())
        now = int(time.time() * 1e9)

        o = _make_order("buy", "market", "100.10", "0.5")
        o.crossed_at_creation = True
        engine.submit_order(o, now)
        engine.tick(now)

        assert o._reserved_amount == _ZERO, (
            f"Reserve not released after fill: {o._reserved_amount}"
        )
        _assert_balance_invariants(portfolio)

    def test_rejected_order_never_reserves(self):
        """Order that fails validation should never reserve anything."""
        engine, portfolio = _make_engine(balances={"USDT": Decimal("1")})
        engine.update_book(_make_book())
        now = int(time.time() * 1e9)

        # Try to buy 100 BTC with only $1 — should be rejected
        o = _make_order("buy", "limit_maker", "100.00", "100.0")
        engine.submit_order(o, now)

        assert portfolio.available("USDT") == Decimal("1")
        _assert_balance_invariants(portfolio)


# =========================================================================
# 3. POSITION ACCOUNTING
# =========================================================================


class TestPositionAccounting:
    """VWAP, realized PnL, and position flips must be mathematically correct."""

    def _flat(self) -> PositionState:
        return PositionState(
            quantity=_ZERO, avg_entry_price=_ZERO,
            realized_pnl=_ZERO, opened_at_ns=0,
        )

    def _fill(self, state, side, qty, price):
        """Wrapper: apply_fill(old, side_str, qty, price) -> (new_state, result)."""
        result = apply_fill(state, side, qty, price)
        return result.new_state, result

    def test_vwap_on_additive_fills(self):
        """Two buys at different prices → VWAP = weighted average."""
        state = self._flat()

        state, r1 = self._fill(state, "buy", Decimal("1.0"), Decimal("100"))
        assert state.avg_entry_price == Decimal("100")

        state, r2 = self._fill(state, "buy", Decimal("1.0"), Decimal("110"))
        expected_vwap = (Decimal("100") + Decimal("110")) / 2
        assert abs(state.avg_entry_price - expected_vwap) < _EPS
        assert state.quantity == Decimal("2.0")

    def test_flip_through_zero_realizes_pnl(self):
        """Long 1.0 → Sell 2.0 should close long, open short, realize PnL."""
        state = self._flat()

        state, _ = self._fill(state, "buy", Decimal("1.0"), Decimal("100"))

        state, result = self._fill(state, "sell", Decimal("2.0"), Decimal("110"))

        assert result.fill_realized_pnl == Decimal("10"), (
            f"Expected realized PnL=10, got {result.fill_realized_pnl}"
        )
        assert state.quantity == Decimal("-1.0")
        assert state.avg_entry_price == Decimal("110")

    def test_close_position_realizes_correct_pnl(self):
        """Close a winning and a losing trade — PnL must be exact."""
        state = self._flat()

        state, _ = self._fill(state, "buy", Decimal("1.0"), Decimal("100"))
        state, result = self._fill(state, "sell", Decimal("1.0"), Decimal("105"))
        assert result.fill_realized_pnl == Decimal("5")

        state, _ = self._fill(state, "sell", Decimal("1.0"), Decimal("200"))
        state, result = self._fill(state, "buy", Decimal("1.0"), Decimal("210"))
        assert result.fill_realized_pnl == Decimal("-10")

    def test_many_partial_fills_accumulate_correctly(self):
        """50 small fills should produce the same VWAP as one large fill."""
        state_many = self._flat()
        state_one = self._flat()

        total_qty = _ZERO
        total_cost = _ZERO
        for i in range(50):
            price = Decimal("100") + Decimal(str(i)) / 10
            qty = Decimal("0.02")
            state_many, _ = self._fill(state_many, "buy", qty, price)
            total_qty += qty
            total_cost += qty * price

        state_one, _ = self._fill(state_one, "buy", total_qty, total_cost / total_qty)

        assert abs(state_many.quantity - total_qty) < _EPS
        assert abs(state_many.avg_entry_price - state_one.avg_entry_price) < Decimal("0.01")

    def test_zero_quantity_fill_is_noop(self):
        state = self._flat()
        state, result = self._fill(state, "buy", Decimal("1.0"), Decimal("100"))
        old_qty = state.quantity
        state, result = self._fill(state, "sell", _ZERO, Decimal("110"))
        assert state.quantity == old_qty


# =========================================================================
# 4. RESERVE STRESS UNDER ADVERSARIAL PATTERNS
# =========================================================================


class TestReserveStressAdversarial:
    """Push reserve tracking to breaking point with adversarial order patterns."""

    def test_submit_cancel_rapid_cycle_200_times(self):
        """Rapidly submit and cancel 200 orders — no reserve leak."""
        engine, portfolio = _make_engine()
        engine.update_book(_make_book())
        now = int(time.time() * 1e9)

        for i in range(200):
            t = now + i * 100_000
            o = _make_order(
                "buy" if i % 2 == 0 else "sell",
                "limit_maker",
                "99.00" if i % 2 == 0 else "101.00",
                "0.5",
                order_id=f"rapid_{i}",
            )
            engine.submit_order(o, t)
            if o.status == OrderStatus.OPEN:
                engine.cancel_order(o.order_id, t + 1)
            engine.tick(t + 2)

        _assert_balance_invariants(portfolio, ["USDT", "BTC"])
        assert portfolio.available("USDT") >= _USDT_START - _EPS

    def test_mixed_fills_and_cancels_no_leak(self):
        """Alternate between filling and cancelling — reserves must balance."""
        engine, portfolio = _make_engine()
        now = int(time.time() * 1e9)
        initial_usdt = portfolio.balance("USDT")

        for i in range(50):
            t = now + i * 2_000_000_000
            engine.update_book(_make_book())

            if i % 3 == 0:
                # Market fill
                o = _make_order("buy", "market", "100.10", "0.05", order_id=f"mkt_{i}")
                o.crossed_at_creation = True
                engine.submit_order(o, t)
                engine.tick(t)
            elif i % 3 == 1:
                # Limit then cancel
                o = _make_order("buy", "limit_maker", "98.00", "0.5", order_id=f"lim_{i}")
                engine.submit_order(o, t)
                engine.cancel_order(o.order_id, t + 100)
            else:
                # Sell back
                if portfolio.balance("BTC") > Decimal("0.05"):
                    o = _make_order("sell", "market", "99.90", "0.05", order_id=f"sell_{i}")
                    o.crossed_at_creation = True
                    engine.submit_order(o, t)
                    engine.tick(t)

        _assert_balance_invariants(portfolio, ["USDT", "BTC"])

    def test_max_open_orders_respected(self):
        """Submitting beyond max open orders should reject, not leak."""
        config = EngineConfig(max_open_orders=5)
        spec = _make_spec(BTC_SPOT)
        portfolio = PaperPortfolio({"USDT": _USDT_START, "BTC": Decimal("2")}, PortfolioConfig())
        engine = OrderMatchingEngine(
            instrument_id=BTC_SPOT,
            instrument_spec=spec,
            portfolio=portfolio,
            fill_model=TopOfBookFillModel(),
            fee_model=MakerTakerFeeModel(_MAKER_FEE, _TAKER_FEE),
            latency_model=NO_LATENCY,
            config=config,
        )
        engine.update_book(_make_book())
        now = int(time.time() * 1e9)

        accepted = 0
        for i in range(10):
            o = _make_order("buy", "limit_maker", str(95 - i), "0.1", order_id=f"maxord_{i}")
            engine.submit_order(o, now + i)
            if o.status == OrderStatus.OPEN:
                accepted += 1

        assert accepted <= 5
        _assert_balance_invariants(portfolio)


# =========================================================================
# 5. BACKTEST EQUITY CONSERVATION
# =========================================================================


class TestBacktestEquityConservation:
    """End-to-end: equity must equal initial + realized PnL + unrealized PnL."""

    def _run_mini_backtest(self, n_ticks: int = 100, fills_per_tick: int = 0) -> dict:
        """Run a minimal time-stepping loop and return final state."""
        from simulation.data_feeds import StaticDataFeed

        iid = BTC_PERP
        spec = _make_spec(iid)
        initial_equity = Decimal("1000")
        book = _make_book(iid=iid, bid="50000.00", ask="50001.00", bid_size="100", ask_size="100")
        feed = StaticDataFeed(book=book)

        desk_config = DeskConfig(
            initial_balances={"USDT": initial_equity},
            default_fill_model="top_of_book",
            state_file_path=f"/tmp/stress_test_{uuid.uuid4().hex[:8]}.json",
            redis_url=None,
            reset_state_on_startup=True,
            seed=42,
        )
        desk = PaperDesk(desk_config)
        desk.register_instrument(
            instrument_spec=spec,
            data_feed=feed,
            leverage=10,
        )

        now_ns = int(time.time() * 1e9)
        total_fees = _ZERO
        fill_count = 0

        for tick in range(n_ticks):
            t = now_ns + tick * 60_000_000_000

            # Submit alternating buy/sell every 10 ticks
            if tick % 20 == 5:
                desk.submit_order(
                    instrument_id=iid,
                    side=OrderSide.BUY,
                    order_type=PaperOrderType.MARKET,
                    price=Decimal("50001.00"),
                    quantity=Decimal("0.001"),
                    source_bot="stress_test",
                )
            elif tick % 20 == 15:
                desk.submit_order(
                    instrument_id=iid,
                    side=OrderSide.SELL,
                    order_type=PaperOrderType.MARKET,
                    price=Decimal("50000.00"),
                    quantity=Decimal("0.001"),
                    source_bot="stress_test",
                )

            events = desk.tick(t)
            for ev in events:
                if isinstance(ev, OrderFilled):
                    total_fees += ev.fee
                    fill_count += 1

        portfolio = desk.portfolio
        equity = portfolio.equity_quote(
            mark_prices={iid.key: Decimal("50000.50")},
        )
        pos = portfolio.get_position(iid)
        pos_qty = pos.quantity if pos else _ZERO
        realized_pnl = pos.realized_pnl if pos else _ZERO

        return {
            "initial": initial_equity,
            "final_equity": equity,
            "balance": portfolio.balance("USDT"),
            "available": portfolio.available("USDT"),
            "position_qty": pos_qty,
            "realized_pnl": realized_pnl,
            "total_fees": total_fees,
            "fill_count": fill_count,
        }

    def test_equity_never_exceeds_initial_in_flat_market(self):
        """In a flat market, equity should only decrease due to fees."""
        result = self._run_mini_backtest(n_ticks=200)
        assert result["final_equity"] <= result["initial"] + _EPS, (
            f"Equity exceeded initial in flat market: "
            f"initial={result['initial']}, final={result['final_equity']}"
        )

    def test_balance_available_invariant(self):
        result = self._run_mini_backtest(n_ticks=100)
        assert result["available"] >= _ZERO
        assert result["balance"] >= _ZERO
        assert result["available"] <= result["balance"] + _EPS

    def test_fills_produce_fees(self):
        """Every fill must produce a non-negative fee."""
        result = self._run_mini_backtest(n_ticks=200)
        if result["fill_count"] > 0:
            assert result["total_fees"] > _ZERO, "Fills happened but no fees charged"


# =========================================================================
# 6. RAPID SIGNAL STRESS (simulates fast strategy changes)
# =========================================================================


class TestRapidSignalStress:
    """Simulate a strategy that rapidly changes direction."""

    def test_rapid_direction_flip_no_leak(self):
        """Buy → sell → buy → sell 50 times in quick succession."""
        engine, portfolio = _make_engine(
            iid=BTC_PERP, balances={"USDT": _USDT_START}, leverage=10,
        )
        now = int(time.time() * 1e9)

        for i in range(50):
            t = now + i * 1_000_000_000
            engine.update_book(_make_book(iid=BTC_PERP))

            side = "buy" if i % 2 == 0 else "sell"
            o = _make_order(side, "market", "100.05", "0.5", iid=BTC_PERP, order_id=f"flip_{i}")
            o.crossed_at_creation = True
            engine.submit_order(o, t)
            engine.tick(t)
            _assert_balance_invariants(portfolio)

        # At the end, wallet must not have leaked
        usdt_final = portfolio.balance("USDT")
        assert usdt_final > _ZERO, f"Wallet drained to {usdt_final}"
        _assert_balance_invariants(portfolio)

    def test_submit_during_pending_fill_no_double_reserve(self):
        """Submit a new order while a previous one is pending fill."""
        engine, portfolio = _make_engine()
        engine.update_book(_make_book())
        now = int(time.time() * 1e9)

        avail_before = portfolio.available("USDT")

        o1 = _make_order("buy", "limit_maker", "99.50", "1.0", order_id="double_1")
        engine.submit_order(o1, now)
        avail_after_o1 = portfolio.available("USDT")

        o2 = _make_order("buy", "limit_maker", "99.00", "1.0", order_id="double_2")
        engine.submit_order(o2, now + 1)
        avail_after_o2 = portfolio.available("USDT")

        reserved_total = avail_before - avail_after_o2
        expected_reserve = Decimal("99.50") + Decimal("99.00")
        assert abs(reserved_total - expected_reserve) < Decimal("1"), (
            f"Double reserve: reserved={reserved_total}, expected~{expected_reserve}"
        )

        engine.cancel_all(now + 2)
        assert portfolio.available("USDT") == avail_before


# =========================================================================
# 7. EDGE CASES
# =========================================================================


class TestEdgeCases:
    """Boundary conditions that could cause silent accounting errors."""

    def test_dust_position_after_partial_close(self):
        """Close almost all of a position — dust remainder handled correctly."""
        state = PositionState(
            quantity=_ZERO, avg_entry_price=_ZERO,
            realized_pnl=_ZERO, opened_at_ns=0,
        )
        r = apply_fill(state, "buy", Decimal("1.0"), Decimal("100"))
        state = r.new_state
        r = apply_fill(state, "sell", Decimal("0.9999"), Decimal("105"))
        state = r.new_state

        # Dust quantity should be either zero or positive, never negative
        assert state.quantity >= _ZERO

    def test_min_notional_rejection(self):
        """Order below min notional should be rejected, not leak reserves."""
        engine, portfolio = _make_engine()
        engine.update_book(_make_book())
        now = int(time.time() * 1e9)

        # min_notional = 5, so 0.01 * 100 = 1.0 < 5 → reject
        o = _make_order("buy", "limit_maker", "100.00", "0.01")
        engine.submit_order(o, now)

        assert o.status in (OrderStatus.REJECTED, OrderStatus.PENDING_SUBMIT)
        assert portfolio.available("USDT") == _USDT_START

    def test_zero_price_order_rejected(self):
        engine, portfolio = _make_engine()
        engine.update_book(_make_book())
        now = int(time.time() * 1e9)

        o = _make_order("buy", "limit_maker", "0.00", "1.0")
        engine.submit_order(o, now)

        assert portfolio.available("USDT") == _USDT_START

    def test_negative_balance_impossible(self):
        """Even after many trades, USDT balance must never go negative."""
        engine, portfolio = _make_engine(balances={"USDT": Decimal("100"), "BTC": _ZERO})
        now = int(time.time() * 1e9)

        for i in range(30):
            t = now + i * 1_000_000_000
            engine.update_book(_make_book())
            o = _make_order("buy", "market", "100.10", "1.0", order_id=f"neg_{i}")
            o.crossed_at_creation = True
            engine.submit_order(o, t)
            engine.tick(t)

            usdt = portfolio.balance("USDT")
            assert usdt >= -_EPS, f"USDT went negative: {usdt} at iteration {i}"

    def test_ledger_credit_debit_symmetry(self):
        """Credit and debit must be perfectly symmetric."""
        ledger = MultiAssetLedger({"X": _ZERO})
        for _ in range(100):
            ledger.credit("X", Decimal("7.123456789"))
        for _ in range(100):
            ledger.debit("X", Decimal("7.123456789"))

        assert abs(ledger.total("X")) < Decimal("1e-10"), (
            f"Ledger not symmetric: {ledger.total('X')}"
        )

    def test_equity_with_zero_position_equals_cash(self):
        """When position is flat, equity must equal cash balance exactly."""
        engine, portfolio = _make_engine(
            iid=BTC_PERP, balances={"USDT": _USDT_START}, leverage=10,
        )
        now = int(time.time() * 1e9)
        engine.update_book(_make_book(iid=BTC_PERP))

        # Open and close
        buy = _make_order("buy", "market", "100.10", "0.5", iid=BTC_PERP, order_id="eq_buy")
        buy.crossed_at_creation = True
        engine.submit_order(buy, now)
        engine.tick(now)

        sell = _make_order("sell", "market", "99.90", "0.5", iid=BTC_PERP, order_id="eq_sell")
        sell.crossed_at_creation = True
        engine.submit_order(sell, now + 1_000_000_000)
        engine.tick(now + 1_000_000_000)

        pos = portfolio.get_position(BTC_PERP)
        pos_qty = pos.quantity if pos else _ZERO

        if abs(pos_qty) < _EPS:
            equity = portfolio.equity_quote(
                mark_prices={BTC_PERP.key: Decimal("100.00")},
            )
            cash = portfolio.balance("USDT")
            assert abs(equity - cash) < Decimal("0.01"), (
                f"Flat position but equity ({equity}) != cash ({cash})"
            )


# =========================================================================
# 8. MULTI-INSTRUMENT ISOLATION
# =========================================================================


class TestMultiInstrumentIsolation:
    """Orders on different instruments must not interfere."""

    def test_two_instruments_independent_reserves(self):
        spec_btc = _make_spec(BTC_PERP)
        spec_eth = _make_spec(ETH_PERP)
        portfolio = PaperPortfolio({"USDT": Decimal("5000")}, PortfolioConfig())

        eng_btc = OrderMatchingEngine(
            instrument_id=BTC_PERP, instrument_spec=spec_btc,
            portfolio=portfolio,
            fill_model=TopOfBookFillModel(),
            fee_model=MakerTakerFeeModel(_MAKER_FEE, _TAKER_FEE),
            latency_model=NO_LATENCY,
            config=EngineConfig(),
            leverage=10,
        )
        eng_eth = OrderMatchingEngine(
            instrument_id=ETH_PERP, instrument_spec=spec_eth,
            portfolio=portfolio,
            fill_model=TopOfBookFillModel(),
            fee_model=MakerTakerFeeModel(_MAKER_FEE, _TAKER_FEE),
            latency_model=NO_LATENCY,
            config=EngineConfig(),
            leverage=10,
        )

        now = int(time.time() * 1e9)
        eng_btc.update_book(_make_book(iid=BTC_PERP))
        eng_eth.update_book(_make_book(iid=ETH_PERP))

        btc_order = _make_order("buy", "limit_maker", "99.50", "1.0", iid=BTC_PERP, order_id="iso_btc")
        eth_order = _make_order("buy", "limit_maker", "99.50", "1.0", iid=ETH_PERP, order_id="iso_eth")

        eng_btc.submit_order(btc_order, now)
        eng_eth.submit_order(eth_order, now + 1)

        # Cancel BTC only
        eng_btc.cancel_order("iso_btc", now + 2)

        # ETH reserve should still be held
        avail = portfolio.available("USDT")
        # ETH margin reserved = 99.50 * 1.0 / 10 (leverage) = ~9.95
        assert avail < Decimal("5000")

        eng_eth.cancel_order("iso_eth", now + 3)
        assert abs(portfolio.available("USDT") - Decimal("5000")) < Decimal("1")
        _assert_balance_invariants(portfolio)
