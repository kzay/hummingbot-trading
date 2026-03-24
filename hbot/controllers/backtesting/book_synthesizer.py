"""Book synthesizers for the backtesting engine.

Converts OHLCV candle data or raw trade ticks into `OrderBookSnapshot`
instances that the PaperDesk matching engine can consume.

Two concrete implementations are provided alongside the structural protocol:

- `CandleBookSynthesizer`:
  Reconstructs a plausible order book from a single OHLCV candle bar.
  The intra-bar price walk follows OHLC waypoints; spread widens in
  volatile bars; depth decays geometrically away from the best level.

- `TradeBookSynthesizer`:
  Derives best-bid / best-ask from a batch of real trade ticks for the
  current time step.  Cumulative volume per side forms the single depth
  level returned per side.

Look-ahead bias invariant
-------------------------
``step_index=0`` MUST use the candle's *open* price as the mid reference,
never ``close``.  The close is only used at ``step_index == steps_per_bar - 1``
(the final intra-bar sub-step).  This matches the ``HistoricalDataFeed``
contract: the strategy never observes a future price at the start of a bar.
"""
from __future__ import annotations

import random
from decimal import Decimal
from typing import Protocol, runtime_checkable

from controllers.backtesting.types import CandleRow, SynthesisConfig, TradeRow
from simulation.types import (
    _ONE,
    _TWO,
    _ZERO,
    BookLevel,
    InstrumentId,
    OrderBookSnapshot,
)

# ---------------------------------------------------------------------------
# Module-level Decimal constants
# ---------------------------------------------------------------------------

_TEN_THOUSAND = Decimal("10000")


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class BookSynthesizer(Protocol):
    """Convert a single OHLCV candle bar into an ``OrderBookSnapshot``.

    The protocol is ``runtime_checkable`` so callers can use
    ``isinstance(obj, BookSynthesizer)`` for defensive validation without
    requiring inheritance.

    Parameters
    ----------
    candle:
        The OHLCV bar covering the current time window.
    instrument_id:
        Identifies the instrument for the returned snapshot.
    step_index:
        Zero-based intra-bar step index.  Implementations use this to
        walk the price through the bar's OHLC path.  ``step_index=0``
        **must** produce the candle's ``open`` price as mid to prevent
        look-ahead bias.
    rng:
        Seeded ``random.Random`` instance supplied by the feed.  All
        randomness **must** flow through this object so that synthesis
        is deterministic given the same seed.

    Returns
    -------
    OrderBookSnapshot
        A fully-populated snapshot whose ``timestamp_ns`` matches the
        feed's current time cursor.
    """

    def synthesize(
        self,
        candle: CandleRow,
        instrument_id: InstrumentId,
        step_index: int,
        rng: random.Random,
    ) -> OrderBookSnapshot:
        ...

    @property
    def steps_per_bar(self) -> int:
        """Number of intra-bar steps this synthesizer was configured for."""
        ...


# ---------------------------------------------------------------------------
# OHLC price walk helpers
# ---------------------------------------------------------------------------


def _ohlc_waypoints(
    candle: CandleRow,
    steps_per_bar: int,
    rng: random.Random,
) -> list[float]:
    """Return a list of exactly ``steps_per_bar`` mid prices for a bar.

    Uses native float arithmetic for speed; the output precision is
    sufficient for synthetic book construction.

    Invariants
    ----------
    - ``result[0] == float(candle.open)`` always — look-ahead bias guard.
    - ``result[-1] == float(candle.close)`` when ``steps_per_bar > 1``.
    - For ``steps_per_bar == 1`` only the open price is returned.
    """
    if steps_per_bar <= 0:
        raise ValueError(f"steps_per_bar must be >= 1, got {steps_per_bar}")

    o = float(candle.open)

    if steps_per_bar == 1:
        return [o]

    h = float(candle.high)
    lo = float(candle.low)
    c = float(candle.close)

    high_first: bool = rng.random() < 0.5
    if high_first:
        waypoints = [o, h, lo, c]
    else:
        waypoints = [o, lo, h, c]

    if steps_per_bar == 4:
        return waypoints

    n_intervals = steps_per_bar - 1
    inv = 1.0 / n_intervals
    prices: list[float] = []

    for i in range(steps_per_bar):
        t = i * inv
        seg_pos = t * 3.0
        seg_idx = min(int(seg_pos), 2)
        seg_frac = seg_pos - seg_idx

        p0 = waypoints[seg_idx]
        p1 = waypoints[seg_idx + 1]
        prices.append(p0 + seg_frac * (p1 - p0))

    return prices


# ---------------------------------------------------------------------------
# CandleBookSynthesizer
# ---------------------------------------------------------------------------


class CandleBookSynthesizer:
    """Synthesizes an ``OrderBookSnapshot`` from a single OHLCV candle bar.

    Spread model
    ~~~~~~~~~~~~
    The effective spread widens with intra-bar realised volatility, proxied
    by the candle's high-low range::

        spread_dec = (base_spread_bps / 10_000) * (1 + vol_spread_mult * range / mid)

    Depth model
    ~~~~~~~~~~~
    ``depth_levels`` bid levels and ``depth_levels`` ask levels are
    generated.  Level *i* (0-based; 0 = best) carries size::

        size_i = base_depth_size * depth_decay^i

    Price distance between successive levels (away from best) equals::

        level_step = mid * spread_dec / depth_levels

    Parameters
    ----------
    config:
        ``SynthesisConfig`` controlling all tunable parameters.
    """

    def __init__(self, config: SynthesisConfig) -> None:
        self._cfg = config
        # Float versions for fast hot-path arithmetic; Decimal conversion
        # happens only at the BookLevel boundary.
        self._base_spread_frac: float = float(config.base_spread_bps) / 10_000.0
        self._vol_spread_mult_f: float = float(config.vol_spread_mult)
        self._depth_decay_f: float = float(config.depth_decay)
        # Pre-compute depth sizes — they only depend on config, not on candle data.
        n = config.depth_levels
        decay = 1.0
        base_size = float(config.base_depth_size)
        self._depth_sizes: list[Decimal] = []
        for _ in range(n):
            self._depth_sizes.append(Decimal(f"{base_size * decay:.10f}"))
            decay *= self._depth_decay_f

    # ------------------------------------------------------------------
    # Protocol-required property
    # ------------------------------------------------------------------

    @property
    def steps_per_bar(self) -> int:
        """Number of intra-bar steps this synthesizer was configured for."""
        return self._cfg.steps_per_bar

    # ------------------------------------------------------------------
    # Public synthesis method
    # ------------------------------------------------------------------

    def synthesize(
        self,
        candle: CandleRow,
        instrument_id: InstrumentId,
        step_index: int,
        rng: random.Random,
    ) -> OrderBookSnapshot:
        """Build a synthetic order book for one intra-bar sub-step.

        ``step_index=0`` always returns a book whose mid equals
        ``candle.open``, enforcing the look-ahead bias invariant.

        Parameters
        ----------
        candle:
            Source OHLCV bar.  ``candle.timestamp_ns`` is used as the
            snapshot timestamp.
        instrument_id:
            Target instrument.
        step_index:
            Zero-based index within the bar (0 … steps_per_bar-1).
            Values outside this range are clamped defensively.
        rng:
            Caller-owned seeded RNG; consumed only for high/low ordering.

        Returns
        -------
        OrderBookSnapshot
            Synthetic book with ``depth_levels`` levels per side, bids
            sorted highest-price-first, asks sorted lowest-price-first.
        """
        mid = self._mid_price(candle, step_index, rng)
        spread_dec = self._spread(candle, mid)
        bids, asks = self._build_levels(mid, spread_dec)

        return OrderBookSnapshot(
            instrument_id=instrument_id,
            bids=tuple(bids),
            asks=tuple(asks),
            timestamp_ns=candle.timestamp_ns,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _mid_price(
        self,
        candle: CandleRow,
        step_index: int,
        rng: random.Random,
    ) -> float:
        """Return the intra-bar mid price for ``step_index`` as a float."""
        prices = _ohlc_waypoints(candle, self._cfg.steps_per_bar, rng)
        idx = max(0, min(step_index, len(prices) - 1))
        return prices[idx]

    def _spread(self, candle: CandleRow, mid: float) -> float:
        """Compute the dimensionless fractional spread for this bar/step.

        Uses native float arithmetic; precision is sufficient for
        synthetic book construction.
        """
        if mid <= 0.0:
            return self._base_spread_frac
        range_f = float(candle.high) - float(candle.low)
        vol_adj = 1.0 + self._vol_spread_mult_f * (range_f / mid)
        return self._base_spread_frac * vol_adj

    def _build_levels(
        self,
        mid: float,
        spread_dec: float,
    ) -> tuple[list[BookLevel], list[BookLevel]]:
        """Generate bid and ask depth levels around ``mid``.

        Internal math uses float; Decimal conversion happens only at
        ``BookLevel`` construction.  Depth sizes are pre-computed at init.
        """
        half_spread = spread_dec * 0.5

        best_bid = mid * (1.0 - half_spread)
        best_ask = mid * (1.0 + half_spread)

        n: int = self._cfg.depth_levels
        level_step = mid * spread_dec / n if n > 0 else 0.0

        bids: list[BookLevel] = []
        asks: list[BookLevel] = []

        for i in range(n):
            bids.append(BookLevel(
                price=Decimal(f"{best_bid - i * level_step:.10f}"),
                size=self._depth_sizes[i],
            ))
            asks.append(BookLevel(
                price=Decimal(f"{best_ask + i * level_step:.10f}"),
                size=self._depth_sizes[i],
            ))

        return bids, asks


# ---------------------------------------------------------------------------
# TradeBookSynthesizer
# ---------------------------------------------------------------------------


class TradeBookSynthesizer:
    """Synthesizes an ``OrderBookSnapshot`` from a batch of real trade ticks.

    Aggregation rules
    ~~~~~~~~~~~~~~~~~
    - **Buy trades** (aggressive market buys) lift the offer: the
      *minimum* buy-trade price becomes ``best_ask``; cumulative buy
      volume becomes ask-side depth.
    - **Sell trades** (aggressive market sells) hit the bid: the
      *maximum* sell-trade price becomes ``best_bid``; cumulative sell
      volume becomes bid-side depth.
    - When only one side has trades the missing best price is derived from
      the observed side by applying ``fallback_spread_bps``.
    - When no trades are present at all ``candle.open`` is used as mid
      (safe: open is never a future price at bar-start) and synthetic
      half-spreads are applied.

    The returned snapshot always has exactly one level per side (depth
    is a single aggregated level from trade data, not a simulated ladder).

    Parameters
    ----------
    trades:
        All trade ticks for the current time step.
    fallback_spread_bps:
        Spread applied when only one side is observable or no trades
        exist.  Defaults to 5 bps.
    """

    def __init__(
        self,
        trades: list[TradeRow],
        fallback_spread_bps: Decimal = Decimal("5.0"),
    ) -> None:
        self._trades = trades
        self._fallback_spread_bps: Decimal = Decimal(str(fallback_spread_bps))

    # ------------------------------------------------------------------
    # Protocol-required property
    # ------------------------------------------------------------------

    @property
    def steps_per_bar(self) -> int:
        """Always 1 — trade synthesizers operate one step per tick batch."""
        return 1

    # ------------------------------------------------------------------
    # Public synthesis method
    # ------------------------------------------------------------------

    def synthesize(
        self,
        candle: CandleRow,
        instrument_id: InstrumentId,
        step_index: int,
        rng: random.Random,
    ) -> OrderBookSnapshot:
        """Build a one-level-per-side order book from ``self._trades``.

        ``candle``, ``step_index``, and ``rng`` are accepted for protocol
        compatibility.  The primary price signal comes from trade ticks;
        ``candle.open`` is used only as a fallback mid when no trades
        exist (open is safe — it is never a future price at bar start).

        Parameters
        ----------
        candle:
            Bar whose open acts as fallback mid and whose ``timestamp_ns``
            stamps the snapshot.
        instrument_id:
            Target instrument.
        step_index:
            Accepted for interface compatibility; not used in aggregation.
        rng:
            Accepted for interface compatibility; not consumed.

        Returns
        -------
        OrderBookSnapshot
            Single ``BookLevel`` per side.  Zero sizes indicate that the
            level was synthesised from a fallback (no real trade data).
        """
        buy_trades = [t for t in self._trades if t.side == "buy"]
        sell_trades = [t for t in self._trades if t.side == "sell"]

        best_ask: Decimal | None = None
        best_bid: Decimal | None = None
        ask_size: Decimal = _ZERO
        bid_size: Decimal = _ZERO

        if buy_trades:
            # Aggressive buy orders lifted the ask; the lowest trade
            # price on the buy side is the best observable ask.
            best_ask = min(t.price for t in buy_trades)
            ask_size = sum((t.size for t in buy_trades), _ZERO)

        if sell_trades:
            # Aggressive sell orders hit the bid; the highest trade
            # price on the sell side is the best observable bid.
            best_bid = max(t.price for t in sell_trades)
            bid_size = sum((t.size for t in sell_trades), _ZERO)

        # Derive the missing side using the fallback spread.
        fallback_frac = self._fallback_spread_bps / _TEN_THOUSAND

        if best_bid is None and best_ask is None:
            # No trades at all — fall back to candle open as mid.
            mid = candle.open
            half = mid * (fallback_frac / _TWO)
            best_bid = mid - half
            best_ask = mid + half
            # bid_size and ask_size remain _ZERO to signal synthetic data.

        elif best_bid is None:
            # Only ask side observed — synthesise bid from ask.
            assert best_ask is not None  # narrowing for type checkers
            best_bid = best_ask * (_ONE - fallback_frac)

        elif best_ask is None:
            # Only bid side observed — synthesise ask from bid.
            best_ask = best_bid * (_ONE + fallback_frac)

        bids: tuple[BookLevel, ...] = (
            BookLevel(price=best_bid, size=bid_size),
        )
        asks: tuple[BookLevel, ...] = (
            BookLevel(price=best_ask, size=ask_size),
        )

        return OrderBookSnapshot(
            instrument_id=instrument_id,
            bids=bids,
            asks=asks,
            timestamp_ns=candle.timestamp_ns,
        )
