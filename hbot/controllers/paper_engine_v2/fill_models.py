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

import logging
import os
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
_TRUE_VALUES = {"1", "true", "yes", "on"}
logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


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
    prob_fill_on_limit: float = 0.4   # probability of fill when market touches limit (realistic for BTC-USDT perps)
    prob_slippage: float = 0.0        # probability of 1-tick extra slippage
    queue_jitter_pct: float = 0.20    # +/- randomization on queue_participation
    depth_levels: int = 3             # number of contra levels considered for depth-limited fills
    depth_decay: Decimal = Decimal("0.70")  # farther levels contribute less to instantaneous fillability
    queue_position_enabled: bool = False
    queue_ahead_ratio: Decimal = Decimal("0.50")  # initial fraction of visible touched depth ahead of us
    queue_trade_through_ratio: Decimal = Decimal("0.35")  # per-touch fraction of depth considered traded-through
    seed: int = 7


class QueuePositionFillModel:
    """Realistic queue-position fill model.

    Simulates partial fills based on book depth and queue position.
    Seeded RNG ensures deterministic results for regression testing.
    """

    def __init__(self, config: Optional[QueuePositionConfig] = None):
        self._cfg = config or QueuePositionConfig()
        self._rng = random.Random(self._cfg.seed)
        self._queue_ahead_by_order: dict[str, Decimal] = {}
        self._trace_enabled = _env_bool("HB_PAPER_FILL_TRACE_ENABLED", default=False)
        self._trace_sample_every = max(1, int(os.getenv("HB_PAPER_FILL_TRACE_SAMPLE_EVERY", "1")))
        self._trace_max_lines = max(1, int(os.getenv("HB_PAPER_FILL_TRACE_MAX_LINES", "200")))
        self._trace_seen = 0
        self._trace_emitted = 0
        if self._trace_enabled:
            logger.warning(
                "PAPER_FILL_TRACE init enabled=true sample_every=%s max_lines=%s seed=%s",
                self._trace_sample_every,
                self._trace_max_lines,
                self._cfg.seed,
            )

    def _trace(self, stage: str, order: PaperOrder, **fields: object) -> None:
        if not self._trace_enabled:
            return
        self._trace_seen += 1
        if self._trace_emitted >= self._trace_max_lines:
            return
        if (self._trace_seen % self._trace_sample_every) != 0:
            return
        base_fields = {
            "order_id": order.order_id,
            "side": str(order.side),
            "otype": str(order.order_type),
            "price": str(order.price),
            "remaining": str(order.remaining_quantity),
        }
        parts: list[str] = []
        for key, value in {**base_fields, **fields}.items():
            parts.append(f"{key}={value}")
        logger.warning("PAPER_FILL_TRACE stage=%s %s", stage, " ".join(parts))
        self._trace_emitted += 1

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

        # Determine if market has reached the order price.
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
            self._trace("no_fill_no_top", order, best_bid=str(best_bid), best_ask=str(best_ask))
            return _NO_FILL

        cfg = self._cfg
        latency_ms = int(float(cfg.queue_participation) * 1000 * 1.5)  # approx queue delay

        # Taker / crossing fill
        if order.crossed_at_creation or order.order_type == PaperOrderType.MARKET:
            contra_levels = self._contra_levels(order, book)
            return self._taker_fill(order, contra_levels, remaining, now_ns)

        # Passive order (LIMIT or LIMIT_MAKER) — only fills when the market
        # has reached the order price (touchable). A resting order behind
        # the spread does NOT fill — it must wait for the market to come to it.
        if not is_touchable:
            return _NO_FILL

        # Market touched the order price — apply queue position probability
        fill_draw = self._rng.random()
        if fill_draw > cfg.prob_fill_on_limit:
            self._trace(
                "no_fill_prob_miss",
                order,
                draw=f"{fill_draw:.6f}",
                prob=f"{cfg.prob_fill_on_limit:.6f}",
                top_price=str(top_level.price),
                top_size=str(top_level.size),
            )
            return _NO_FILL  # queue position miss

        contra_levels = self._reachable_levels(order, book)
        self._trace(
            "touch_eligible",
            order,
            draw=f"{fill_draw:.6f}",
            prob=f"{cfg.prob_fill_on_limit:.6f}",
            top_price=str(top_level.price),
            top_size=str(top_level.size),
            reachable_levels=len(contra_levels),
        )
        return self._passive_maker_fill(order, top_level, contra_levels, remaining, latency_ms)

    def _contra_levels(self, order: PaperOrder, book: OrderBookSnapshot) -> list[BookLevel]:
        levels = list(book.asks if order.side == OrderSide.BUY else book.bids)
        max_levels = max(1, int(self._cfg.depth_levels))
        return levels[:max_levels]

    def _reachable_levels(self, order: PaperOrder, book: OrderBookSnapshot) -> list[BookLevel]:
        levels = self._contra_levels(order, book)
        if order.side == OrderSide.BUY:
            filtered = [lv for lv in levels if lv.price <= order.price]
        else:
            filtered = [lv for lv in levels if lv.price >= order.price]
        return filtered

    def _effective_depth(self, levels: list[BookLevel]) -> Decimal:
        if not levels:
            return _ZERO
        decay = max(Decimal("0.1"), min(_ONE, self._cfg.depth_decay))
        total = _ZERO
        weight = _ONE
        for lv in levels:
            if lv.size > _ZERO:
                total += lv.size * weight
            weight *= decay
        return total

    def _passive_maker_fill(
        self, order: PaperOrder, top: BookLevel, contra_levels: list[BookLevel], remaining: Decimal, delay_ms: int
    ) -> FillDecision:
        cfg = self._cfg
        if cfg.queue_position_enabled:
            depth_now = top.size if top.size > _ZERO else self._effective_depth(contra_levels)
            queue_ahead = self._queue_ahead_by_order.get(order.order_id)
            if queue_ahead is None:
                queue_ahead = max(_ZERO, depth_now * max(_ZERO, cfg.queue_ahead_ratio))
            queue_ahead = max(_ZERO, queue_ahead - depth_now * max(_ZERO, cfg.queue_trade_through_ratio))
            self._queue_ahead_by_order[order.order_id] = queue_ahead
            if queue_ahead > _ZERO:
                self._trace(
                    "no_fill_queue_ahead",
                    order,
                    depth_now=str(depth_now),
                    queue_ahead=str(queue_ahead),
                    ahead_ratio=str(cfg.queue_ahead_ratio),
                    trade_through_ratio=str(cfg.queue_trade_through_ratio),
                )
                return _NO_FILL
        jitter = 1.0 + self._rng.uniform(-cfg.queue_jitter_pct, cfg.queue_jitter_pct)
        qf = Decimal(str(float(cfg.queue_participation) * jitter))
        pr = Decimal(str(self._rng.uniform(
            float(cfg.min_partial_fill_ratio),
            float(cfg.max_partial_fill_ratio),
        )))
        reachable_depth = self._effective_depth(contra_levels) if contra_levels else top.size
        depth_fill = reachable_depth * qf if reachable_depth > _ZERO else remaining * pr
        qty = min(remaining, depth_fill, remaining * pr)
        qty = max(qty, _ZERO)
        if qty <= _ZERO:
            self._trace(
                "no_fill_zero_qty",
                order,
                qf=str(qf),
                pr=str(pr),
                reachable_depth=str(reachable_depth),
                depth_fill=str(depth_fill),
            )
            return _NO_FILL
        self._trace(
            "maker_fill",
            order,
            qty=str(qty),
            qf=str(qf),
            pr=str(pr),
            reachable_depth=str(reachable_depth),
            delay_ms=delay_ms,
        )
        return FillDecision(
            fill_quantity=qty,
            fill_price=order.price,
            is_maker=True,
            queue_delay_ms=delay_ms,
        )

    def _taker_fill(
        self, order: PaperOrder, contra_levels: list[BookLevel], remaining: Decimal, now_ns: int
    ) -> FillDecision:
        cfg = self._cfg
        if not contra_levels:
            return _NO_FILL
        jitter = 1.0 + self._rng.uniform(-cfg.queue_jitter_pct, cfg.queue_jitter_pct)
        qf = Decimal(str(float(cfg.queue_participation) * jitter))
        effective_depth = self._effective_depth(contra_levels)
        qty = min(remaining, effective_depth * qf if effective_depth > _ZERO else remaining)
        qty = max(qty, _ZERO)
        if qty <= _ZERO:
            return _NO_FILL

        # Consume quantity across multiple levels and compute a simple VWAP.
        qty_left = qty
        notional = _ZERO
        for lv in contra_levels:
            if qty_left <= _ZERO:
                break
            if lv.size <= _ZERO:
                continue
            take = min(qty_left, lv.size)
            notional += take * lv.price
            qty_left -= take
        if qty_left > _ZERO:
            notional += qty_left * contra_levels[-1].price
        vwap = notional / qty if qty > _ZERO else contra_levels[0].price

        slippage = (cfg.slippage_bps + cfg.adverse_selection_bps) / _10K
        extra_slippage = Decimal("0")
        if self._rng.random() < cfg.prob_slippage:
            extra_slippage = Decimal("0.0001")  # 1 tick default

        if order.side == OrderSide.BUY:
            price = vwap * (_ONE + slippage + extra_slippage)
        else:
            price = vwap * (_ONE - slippage - extra_slippage)

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
# Nautilus-style preset fill models
# ---------------------------------------------------------------------------

class BestPriceFillModel(TopOfBookFillModel):
    """Nautilus-style optimistic best-price fill model."""


class OneTickSlippageFillModel:
    """Nautilus-style deterministic 1-tick slippage on taker fills."""

    def evaluate(self, order: PaperOrder, book: OrderBookSnapshot, now_ns: int) -> FillDecision:
        remaining = order.remaining_quantity
        if remaining <= _ZERO:
            return _NO_FILL
        is_buy = order.side == OrderSide.BUY
        top = book.best_ask if is_buy else book.best_bid
        if top is None:
            return _NO_FILL
        tick = order.instrument_id and Decimal("0.0001")
        price = top.price + tick if is_buy else top.price - tick
        return FillDecision(
            fill_quantity=remaining,
            fill_price=max(_ZERO, price),
            is_maker=False,
            queue_delay_ms=0,
        )


class TwoTierFillModel:
    """Nautilus-style two-tier depth model.

    First tier fills up to `tier1_size` at best price, remainder at one tick worse.
    """

    def __init__(self, tier1_size: Decimal = Decimal("10")):
        self._tier1_size = max(_ZERO, tier1_size)

    def evaluate(self, order: PaperOrder, book: OrderBookSnapshot, now_ns: int) -> FillDecision:
        remaining = order.remaining_quantity
        if remaining <= _ZERO:
            return _NO_FILL
        is_buy = order.side == OrderSide.BUY
        top = book.best_ask if is_buy else book.best_bid
        if top is None:
            return _NO_FILL
        tick = Decimal("0.0001")
        q1 = min(remaining, self._tier1_size)
        q2 = max(_ZERO, remaining - q1)
        p1 = top.price
        p2 = top.price + tick if is_buy else top.price - tick
        notional = q1 * p1 + q2 * p2
        vwap = notional / remaining if remaining > _ZERO else p1
        return FillDecision(
            fill_quantity=remaining,
            fill_price=max(_ZERO, vwap),
            is_maker=False,
            queue_delay_ms=0,
        )


class ThreeTierFillModel:
    """Nautilus-style three-tier depth model."""

    def __init__(
        self,
        tier1_size: Decimal = Decimal("50"),
        tier2_size: Decimal = Decimal("30"),
        tier3_size: Decimal = Decimal("20"),
    ):
        self._tier1 = max(_ZERO, tier1_size)
        self._tier2 = max(_ZERO, tier2_size)
        self._tier3 = max(_ZERO, tier3_size)

    def evaluate(self, order: PaperOrder, book: OrderBookSnapshot, now_ns: int) -> FillDecision:
        remaining = order.remaining_quantity
        if remaining <= _ZERO:
            return _NO_FILL
        is_buy = order.side == OrderSide.BUY
        top = book.best_ask if is_buy else book.best_bid
        if top is None:
            return _NO_FILL
        tick = Decimal("0.0001")
        p1 = top.price
        p2 = top.price + tick if is_buy else top.price - tick
        p3 = top.price + tick + tick if is_buy else top.price - tick - tick
        q1 = min(remaining, self._tier1)
        q2 = min(max(_ZERO, remaining - q1), self._tier2)
        q3 = max(_ZERO, remaining - q1 - q2)
        notional = q1 * p1 + q2 * p2 + q3 * p3
        vwap = notional / remaining if remaining > _ZERO else p1
        return FillDecision(remaining, max(_ZERO, vwap), False, 0)


class CompetitionAwareFillModel:
    """Nautilus-style competition-aware best level availability."""

    def __init__(self, liquidity_factor: Decimal = Decimal("0.30")):
        self._liq = max(Decimal("0.01"), min(_ONE, liquidity_factor))

    def evaluate(self, order: PaperOrder, book: OrderBookSnapshot, now_ns: int) -> FillDecision:
        remaining = order.remaining_quantity
        if remaining <= _ZERO:
            return _NO_FILL
        top = book.best_ask if order.side == OrderSide.BUY else book.best_bid
        if top is None:
            return _NO_FILL
        qty = min(remaining, top.size * self._liq if top.size > _ZERO else remaining * self._liq)
        if qty <= _ZERO:
            return _NO_FILL
        return FillDecision(qty, top.price, False, 0)


class SizeAwareFillModel:
    """Size-aware fill quality: larger clips pay worse price."""

    def __init__(self, soft_clip_qty: Decimal = Decimal("1.0"), impact_bps_per_clip: Decimal = Decimal("0.8")):
        self._soft = max(Decimal("0.0001"), soft_clip_qty)
        self._impact = max(_ZERO, impact_bps_per_clip)

    def evaluate(self, order: PaperOrder, book: OrderBookSnapshot, now_ns: int) -> FillDecision:
        remaining = order.remaining_quantity
        if remaining <= _ZERO:
            return _NO_FILL
        top = book.best_ask if order.side == OrderSide.BUY else book.best_bid
        if top is None:
            return _NO_FILL
        clips = remaining / self._soft
        impact_bps = self._impact * clips
        direction = _ONE if order.side == OrderSide.BUY else Decimal("-1")
        price = top.price * (_ONE + direction * impact_bps / Decimal("10000"))
        return FillDecision(remaining, max(_ZERO, price), False, 0)


class MarketHoursAwareFillModel:
    """Session-aware liquidity profile (mainly for mixed-asset backtests)."""

    def __init__(self, off_hours_liquidity_factor: Decimal = Decimal("0.5")):
        self._off = max(Decimal("0.05"), min(_ONE, off_hours_liquidity_factor))

    def evaluate(self, order: PaperOrder, book: OrderBookSnapshot, now_ns: int) -> FillDecision:
        remaining = order.remaining_quantity
        if remaining <= _ZERO:
            return _NO_FILL
        top = book.best_ask if order.side == OrderSide.BUY else book.best_bid
        if top is None:
            return _NO_FILL
        hour = int((now_ns // 1_000_000_000) % 86_400 // 3600)
        # UTC overlap hours 12-20 have better liquidity; off-hours are thinner.
        liq_factor = _ONE if 12 <= hour <= 20 else self._off
        qty = min(remaining, max(_ZERO, top.size * liq_factor))
        if qty <= _ZERO:
            return _NO_FILL
        return FillDecision(qty, top.price, False, 0)


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

def make_fill_model(
    name: str,
    seed: int = 7,
    queue_participation: Decimal = Decimal("0.35"),
    slippage_bps: Decimal = Decimal("1.0"),
    adverse_selection_bps: Decimal = Decimal("1.5"),
    partial_fill_min_ratio: Decimal = Decimal("0.15"),
    partial_fill_max_ratio: Decimal = Decimal("0.85"),
    depth_levels: int = 3,
    depth_decay: Decimal = Decimal("0.70"),
    queue_position_enabled: bool = False,
    queue_ahead_ratio: Decimal = Decimal("0.50"),
    queue_trade_through_ratio: Decimal = Decimal("0.35"),
    prob_fill_on_limit: float = 0.4,
    prob_slippage: float = 0.0,
) -> FillModel:
    """Create a fill model by name string."""
    cfg = QueuePositionConfig(
        seed=seed,
        queue_participation=max(_ZERO, queue_participation),
        slippage_bps=max(_ZERO, slippage_bps),
        adverse_selection_bps=max(_ZERO, adverse_selection_bps),
        min_partial_fill_ratio=max(_ZERO, partial_fill_min_ratio),
        max_partial_fill_ratio=max(_ZERO, partial_fill_max_ratio),
        depth_levels=max(1, int(depth_levels)),
        depth_decay=max(Decimal("0.10"), min(_ONE, depth_decay)),
        queue_position_enabled=bool(queue_position_enabled),
        queue_ahead_ratio=max(_ZERO, queue_ahead_ratio),
        queue_trade_through_ratio=max(_ZERO, queue_trade_through_ratio),
        prob_fill_on_limit=max(0.0, min(1.0, float(prob_fill_on_limit))),
        prob_slippage=max(0.0, min(1.0, float(prob_slippage))),
    )
    if name == "best_price":
        return BestPriceFillModel()
    if name == "one_tick_slippage":
        return OneTickSlippageFillModel()
    if name == "two_tier":
        return TwoTierFillModel()
    if name == "three_tier":
        return ThreeTierFillModel()
    if name == "competition_aware":
        return CompetitionAwareFillModel()
    if name == "size_aware":
        return SizeAwareFillModel()
    if name == "market_hours_aware":
        return MarketHoursAwareFillModel()
    if name == "top_of_book":
        return TopOfBookFillModel()
    if name == "latency_aware":
        return LatencyAwareFillModel(LatencyAwareConfig(**cfg.__dict__))
    # default
    return QueuePositionFillModel(cfg)
