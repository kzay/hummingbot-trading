"""Incremental Liquidity Pool detector.

Clusters nearby swing highs/lows into liquidity pools.  A pool is swept
when price trades beyond the pool level.

  - Buy-side liquidity: cluster of swing highs (stop losses above).
  - Sell-side liquidity: cluster of swing lows (stop losses below).
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from controllers.common.ict._types import LiquidityPool, SwingEvent


class LiquidityDetector:
    """O(k) per-bar liquidity detector where k = active pool count."""

    __slots__ = (
        "_active",
        "_all_events",
        "_bar_idx",
        "_min_touches",
        "_range_pct",
        "_swing_highs",
        "_swing_lows",
    )

    def __init__(
        self,
        range_pct: Decimal = Decimal("0.01"),
        min_touches: int = 2,
    ) -> None:
        self._range_pct = range_pct
        self._min_touches = min_touches
        self._bar_idx: int = 0
        self._swing_highs: list[SwingEvent] = []
        self._swing_lows: list[SwingEvent] = []
        self._active: list[LiquidityPool] = []
        self._all_events: list[LiquidityPool] = []

    def on_swing(self, swing: SwingEvent) -> LiquidityPool | None:
        """Process a new confirmed swing.  Returns a LiquidityPool if
        enough nearby swings cluster together."""
        if swing.direction == +1:
            self._swing_highs.append(swing)
            return self._try_cluster(self._swing_highs, +1)
        else:
            self._swing_lows.append(swing)
            return self._try_cluster(self._swing_lows, -1)

    def _try_cluster(
        self, swings: list[SwingEvent], direction: int
    ) -> LiquidityPool | None:
        if len(swings) < self._min_touches:
            return None
        latest = swings[-1]
        threshold = latest.level * self._range_pct
        cluster = [s for s in swings if abs(s.level - latest.level) <= threshold]

        if len(cluster) < self._min_touches:
            return None

        avg_level = sum(s.level for s in cluster) / Decimal(len(cluster))
        pool = LiquidityPool(
            start_index=cluster[0].index,
            end_index=cluster[-1].index,
            direction=direction,
            level=avg_level,
            count=len(cluster),
        )

        for existing in self._active:
            if (
                existing.direction == direction
                and abs(existing.level - avg_level) <= threshold
            ):
                idx_all = self._all_events.index(existing)
                self._all_events[idx_all] = pool
                idx_active = self._active.index(existing)
                self._active[idx_active] = pool
                return pool

        self._active.append(pool)
        self._all_events.append(pool)
        return pool

    def add_bar(
        self,
        open_: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: Decimal = Decimal(0),
    ) -> None:
        """Check for pool sweeps on each bar."""
        self._bar_idx += 1
        surviving: list[LiquidityPool] = []
        for pool in self._active:
            if pool.direction == +1 and high > pool.level:
                swept = replace(pool, swept=True, sweep_index=self._bar_idx - 1)
                self._replace_in_history(pool, swept)
                continue
            if pool.direction == -1 and low < pool.level:
                swept = replace(pool, swept=True, sweep_index=self._bar_idx - 1)
                self._replace_in_history(pool, swept)
                continue
            surviving.append(pool)
        self._active = surviving

    def _replace_in_history(self, old: LiquidityPool, new: LiquidityPool) -> None:
        for i in range(len(self._all_events) - 1, -1, -1):
            if self._all_events[i] is old:
                self._all_events[i] = new
                return

    @property
    def active(self) -> list[LiquidityPool]:
        return list(self._active)

    @property
    def all_events(self) -> list[LiquidityPool]:
        return list(self._all_events)

    @property
    def bar_count(self) -> int:
        return self._bar_idx

    def reset(self) -> None:
        self._bar_idx = 0
        self._swing_highs.clear()
        self._swing_lows.clear()
        self._active.clear()
        self._all_events.clear()
