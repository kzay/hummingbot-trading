"""Stress tests for backtest harness — equity tracking, metrics correctness.

Validates:
1. Metric calculations under edge conditions (Sharpe, Sortino, drawdown)
2. Round-trip PnL matching via FIFO
3. Fill recording completeness
4. Determinism — same seed produces identical results
"""
from __future__ import annotations

import math
from decimal import Decimal

from controllers.backtesting.metrics import (
    calmar_ratio,
    compute_drawdown,
    compute_round_trips,
    daily_returns,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    total_return_pct,
    win_rate,
)
from controllers.backtesting.types import EquitySnapshot, FillRecord

_ZERO = Decimal("0")
_EPS = Decimal("1e-8")


def _snap(date: str, equity: str, dd: str = "0", dr: str = "0",
          cr: str = "0", pn: str = "0", fills: int = 0) -> EquitySnapshot:
    return EquitySnapshot(
        date=date,
        equity=Decimal(equity),
        drawdown_pct=Decimal(dd),
        daily_return_pct=Decimal(dr),
        cumulative_return_pct=Decimal(cr),
        position_notional=Decimal(pn),
        num_fills=fills,
    )


def _fill(side: str, price: str, qty: str, fee: str, ts_ns: int = 0) -> FillRecord:
    return FillRecord(
        timestamp_ns=ts_ns,
        order_id=f"ord_{ts_ns}",
        side=side,
        fill_price=Decimal(price),
        fill_quantity=Decimal(qty),
        fee=Decimal(fee),
        is_maker=True,
        slippage_bps=Decimal("0"),
        mid_slippage_bps=Decimal("0"),
    )


# =========================================================================
# 1. SHARPE / SORTINO EDGE CASES
# =========================================================================


class TestSharpeEdgeCases:

    def test_empty_curve(self):
        assert daily_returns([]) == []
        assert sharpe_ratio([]) == 0.0

    def test_single_snapshot(self):
        curve = [_snap("2025-01-01", "100")]
        assert daily_returns(curve) == []
        assert sharpe_ratio(daily_returns(curve)) == 0.0

    def test_two_snapshots(self):
        curve = [_snap("2025-01-01", "100"), _snap("2025-01-02", "110")]
        returns = daily_returns(curve)
        assert len(returns) == 1
        assert sharpe_ratio(returns) == 0.0  # need >= 2 returns

    def test_constant_equity(self):
        """Flat equity → zero returns → std = 0 → Sharpe = 0."""
        curve = [_snap(f"2025-01-{i+1:02d}", "100") for i in range(30)]
        returns = daily_returns(curve)
        assert sharpe_ratio(returns) == 0.0

    def test_monotonic_up(self):
        curve = [_snap(f"2025-01-{i+1:02d}", str(100 + i)) for i in range(30)]
        returns = daily_returns(curve)
        result = sharpe_ratio(returns)
        assert result > 0, f"Expected positive Sharpe, got {result}"
        assert not math.isnan(result)

    def test_monotonic_down(self):
        curve = [_snap(f"2025-01-{i+1:02d}", str(100 - i * 0.5)) for i in range(30)]
        returns = daily_returns(curve)
        result = sharpe_ratio(returns)
        assert result < 0, f"Expected negative Sharpe, got {result}"

    def test_mixed_returns_finite(self):
        prices = [100, 105, 98, 110, 95, 102, 108, 97, 115, 100,
                  103, 99, 107, 94, 112, 101, 106, 98, 111, 96]
        curve = [_snap(f"2025-01-{i+1:02d}", str(p)) for i, p in enumerate(prices)]
        returns = daily_returns(curve)
        s = sharpe_ratio(returns)
        assert not math.isnan(s)
        assert not math.isinf(s)


class TestSortinoEdgeCases:

    def test_empty(self):
        assert sortino_ratio([]) == 0.0

    def test_all_positive(self):
        """No downside → downside deviation = 0 → Sortino = 0."""
        returns = [0.01, 0.02, 0.015, 0.008, 0.012]
        result = sortino_ratio(returns)
        assert result == 0.0

    def test_mixed(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.008]
        result = sortino_ratio(returns)
        assert not math.isnan(result)
        assert not math.isinf(result)


# =========================================================================
# 2. DRAWDOWN
# =========================================================================


class TestDrawdown:

    def test_empty(self):
        dd = compute_drawdown([])
        assert dd.max_drawdown_pct == 0.0

    def test_single(self):
        dd = compute_drawdown([_snap("2025-01-01", "100")])
        assert dd.max_drawdown_pct == 0.0

    def test_monotonic_up_zero_drawdown(self):
        curve = [_snap(f"2025-01-{i+1:02d}", str(100 + i)) for i in range(10)]
        dd = compute_drawdown(curve)
        assert dd.max_drawdown_pct == 0.0

    def test_monotonic_down_increasing_drawdown(self):
        curve = [_snap(f"2025-01-{i+1:02d}", str(100 - i * 5)) for i in range(10)]
        dd = compute_drawdown(curve)
        assert dd.max_drawdown_pct > 0
        # Max DD = (100 - 55) / 100 = 45%
        assert abs(dd.max_drawdown_pct - 45.0) < 1.0

    def test_dip_and_recovery(self):
        curve = [
            _snap("2025-01-01", "100"),
            _snap("2025-01-02", "90"),
            _snap("2025-01-03", "80"),
            _snap("2025-01-04", "95"),
            _snap("2025-01-05", "100"),
        ]
        dd = compute_drawdown(curve)
        # Max DD was 20% (100 → 80)
        assert abs(dd.max_drawdown_pct - 20.0) < 1.0


# =========================================================================
# 3. TOTAL RETURN
# =========================================================================


class TestTotalReturn:

    def test_empty(self):
        assert total_return_pct([]) == 0.0

    def test_single(self):
        assert total_return_pct([_snap("2025-01-01", "100")]) == 0.0

    def test_positive(self):
        curve = [_snap("2025-01-01", "100"), _snap("2025-01-02", "110")]
        result = total_return_pct(curve)
        assert abs(result - 10.0) < 0.01

    def test_negative(self):
        curve = [_snap("2025-01-01", "100"), _snap("2025-01-02", "90")]
        result = total_return_pct(curve)
        assert abs(result - (-10.0)) < 0.01

    def test_zero_start_equity(self):
        curve = [_snap("2025-01-01", "0"), _snap("2025-01-02", "100")]
        result = total_return_pct(curve)
        assert result == 0.0  # guard against division by zero

    def test_calmar_zero_dd(self):
        assert calmar_ratio(10.0, 0.0) == 0.0

    def test_calmar_normal(self):
        result = calmar_ratio(10.0, 5.0)
        assert abs(result - 2.0) < 0.01


# =========================================================================
# 4. ROUND-TRIP MATCHING
# =========================================================================


class TestRoundTripMatching:

    def test_simple_round_trip(self):
        fills = [
            _fill("buy", "100", "1.0", "0.02", 1),
            _fill("sell", "110", "1.0", "0.022", 2),
        ]
        rt = compute_round_trips(fills)
        assert rt.total_count == 1
        assert rt.gross_profit > _ZERO

    def test_short_round_trip(self):
        fills = [
            _fill("sell", "110", "1.0", "0.022", 1),
            _fill("buy", "100", "1.0", "0.02", 2),
        ]
        rt = compute_round_trips(fills)
        assert rt.total_count == 1
        assert rt.gross_profit > _ZERO

    def test_no_fills(self):
        rt = compute_round_trips([])
        assert rt.total_count == 0
        assert rt.gross_profit == _ZERO
        assert rt.gross_loss == _ZERO

    def test_single_fill_no_trip(self):
        fills = [_fill("buy", "100", "1.0", "0.02", 1)]
        rt = compute_round_trips(fills)
        assert rt.total_count == 0

    def test_multiple_buys_single_sell(self):
        """FIFO: 2 buys, 1 sell closes first buy only."""
        fills = [
            _fill("buy", "100", "1.0", "0.02", 1),
            _fill("buy", "105", "1.0", "0.021", 2),
            _fill("sell", "110", "1.0", "0.022", 3),
        ]
        rt = compute_round_trips(fills)
        assert rt.total_count == 1
        assert rt.win_count == 1


# =========================================================================
# 5. WIN RATE AND PROFIT FACTOR
# =========================================================================


class TestWinRateProfitFactor:

    def test_win_rate_all_winners(self):
        fills = [
            _fill("buy", "100", "1.0", "0.01", 1),
            _fill("sell", "110", "1.0", "0.01", 2),
            _fill("buy", "100", "1.0", "0.01", 3),
            _fill("sell", "105", "1.0", "0.01", 4),
        ]
        assert win_rate(fills) == 1.0

    def test_win_rate_all_losers(self):
        fills = [
            _fill("buy", "110", "1.0", "0.01", 1),
            _fill("sell", "100", "1.0", "0.01", 2),
            _fill("buy", "105", "1.0", "0.01", 3),
            _fill("sell", "100", "1.0", "0.01", 4),
        ]
        assert win_rate(fills) == 0.0

    def test_win_rate_empty(self):
        assert win_rate([]) == 0.0

    def test_profit_factor_normal(self):
        result = profit_factor(Decimal("13"), Decimal("5"))
        assert abs(result - 2.6) < 0.01

    def test_profit_factor_no_losses(self):
        result = profit_factor(Decimal("10"), _ZERO)
        assert result == float("inf")

    def test_profit_factor_no_wins(self):
        result = profit_factor(_ZERO, Decimal("5"))
        assert result == 0.0

    def test_profit_factor_both_zero(self):
        result = profit_factor(_ZERO, _ZERO)
        assert result == 0.0


# =========================================================================
# 6. DAILY RETURNS EDGE CASES
# =========================================================================


class TestDailyReturns:

    def test_normal(self):
        curve = [
            _snap("2025-01-01", "100"),
            _snap("2025-01-02", "110"),
            _snap("2025-01-03", "105"),
        ]
        returns = daily_returns(curve)
        assert len(returns) == 2
        assert abs(returns[0] - 0.10) < 0.001
        expected_r2 = (105 - 110) / 110
        assert abs(returns[1] - expected_r2) < 0.001

    def test_single_point(self):
        assert daily_returns([_snap("2025-01-01", "100")]) == []

    def test_empty(self):
        assert daily_returns([]) == []


# =========================================================================
# 7. DETERMINISM
# =========================================================================


class TestDeterminism:

    def test_accounting_deterministic(self):
        """Same sequence of fills → same final state."""
        from simulation.accounting import PositionState, apply_fill

        _Z = Decimal("0")

        def _run():
            state = PositionState(quantity=_Z, avg_entry_price=_Z, realized_pnl=_Z, opened_at_ns=0)
            for price in [100, 105, 98, 110, 95, 102]:
                r = apply_fill(state, "buy", Decimal("0.5"), Decimal(str(price)))
                state = r.new_state
            for price in [108, 112, 99, 115]:
                r = apply_fill(state, "sell", Decimal("0.5"), Decimal(str(price)))
                state = r.new_state
            return state

        s1 = _run()
        s2 = _run()
        assert s1.quantity == s2.quantity
        assert s1.avg_entry_price == s2.avg_entry_price
        assert s1.realized_pnl == s2.realized_pnl

    def test_metrics_deterministic(self):
        curve = [_snap(f"2025-{(i//28)+1:02d}-{(i%28)+1:02d}", str(100 + i * 0.5 + (i % 3) * -0.3))
                 for i in range(100)]
        r1 = daily_returns(curve)
        r2 = daily_returns(curve)
        assert r1 == r2

        s1 = sharpe_ratio(r1)
        s2 = sharpe_ratio(r2)
        assert s1 == s2

    def test_round_trip_deterministic(self):
        fills = [
            _fill("buy", "100", "1.0", "0.02", 1),
            _fill("sell", "110", "1.0", "0.022", 2),
            _fill("buy", "105", "0.5", "0.01", 3),
            _fill("sell", "115", "0.5", "0.011", 4),
        ]
        rt1 = compute_round_trips(fills)
        rt2 = compute_round_trips(fills)
        assert rt1.win_count == rt2.win_count
        assert rt1.loss_count == rt2.loss_count
        assert rt1.gross_profit == rt2.gross_profit
        assert rt1.gross_loss == rt2.gross_loss
