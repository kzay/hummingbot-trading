"""Tests for v3 execution adapters — MM grid, directional, hybrid."""

from __future__ import annotations

from decimal import Decimal

import pytest

from controllers.runtime.v3.execution.directional import DirectionalExecutionAdapter
from controllers.runtime.v3.execution.hybrid import HybridExecutionAdapter
from controllers.runtime.v3.execution.mm_grid import MMGridExecutionAdapter
from controllers.runtime.v3.signals import SignalLevel, TradingSignal
from controllers.runtime.v3.types import (
    IndicatorSnapshot,
    MarketSnapshot,
    OrderBookSnapshot,
    PositionSnapshot,
)

_ZERO = Decimal("0")


def _make_snapshot(
    mid: Decimal = Decimal("65000"),
    spread_pct: Decimal = Decimal("0.0002"),
    net_base_pct: Decimal = _ZERO,
    atr_14: Decimal = Decimal("350"),
) -> MarketSnapshot:
    return MarketSnapshot(
        mid=mid,
        order_book=OrderBookSnapshot(
            best_bid=mid * (1 - spread_pct / 2),
            best_ask=mid * (1 + spread_pct / 2),
            spread_pct=spread_pct,
        ),
        position=PositionSnapshot(net_base_pct=net_base_pct),
        indicators=IndicatorSnapshot(atr={14: atr_14}),
    )


def _make_mm_signal(levels: int = 2, spread: str = "0.001", size: str = "100") -> TradingSignal:
    lvls = []
    for i in range(levels):
        lvls.append(SignalLevel(side="buy", spread_pct=Decimal(spread), size_quote=Decimal(size), level_id=f"b{i}"))
        lvls.append(SignalLevel(side="sell", spread_pct=Decimal(spread), size_quote=Decimal(size), level_id=f"s{i}"))
    return TradingSignal(
        family="mm_grid",
        direction="both",
        conviction=Decimal("0.5"),
        levels=tuple(lvls),
    )


def _make_dir_signal(direction: str = "buy", levels: int = 2, spread: str = "0.0015", size: str = "100") -> TradingSignal:
    lvls = [
        SignalLevel(side=direction, spread_pct=Decimal(spread), size_quote=Decimal(size), level_id=f"d{i}")
        for i in range(levels)
    ]
    return TradingSignal(
        family="directional",
        direction=direction,
        conviction=Decimal("0.85"),
        target_net_base_pct=Decimal("0.05"),
        levels=tuple(lvls),
    )


# ── MM Grid tests ────────────────────────────────────────────────────


class TestMMGridAdapter:
    def test_produces_orders_both_sides(self):
        adapter = MMGridExecutionAdapter()
        snap = _make_snapshot()
        sig = _make_mm_signal(levels=2)
        orders = adapter.translate(sig, snap)

        assert len(orders) == 4
        buy_orders = [o for o in orders if o.side == "buy"]
        sell_orders = [o for o in orders if o.side == "sell"]
        assert len(buy_orders) == 2
        assert len(sell_orders) == 2

    def test_buy_price_below_mid(self):
        adapter = MMGridExecutionAdapter()
        snap = _make_snapshot()
        sig = _make_mm_signal(levels=1)
        orders = adapter.translate(sig, snap)

        buy = [o for o in orders if o.side == "buy"][0]
        assert buy.price < snap.mid

    def test_sell_price_above_mid(self):
        adapter = MMGridExecutionAdapter()
        snap = _make_snapshot()
        sig = _make_mm_signal(levels=1)
        orders = adapter.translate(sig, snap)

        sell = [o for o in orders if o.side == "sell"][0]
        assert sell.price > snap.mid

    def test_spread_cap_applied(self):
        adapter = MMGridExecutionAdapter(spread_cap_mult=Decimal("5"))
        snap = _make_snapshot(spread_pct=Decimal("0.001"))
        # Signal spread 0.001 < cap 0.005 → spread widened to 0.005
        sig = _make_mm_signal(levels=1, spread="0.001")
        orders = adapter.translate(sig, snap)

        buy = [o for o in orders if o.side == "buy"][0]
        effective_spread = (snap.mid - buy.price) / snap.mid
        assert effective_spread >= Decimal("0.004")  # At least cap applied

    def test_inventory_skew_widens_buy(self):
        adapter = MMGridExecutionAdapter(skew_intensity=Decimal("1"))
        # Position is long (net_base_pct > target 0) → buy side widened
        snap = _make_snapshot(net_base_pct=Decimal("0.10"))
        sig = _make_mm_signal(levels=1, spread="0.002")
        orders = adapter.translate(sig, snap)

        buy = [o for o in orders if o.side == "buy"][0]
        buy_spread = (snap.mid - buy.price) / snap.mid
        assert buy_spread > Decimal("0.002")  # Widened due to long position

    def test_no_trade_returns_empty(self):
        adapter = MMGridExecutionAdapter()
        snap = _make_snapshot()
        sig = TradingSignal.no_trade()
        assert adapter.translate(sig, snap) == []

    def test_zero_mid_returns_empty(self):
        adapter = MMGridExecutionAdapter()
        snap = _make_snapshot(mid=_ZERO)
        sig = _make_mm_signal()
        assert adapter.translate(sig, snap) == []

    def test_no_trailing(self):
        adapter = MMGridExecutionAdapter()
        pos = PositionSnapshot(base_amount=Decimal("0.01"))
        sig = _make_mm_signal()
        assert adapter.manage_trailing(pos, sig) == []


# ── Directional tests ────────────────────────────────────────────────


class TestDirectionalAdapter:
    def test_single_side_only(self):
        adapter = DirectionalExecutionAdapter()
        snap = _make_snapshot()
        sig = _make_dir_signal(direction="buy")
        orders = adapter.translate(sig, snap)

        assert all(o.side == "buy" for o in orders)

    def test_atr_scaled_barriers(self):
        adapter = DirectionalExecutionAdapter(
            sl_atr_mult=Decimal("1.5"),
            tp_atr_mult=Decimal("3.0"),
        )
        snap = _make_snapshot(atr_14=Decimal("400"))
        sig = _make_dir_signal()
        orders = adapter.translate(sig, snap)

        assert orders[0].stop_loss == Decimal("600")   # 400 * 1.5
        assert orders[0].take_profit == Decimal("1200")  # 400 * 3.0

    def test_no_barriers_without_atr(self):
        adapter = DirectionalExecutionAdapter()
        snap = _make_snapshot(atr_14=_ZERO)
        sig = _make_dir_signal()
        orders = adapter.translate(sig, snap)

        assert orders[0].stop_loss is None
        assert orders[0].take_profit is None

    def test_time_limit_set(self):
        adapter = DirectionalExecutionAdapter(time_limit_s=7200)
        snap = _make_snapshot()
        sig = _make_dir_signal()
        orders = adapter.translate(sig, snap)
        assert orders[0].time_limit_s == 7200

    def test_off_direction_returns_empty(self):
        adapter = DirectionalExecutionAdapter()
        snap = _make_snapshot()
        sig = TradingSignal(family="directional", direction="off")
        assert adapter.translate(sig, snap) == []

    def test_trailing_reset_on_flat(self):
        adapter = DirectionalExecutionAdapter()
        pos = PositionSnapshot(base_amount=_ZERO)
        sig = _make_dir_signal()
        actions = adapter.manage_trailing(pos, sig)
        assert actions == []


# ── Hybrid tests ─────────────────────────────────────────────────────


class TestHybridAdapter:
    def test_high_conviction_uses_directional(self):
        adapter = HybridExecutionAdapter(
            directional_threshold=Decimal("0.80"),
            bias_threshold=Decimal("0.60"),
        )
        snap = _make_snapshot()
        sig = _make_dir_signal(direction="buy")  # conviction=0.85 > 0.80
        orders = adapter.translate(sig, snap)

        # Should be directional: only buy side, with barriers
        assert all(o.side == "buy" for o in orders)
        assert orders[0].stop_loss is not None

    def test_medium_conviction_uses_skewed_mm(self):
        adapter = HybridExecutionAdapter(
            directional_threshold=Decimal("0.90"),
            bias_threshold=Decimal("0.60"),
        )
        snap = _make_snapshot()
        # Conviction 0.75 is between bias (0.60) and directional (0.90)
        sig = TradingSignal(
            family="hybrid",
            direction="buy",
            conviction=Decimal("0.75"),
            levels=_make_mm_signal(levels=1).levels,
        )
        orders = adapter.translate(sig, snap)
        assert len(orders) > 0

    def test_low_conviction_uses_symmetric(self):
        adapter = HybridExecutionAdapter(
            directional_threshold=Decimal("0.90"),
            bias_threshold=Decimal("0.70"),
        )
        snap = _make_snapshot()
        sig = TradingSignal(
            family="hybrid",
            direction="buy",
            conviction=Decimal("0.50"),  # Below bias threshold
            levels=_make_mm_signal(levels=1).levels,
        )
        orders = adapter.translate(sig, snap)
        # Symmetric: both buy and sell orders
        sides = {o.side for o in orders}
        assert "buy" in sides
        assert "sell" in sides

    def test_no_trade_returns_empty(self):
        adapter = HybridExecutionAdapter()
        snap = _make_snapshot()
        sig = TradingSignal.no_trade()
        assert adapter.translate(sig, snap) == []
