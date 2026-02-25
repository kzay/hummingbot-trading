"""Fill models for Paper Engine v2.

Implements the FillModel protocol with three built-in implementations:
- QueuePositionFillModel: default, seeded RNG, partial fills, prob_fill_on_limit
- TopOfBookFillModel: instant optimistic fill (smoke tests only)
- LatencyAwareFillModel: depth-capped realistic fill with drift tracking

Design follows NautilusTrader FillModelConfig conventions:
- prob_fill_on_limit: probability of fill when market touches limit price
- prob_slippage: probability of one extra tick of slippage per fill
- random_seed: deterministic reproducibility
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Protocol

from controllers.paper_engine_v2.types import (
    BookLevel,
    OrderBookSnapshot,
    OrderSide,
    PaperOrder,
    PaperOrderType,
    _ZERO,
    _ONE,
)

_10K = Decimal("10000")


# ---------------------------------------------------------------------------
# Protocol + FillDecision
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FillDecision:
    fill_quantity: Decimal
    fill_price: Decimal
    is_maker: bool
    queue_delay_ms: int


_NO_FILL = FillDecision(fill_quantity=_ZERO, fill_price=_ZERO, is_maker=False, queue_delay_ms=0)


class FillModel(Protocol):
    def evaluate(
        self,
        order: PaperOrder,
        book: OrderBookSnapshot,
        now_ns: int,
    ) -> FillDecision: ...


# ---------------------------------------------------------------------------
# QueuePositionFillModel (default)
# ---------------------------------------------------------------------------

@dataclass
class QueuePositionConfig:
    """Configuration mirrors NautilusTrader FillModelConfig fields."""
    queue_participation: Decimal = Decimal("0.35")
    min_partial_fill_ratio: Decimal = Decimal("0.15")
    max_partial_fill_ratio: Decimal = Decimal("0.85")
    slippage_bps: Decimal = Decimal("1.0")
    adverse_selection_bps: Decimal = Decimal("1.5")
    prob_fill_on_limit: float = 1.0   # probability of fill when market touches limit
    prob_slippage: float = 0.0        # probability of 1-tick extra slippage
    queue_jitter_pct: float = 0.20    # +/- randomization on queue_participation
    seed: int = 7


class QueuePositionFillModel:
    """Realistic queue-position fill model.

    Simulates partial fills based on book depth and queue position.
    Seeded RNG ensures deterministic results for regression testing.
    """

    def __init__(self, config: Optional[QueuePositionConfig] = None):
        self._cfg = config or QueuePositionConfig()
        self._rng = random.Random(self._cfg.seed)

    def evaluate(self, order: PaperOrder, book: OrderBookSnapshot, now_ns: int) -> FillDecision:
        remaining = order.remaining_quantity
        if remaining <= _ZERO:
            return _NO_FILL

        iid = order.instrument_id
        is_buy = order.side == OrderSide.BUY

        best_bid = book.best_bid
        best_ask = book.best_ask

        if best_ask is None and best_bid is None:
            return _NO_FILL

        # Determine if market has reached the order price
        is_touchable = False
        top_level: Optional[BookLevel] = None

        if is_buy:
            top_level = best_ask
            if top_level and order.price >= top_level.price:
                is_touchable = True
        else:
            top_level = best_bid
            if top_level and order.price <= top_level.price:
                is_touchable = True

        if top_level is None:
            return _NO_FILL

        cfg = self._cfg
        latency_ms = int(float(cfg.queue_participation) * 1000 * 1.5)  # approx queue delay

        # Taker / crossing fill
        if order.crossed_at_creation or order.order_type == PaperOrderType.MARKET:
            return self._taker_fill(order, top_level, remaining, now_ns)

        # Resting limit not yet touched
        if not is_touchable:
            if order.order_type == PaperOrderType.LIMIT_MAKER:
                return self._passive_maker_fill(order, top_level, remaining, latency_ms)
            # Regular limit: no fill yet
            return _NO_FILL

        # Market touched the order price
        if self._rng.random() > cfg.prob_fill_on_limit:
            return _NO_FILL  # queue position miss

        return self._passive_maker_fill(order, top_level, remaining, latency_ms)

    def _passive_maker_fill(
        self, order: PaperOrder, top: BookLevel, remaining: Decimal, delay_ms: int
    ) -> FillDecision:
        cfg = self._cfg
        jitter = 1.0 + self._rng.uniform(-cfg.queue_jitter_pct, cfg.queue_jitter_pct)
        qf = Decimal(str(float(cfg.queue_participation) * jitter))
        pr = Decimal(str(self._rng.uniform(
            float(cfg.min_partial_fill_ratio),
            float(cfg.max_partial_fill_ratio),
        )))
        depth_fill = top.size * qf if top.size > _ZERO else remaining * pr
        qty = min(remaining, depth_fill, remaining * pr)
        qty = max(qty, _ZERO)
        if qty <= _ZERO:
            return _NO_FILL
        return FillDecision(
            fill_quantity=qty,
            fill_price=order.price,
            is_maker=True,
            queue_delay_ms=delay_ms,
        )

    def _taker_fill(
        self, order: PaperOrder, top: BookLevel, remaining: Decimal, now_ns: int
    ) -> FillDecision:
        cfg = self._cfg
        jitter = 1.0 + self._rng.uniform(-cfg.queue_jitter_pct, cfg.queue_jitter_pct)
        qf = Decimal(str(float(cfg.queue_participation) * jitter))
        qty = min(remaining, top.size * qf if top.size > _ZERO else remaining)
        qty = max(qty, _ZERO)
        if qty <= _ZERO:
            return _NO_FILL

        slippage = (cfg.slippage_bps + cfg.adverse_selection_bps) / _10K
        extra = order.instrument_id  # just to get tick size reference
        extra_slippage = Decimal("0")
        if self._rng.random() < cfg.prob_slippage:
            extra_slippage = Decimal("0.0001")  # 1 tick default

        if order.side == OrderSide.BUY:
            price = top.price * (_ONE + slippage + extra_slippage)
        else:
            price = top.price * (_ONE - slippage - extra_slippage)

        return FillDecision(
            fill_quantity=qty,
            fill_price=price,
            is_maker=False,
            queue_delay_ms=int(float(cfg.queue_participation) * 1500),
        )


# ---------------------------------------------------------------------------
# TopOfBookFillModel (smoke tests only)
# ---------------------------------------------------------------------------

class TopOfBookFillModel:
    """Instantly fills full remaining at best bid/ask.

    OPTIMISTIC: use only for structural validation (connectivity, order flow).
    Not suitable for PnL benchmarking.
    """

    def evaluate(self, order: PaperOrder, book: OrderBookSnapshot, now_ns: int) -> FillDecision:
        remaining = order.remaining_quantity
        if remaining <= _ZERO:
            return _NO_FILL

        is_buy = order.side == OrderSide.BUY
        top = book.best_ask if is_buy else book.best_bid
        if top is None:
            return _NO_FILL

        return FillDecision(
            fill_quantity=remaining,
            fill_price=top.price,
            is_maker=False,
            queue_delay_ms=0,
        )


# ---------------------------------------------------------------------------
# LatencyAwareFillModel (most realistic)
# ---------------------------------------------------------------------------

@dataclass
class LatencyAwareConfig(QueuePositionConfig):
    depth_participation_pct: Decimal = Decimal("0.10")
    post_fill_drift_window_ms: int = 500


class LatencyAwareFillModel(QueuePositionFillModel):
    """Queue-position model with additional depth cap.

    Extends QueuePositionFillModel with:
    - Fill quantity capped at depth_participation_pct of visible depth at the level
    - Post-fill drift is a metric stored externally (not applied to fill price)
    """

    def __init__(self, config: Optional[LatencyAwareConfig] = None):
        cfg = config or LatencyAwareConfig()
        super().__init__(config=cfg)
        self._la_cfg: LatencyAwareConfig = cfg

    def evaluate(self, order: PaperOrder, book: OrderBookSnapshot, now_ns: int) -> FillDecision:
        decision = super().evaluate(order, book, now_ns)
        if decision.fill_quantity <= _ZERO:
            return decision

        is_buy = order.side == OrderSide.BUY
        top = book.best_ask if is_buy else book.best_bid
        if top and top.size > _ZERO:
            depth_cap = top.size * self._la_cfg.depth_participation_pct
            capped_qty = min(decision.fill_quantity, depth_cap)
            if capped_qty <= _ZERO:
                return _NO_FILL
            return FillDecision(
                fill_quantity=capped_qty,
                fill_price=decision.fill_price,
                is_maker=decision.is_maker,
                queue_delay_ms=decision.queue_delay_ms,
            )
        return decision


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_fill_model(name: str, seed: int = 7) -> FillModel:
    """Create a fill model by name string."""
    if name == "top_of_book":
        return TopOfBookFillModel()
    if name == "latency_aware":
        return LatencyAwareFillModel(LatencyAwareConfig(seed=seed))
    # default
    return QueuePositionFillModel(QueuePositionConfig(seed=seed))
