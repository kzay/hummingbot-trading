"""Tests for backtesting metrics module."""
from __future__ import annotations

from decimal import Decimal

import pytest

from controllers.backtesting.metrics import (
    cagr_pct,
    compute_drawdown,
    compute_round_trips,
    daily_returns,
    fee_attribution,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    total_return_pct,
    turnover_metrics,
    win_rate,
)
from controllers.backtesting.types import EquitySnapshot, FillRecord

# Note: cagr_pct(equity_curve), fee_attribution(fills), turnover_metrics(fills, equity_curve)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_equity_curve(equities: list[float]) -> list[EquitySnapshot]:
    """Build a simple equity curve from a list of equity values."""
    snaps = []
    prev = equities[0] if equities else 100
    for i, eq in enumerate(equities):
        daily_ret = (eq - prev) / prev if prev > 0 else 0
        snaps.append(EquitySnapshot(
            date=f"2025-01-{i + 1:02d}",
            equity=Decimal(str(eq)),
            drawdown_pct=Decimal("0"),
            daily_return_pct=Decimal(str(daily_ret)),
            cumulative_return_pct=Decimal(str((eq - equities[0]) / equities[0])) if equities[0] > 0 else Decimal("0"),
            position_notional=Decimal("0"),
            num_fills=0,
        ))
        prev = eq
    return snaps


def _make_fill(price: float, qty: float, side: str, fee: float = 0.01, is_maker: bool = True) -> FillRecord:
    return FillRecord(
        timestamp_ns=1_000_000_000,
        order_id="test",
        side=side,
        fill_price=Decimal(str(price)),
        fill_quantity=Decimal(str(qty)),
        fee=Decimal(str(fee)),
        is_maker=is_maker,
        slippage_bps=Decimal("1.0"),
        mid_slippage_bps=Decimal("1.0"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDailyReturns:
    def test_basic(self):
        curve = _make_equity_curve([100, 102, 101, 105])
        rets = daily_returns(curve)
        assert len(rets) == 3
        assert abs(rets[0] - 0.02) < 1e-6
        assert abs(rets[1] - (-1 / 102)) < 1e-4

    def test_empty(self):
        assert daily_returns([]) == []

    def test_single_point(self):
        curve = _make_equity_curve([100])
        assert daily_returns(curve) == []


class TestSharpeRatio:
    def test_positive_returns(self):
        # Consistently positive returns → positive Sharpe
        curve = _make_equity_curve([100, 101, 102, 103, 104, 105])
        rets = daily_returns(curve)
        sr = sharpe_ratio(rets)
        assert sr > 0

    def test_flat_equity(self):
        # No variance → Sharpe 0
        curve = _make_equity_curve([100, 100, 100, 100])
        rets = daily_returns(curve)
        sr = sharpe_ratio(rets)
        assert sr == 0.0

    def test_no_returns(self):
        assert sharpe_ratio([]) == 0.0


class TestSortinoRatio:
    def test_no_downside(self):
        # All positive returns → only denominator from downside = 0
        rets = [0.01, 0.02, 0.005, 0.015]
        sr = sortino_ratio(rets)
        # With no downside, should be large (or 0 if implementation guards)
        assert sr >= 0

    def test_empty(self):
        assert sortino_ratio([]) == 0.0


class TestTotalReturn:
    def test_basic(self):
        curve = _make_equity_curve([100, 110])
        ret = total_return_pct(curve)
        assert abs(ret - 10.0) < 0.01

    def test_loss(self):
        curve = _make_equity_curve([100, 90])
        ret = total_return_pct(curve)
        assert abs(ret - (-10.0)) < 0.01


class TestCagr:
    def test_one_year_double(self):
        # Doubling in ~252 trading days → CAGR ~100%
        curve = _make_equity_curve([100] + [200] * 252)
        pct = cagr_pct(curve)
        assert pct > 80.0  # Should be near 100%

    def test_single_point(self):
        curve = _make_equity_curve([100])
        assert cagr_pct(curve) == 0.0


class TestDrawdown:
    def test_basic_drawdown(self):
        curve = _make_equity_curve([100, 110, 105, 95, 100])
        dd = compute_drawdown(curve)
        # Max drawdown from 110 → 95 = 13.6%
        assert dd.max_drawdown_pct > 10.0
        assert dd.max_drawdown_pct < 20.0

    def test_no_drawdown(self):
        curve = _make_equity_curve([100, 101, 102, 103])
        dd = compute_drawdown(curve)
        assert dd.max_drawdown_pct == 0.0


class TestFeeAttribution:
    def test_basic(self):
        fills = [
            _make_fill(100, 1.0, "buy", 0.02, True),
            _make_fill(101, 1.0, "sell", 0.06, False),
        ]
        result = fee_attribution(fills)
        assert float(result["total_fees"]) == pytest.approx(0.08, abs=0.001)
        assert float(result["maker_fill_ratio"]) == pytest.approx(0.5)

    def test_empty(self):
        result = fee_attribution([])
        assert float(result["total_fees"]) == 0.0


class TestTurnover:
    def test_basic(self):
        fills = [
            _make_fill(100, 1.0, "buy"),
            _make_fill(101, 1.0, "sell"),
        ]
        curve = _make_equity_curve([100, 100])
        result = turnover_metrics(fills, curve)
        assert result["total_notional"] == pytest.approx(201.0, abs=1.0)


# ---------------------------------------------------------------------------
# Win rate & round-trip matching
# ---------------------------------------------------------------------------

class TestWinRate:
    def test_empty_fills(self):
        assert win_rate([]) == 0.0

    def test_single_winning_round_trip(self):
        fills = [
            _make_fill(100, 1.0, "buy", fee=0.0),
            _make_fill(110, 1.0, "sell", fee=0.0),
        ]
        assert win_rate(fills) == 1.0

    def test_single_losing_round_trip(self):
        fills = [
            _make_fill(110, 1.0, "buy", fee=0.0),
            _make_fill(100, 1.0, "sell", fee=0.0),
        ]
        assert win_rate(fills) == 0.0

    def test_mixed_round_trips(self):
        fills = [
            _make_fill(100, 1.0, "buy", fee=0.0),
            _make_fill(110, 1.0, "sell", fee=0.0),   # win
            _make_fill(120, 1.0, "buy", fee=0.0),
            _make_fill(115, 1.0, "sell", fee=0.0),   # loss
        ]
        assert win_rate(fills) == pytest.approx(0.5)

    def test_partial_quantity_matching(self):
        fills = [
            _make_fill(100, 2.0, "buy", fee=0.0),
            _make_fill(110, 1.0, "sell", fee=0.0),   # closes 1 of 2 — win
            _make_fill(90, 1.0, "sell", fee=0.0),     # closes remaining 1 — loss
        ]
        rt = compute_round_trips(fills)
        assert rt.win_count == 1
        assert rt.loss_count == 1
        assert rt.rate == pytest.approx(0.5)

    def test_fee_can_turn_win_to_loss(self):
        fills = [
            _make_fill(100, 1.0, "buy", fee=0.0),
            _make_fill(100.05, 1.0, "sell", fee=0.10),  # tiny gain < fee
        ]
        assert win_rate(fills) == 0.0

    def test_both_entry_and_exit_fees_deducted(self):
        fills = [
            _make_fill(100, 1.0, "buy", fee=0.05),
            _make_fill(100.08, 1.0, "sell", fee=0.05),  # gross +0.08, total fees 0.10
        ]
        rt = compute_round_trips(fills)
        assert rt.loss_count == 1
        assert rt.win_count == 0
        assert float(rt.gross_loss) == pytest.approx(0.02, abs=0.001)

    def test_open_position_not_counted(self):
        fills = [
            _make_fill(100, 1.0, "buy", fee=0.0),
            _make_fill(110, 0.5, "sell", fee=0.0),    # partial close — 1 round trip
        ]
        rt = compute_round_trips(fills)
        assert rt.total_count == 1
        assert rt.win_count == 1


class TestProfitFactor:
    def test_profit_only(self):
        assert profit_factor(Decimal("100"), Decimal("0")) == float("inf")

    def test_loss_only(self):
        assert profit_factor(Decimal("0"), Decimal("100")) == 0.0

    def test_balanced(self):
        assert profit_factor(Decimal("200"), Decimal("100")) == pytest.approx(2.0)
