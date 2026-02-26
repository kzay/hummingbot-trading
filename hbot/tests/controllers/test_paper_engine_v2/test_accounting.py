"""Deterministic scenario matrix tests for accounting.py core.

Each test vector describes a sequence of fills and the expected
position state after each fill. This is the authoritative regression
suite for position PnL math — all edge cases should be added here.

Invariants under test:
  1. realized_pnl = pure price PnL only
  2. avg_entry = VWAP over same-direction fills
  3. Flip: realized computed for close leg, re-open at fill_price
  4. Flat detection with EPS tolerance
"""
from decimal import Decimal

import pytest

from controllers.paper_engine_v2.accounting import (
    FillResult,
    FillTransition,
    PositionSide,
    PositionState,
    apply_fill,
    position_side,
    unrealized_pnl,
    vwap_avg_entry,
)

_Z = Decimal("0")


def _state(qty="0", avg="0", rpnl="0") -> PositionState:
    return PositionState(
        quantity=Decimal(qty),
        avg_entry_price=Decimal(avg),
        realized_pnl=Decimal(rpnl),
        opened_at_ns=0,
    )


def _fill(state: PositionState, side: str, qty: str, price: str, now_ns: int = 1) -> FillResult:
    return apply_fill(state, side, Decimal(qty), Decimal(price), now_ns)


# ---------------------------------------------------------------------------
# Transition classification
# ---------------------------------------------------------------------------

class TestTransitionClassification:
    def test_flat_buy_is_open(self):
        r = _fill(_state(), "buy", "1", "100")
        assert r.transition == FillTransition.OPEN

    def test_flat_sell_is_open(self):
        r = _fill(_state(), "sell", "1", "100")
        assert r.transition == FillTransition.OPEN

    def test_long_buy_is_add(self):
        s = _fill(_state(), "buy", "1", "100").new_state
        r = _fill(s, "buy", "0.5", "110")
        assert r.transition == FillTransition.ADD

    def test_short_sell_is_add(self):
        s = _fill(_state(), "sell", "1", "100").new_state
        r = _fill(s, "sell", "0.5", "90")
        assert r.transition == FillTransition.ADD

    def test_long_partial_sell_is_reduce(self):
        s = _fill(_state(), "buy", "2", "100").new_state
        r = _fill(s, "sell", "1", "110")
        assert r.transition == FillTransition.REDUCE

    def test_long_full_sell_is_close(self):
        s = _fill(_state(), "buy", "1", "100").new_state
        r = _fill(s, "sell", "1", "110")
        assert r.transition == FillTransition.CLOSE

    def test_long_oversell_is_flip(self):
        s = _fill(_state(), "buy", "1", "100").new_state
        r = _fill(s, "sell", "2", "110")
        assert r.transition == FillTransition.FLIP

    def test_short_overbuy_is_flip(self):
        s = _fill(_state(), "sell", "1", "100").new_state
        r = _fill(s, "buy", "2", "90")
        assert r.transition == FillTransition.FLIP


# ---------------------------------------------------------------------------
# Open position
# ---------------------------------------------------------------------------

class TestOpenPosition:
    def test_open_long_qty_and_avg(self):
        r = _fill(_state(), "buy", "1", "100")
        assert r.new_state.quantity == Decimal("1")
        assert r.new_state.avg_entry_price == Decimal("100")
        assert r.new_state.realized_pnl == _Z

    def test_open_short_qty_and_avg(self):
        r = _fill(_state(), "sell", "1", "100")
        assert r.new_state.quantity == Decimal("-1")
        assert r.new_state.avg_entry_price == Decimal("100")
        assert r.new_state.realized_pnl == _Z

    def test_open_sets_open_qty_metadata(self):
        r = _fill(_state(), "buy", "2", "100")
        assert r.open_quantity == Decimal("2")
        assert r.close_quantity == _Z
        assert r.fill_realized_pnl == _Z


# ---------------------------------------------------------------------------
# Adding to position (VWAP avg entry)
# ---------------------------------------------------------------------------

class TestAddPosition:
    def test_add_long_vwap(self):
        s = _fill(_state(), "buy", "1", "100").new_state
        r = _fill(s, "buy", "1", "200")
        # VWAP: (1*100 + 1*200) / 2 = 150
        assert r.new_state.avg_entry_price == Decimal("150")
        assert r.new_state.quantity == Decimal("2")
        assert r.fill_realized_pnl == _Z

    def test_add_long_unequal_lots(self):
        s = _fill(_state(), "buy", "2", "100").new_state
        r = _fill(s, "buy", "1", "130")
        # VWAP: (2*100 + 1*130) / 3 = 110
        assert r.new_state.avg_entry_price == Decimal("110")

    def test_add_short_vwap(self):
        s = _fill(_state(), "sell", "1", "100").new_state
        r = _fill(s, "sell", "1", "80")
        # VWAP: (1*100 + 1*80) / 2 = 90
        assert r.new_state.avg_entry_price == Decimal("90")
        assert r.new_state.quantity == Decimal("-2")

    def test_add_no_realized_pnl(self):
        s = _fill(_state(), "buy", "1", "100").new_state
        r = _fill(s, "buy", "0.5", "150")
        assert r.fill_realized_pnl == _Z
        assert r.new_state.realized_pnl == _Z


# ---------------------------------------------------------------------------
# Reduce (partial close)
# ---------------------------------------------------------------------------

class TestReducePosition:
    def test_reduce_long_partial(self):
        s = _fill(_state(), "buy", "2", "100").new_state
        r = _fill(s, "sell", "1", "120")
        # close_qty = 1, direction = +1, pnl = (120-100)*1 = 20
        assert r.fill_realized_pnl == Decimal("20")
        assert r.new_state.quantity == Decimal("1")
        # avg_entry unchanged after partial close
        assert r.new_state.avg_entry_price == Decimal("100")

    def test_reduce_short_partial(self):
        s = _fill(_state(), "sell", "2", "100").new_state
        r = _fill(s, "buy", "1", "80")
        # close_qty = 1, direction = -1, pnl = (80-100)*1*(-1) = 20
        assert r.fill_realized_pnl == Decimal("20")
        assert r.new_state.quantity == Decimal("-1")
        assert r.new_state.avg_entry_price == Decimal("100")

    def test_reduce_accumulates_realized_pnl(self):
        s = _fill(_state(), "buy", "3", "100").new_state
        s2 = _fill(s, "sell", "1", "120").new_state  # +20
        r = _fill(s2, "sell", "1", "110")             # +10
        assert r.fill_realized_pnl == Decimal("10")
        assert r.new_state.realized_pnl == Decimal("30")

    def test_reduce_loss(self):
        s = _fill(_state(), "buy", "1", "100").new_state
        r = _fill(s, "sell", "0.5", "80")
        # pnl = (80 - 100) * 0.5 = -10
        assert r.fill_realized_pnl == Decimal("-10")


# ---------------------------------------------------------------------------
# Full close
# ---------------------------------------------------------------------------

class TestClosePosition:
    def test_close_long_goes_flat(self):
        s = _fill(_state(), "buy", "1", "100").new_state
        r = _fill(s, "sell", "1", "130")
        assert r.new_state.quantity == _Z
        assert r.new_state.avg_entry_price == _Z
        assert r.fill_realized_pnl == Decimal("30")

    def test_close_short_goes_flat(self):
        s = _fill(_state(), "sell", "1", "100").new_state
        r = _fill(s, "buy", "1", "70")
        assert r.new_state.quantity == _Z
        assert r.fill_realized_pnl == Decimal("30")

    def test_close_long_loss(self):
        s = _fill(_state(), "buy", "1", "100").new_state
        r = _fill(s, "sell", "1", "90")
        assert r.fill_realized_pnl == Decimal("-10")

    def test_close_sets_avg_entry_zero(self):
        s = _fill(_state(), "buy", "1", "100").new_state
        r = _fill(s, "sell", "1", "110")
        assert r.new_state.avg_entry_price == _Z

    def test_close_resets_opened_at(self):
        s = _fill(_state(), "buy", "1", "100", now_ns=1000).new_state
        r = _fill(s, "sell", "1", "110", now_ns=2000)
        assert r.new_state.opened_at_ns == 0


# ---------------------------------------------------------------------------
# Position flip (cross zero)
# ---------------------------------------------------------------------------

class TestFlip:
    def test_flip_long_to_short(self):
        """V6 test vector from spec: open long 1.0, sell 2.0."""
        s = _fill(_state(), "buy", "1", "100").new_state
        r = _fill(s, "sell", "2", "120")
        # Close 1.0 long @ 120: pnl = (120-100)*1 = 20
        assert r.fill_realized_pnl == Decimal("20")
        # Re-open 1.0 short @ 120
        assert r.new_state.quantity == Decimal("-1")
        assert r.new_state.avg_entry_price == Decimal("120")
        assert r.transition == FillTransition.FLIP

    def test_flip_short_to_long(self):
        s = _fill(_state(), "sell", "1", "100").new_state
        r = _fill(s, "buy", "2", "80")
        # Close 1.0 short @ 80: pnl = (80-100)*1*(-1) = 20
        assert r.fill_realized_pnl == Decimal("20")
        # Re-open 1.0 long @ 80
        assert r.new_state.quantity == Decimal("1")
        assert r.new_state.avg_entry_price == Decimal("80")

    def test_flip_preserves_cumulative_pnl(self):
        s = _fill(_state(), "buy", "1", "100").new_state
        s2 = _fill(s, "buy", "1", "110").new_state   # avg = 105
        r = _fill(s2, "sell", "4", "120")             # close 2@105, open 2 short
        # pnl for close: (120-105)*2 = 30
        assert r.fill_realized_pnl == Decimal("30")
        assert r.new_state.quantity == Decimal("-2")
        assert r.new_state.avg_entry_price == Decimal("120")

    def test_flip_close_qty_metadata(self):
        s = _fill(_state(), "buy", "1", "100").new_state
        r = _fill(s, "sell", "3", "110")
        assert r.close_quantity == Decimal("1")
        assert r.open_quantity == Decimal("2")

    def test_flip_loss(self):
        s = _fill(_state(), "buy", "1", "100").new_state
        r = _fill(s, "sell", "2", "90")
        # Close 1 long @ 90: pnl = (90-100)*1 = -10
        assert r.fill_realized_pnl == Decimal("-10")
        assert r.new_state.quantity == Decimal("-1")
        assert r.new_state.avg_entry_price == Decimal("90")


# ---------------------------------------------------------------------------
# EPS / dust tolerance
# ---------------------------------------------------------------------------

class TestDustTolerance:
    def test_tiny_residual_goes_flat(self):
        # Fill that should bring qty to zero except for floating dust.
        s = PositionState(
            quantity=Decimal("1e-11"),   # within EPS
            avg_entry_price=Decimal("100"),
            realized_pnl=_Z,
            opened_at_ns=0,
        )
        r = _fill(s, "sell", "1e-11", "100")
        assert r.new_state.quantity == _Z

    def test_zero_fill_qty_noop(self):
        s = _fill(_state(), "buy", "1", "100").new_state
        original_qty = s.quantity
        r = apply_fill(s, "sell", _Z, Decimal("200"))
        assert r.new_state.quantity == original_qty
        assert r.fill_realized_pnl == _Z


# ---------------------------------------------------------------------------
# Multi-fill sequences
# ---------------------------------------------------------------------------

class TestMultiFillSequence:
    def test_scalp_sequence(self):
        """Buy 1 @ 100, sell 0.5 @ 110, sell 0.5 @ 120 → net pnl = 15"""
        s = _fill(_state(), "buy", "1", "100").new_state
        s = _fill(s, "sell", "0.5", "110").new_state   # pnl = 5
        r = _fill(s, "sell", "0.5", "120")              # pnl = 10
        assert r.new_state.quantity == _Z
        assert r.new_state.realized_pnl == Decimal("15")

    def test_pyramid_and_close(self):
        """
        Buy 1 @ 100 (avg=100)
        Buy 2 @ 200 (avg=166.67)
        Sell 3 @ 250 → pnl = (250 - 500/3) * 3 = 250
        """
        s = _fill(_state(), "buy", "1", "100").new_state
        s = _fill(s, "buy", "2", "200").new_state
        expected_avg = Decimal("500") / Decimal("3")
        assert abs(s.avg_entry_price - expected_avg) < Decimal("0.01")
        r = _fill(s, "sell", "3", "250")
        expected_pnl = (Decimal("250") - expected_avg) * Decimal("3")
        assert abs(r.fill_realized_pnl - expected_pnl) < Decimal("0.01")
        assert r.new_state.quantity == _Z

    def test_double_flip(self):
        """Long 1 → flip short 2 → flip long 3 → check state."""
        s0 = _fill(_state(), "buy", "1", "100").new_state
        s1 = _fill(s0, "sell", "3", "110").new_state   # flip: short 2
        assert s1.quantity == Decimal("-2")
        assert s1.avg_entry_price == Decimal("110")
        s2 = _fill(s1, "buy", "5", "90").new_state     # flip: long 3
        assert s2.quantity == Decimal("3")
        assert s2.avg_entry_price == Decimal("90")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_position_side_flat(self):
        assert position_side(_Z) == PositionSide.FLAT

    def test_position_side_long(self):
        assert position_side(Decimal("1")) == PositionSide.LONG

    def test_position_side_short(self):
        assert position_side(Decimal("-1")) == PositionSide.SHORT

    def test_vwap_avg_entry(self):
        # 2 units @ 100, add 1 unit @ 130 → vwap = (200+130)/3 = 110
        result = vwap_avg_entry(Decimal("2"), Decimal("100"), Decimal("1"), Decimal("130"))
        assert result == Decimal("110")

    def test_vwap_zero_old_qty(self):
        result = vwap_avg_entry(_Z, _Z, Decimal("1"), Decimal("150"))
        assert result == Decimal("150")

    def test_unrealized_pnl_long_profit(self):
        pnl = unrealized_pnl(Decimal("1"), Decimal("100"), Decimal("120"))
        assert pnl == Decimal("20")

    def test_unrealized_pnl_long_loss(self):
        pnl = unrealized_pnl(Decimal("1"), Decimal("100"), Decimal("80"))
        assert pnl == Decimal("-20")

    def test_unrealized_pnl_short_profit(self):
        pnl = unrealized_pnl(Decimal("-1"), Decimal("100"), Decimal("80"))
        assert pnl == Decimal("20")

    def test_unrealized_pnl_flat(self):
        pnl = unrealized_pnl(_Z, Decimal("100"), Decimal("120"))
        assert pnl == _Z

    def test_unrealized_pnl_zero_price(self):
        pnl = unrealized_pnl(Decimal("1"), Decimal("100"), _Z)
        assert pnl == _Z
