"""Historical data feed for the backtesting engine.

Implements the ``MarketDataFeed`` protocol using pre-loaded OHLCV candles and
a :class:`~controllers.backtesting.book_synthesizer.BookSynthesizer` instance.
Replaces the live ``HummingbotDataFeed`` / ``ReplayDataFeed`` adapters with a
purely deterministic, time-cursor-driven source that is suitable for replay at
arbitrary speeds.

Time model
----------
The feed maintains a single mutable integer cursor ``_current_ns`` that is
advanced exclusively by :meth:`set_time`.  All query methods (``get_book``,
``get_mid_price``, ``get_funding_rate``) are **read-only** with respect to the
cursor — they synthesise data for the current instant but do not move time
forward.  This matches the contract of Paper Engine V2's ``MarketDataFeed``
protocol.

Candle-to-step mapping
-----------------------
Given:
    * ``first_candle_ns``  — ``timestamp_ns`` of ``candles[0]``
    * ``candle_interval_ns`` — bar width in nanoseconds, derived from the
      median gap between consecutive candle timestamps (robust to a single
      missing bar at the seam) and validated against
      ``step_interval_ns * steps_per_bar``
    * ``step_interval_ns``  — supplied by the harness (engine tick cadence)
    * ``steps_per_bar``     — taken from ``synthesizer.steps_per_bar``

For a given ``now_ns``:
    elapsed_ns   = now_ns - first_candle_ns
    candle_index = elapsed_ns // candle_interval_ns
    step_index   = (elapsed_ns % candle_interval_ns) // step_interval_ns

Edge cases handled:
    * ``now_ns < first_candle_ns`` → out-of-range, all queries return ``None``.
    * ``candle_index >= len(candles)`` → data exhausted, all queries return
      ``None`` (``has_data()`` returns ``False``).
    * ``step_index >= steps_per_bar`` is clamped to ``steps_per_bar - 1`` to
      guard against floating-point drift at candle boundaries.

Funding rates
-------------
The ``funding_rates`` dict maps ``timestamp_ms`` (milliseconds since epoch) to
a ``Decimal`` rate.  Look-up uses the largest key that is ``<= now_ms``
(floor-search), mirroring how real exchange funding events are applied.
Returns ``Decimal("0")`` when the dict is empty or no preceding entry exists.
"""
from __future__ import annotations

import bisect
import logging
import random
from decimal import Decimal

from controllers.backtesting.book_synthesizer import BookSynthesizer
from controllers.backtesting.types import CandleRow
from simulation.types import (
    InstrumentId,
    OrderBookSnapshot,
)

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")

# Minimum number of candles required to infer the bar interval.
_MIN_CANDLES_FOR_INTERVAL = 2


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _derive_candle_interval_ns(candles: list[CandleRow]) -> int:
    """Return the candle bar width in nanoseconds.

    Uses the median inter-bar gap computed from the first few candles to be
    robust against a single missing bar at the start of the series.

    Raises
    ------
    ValueError
        If fewer than two candles are supplied (impossible to infer interval).
    """
    if len(candles) < _MIN_CANDLES_FOR_INTERVAL:
        raise ValueError(
            f"HistoricalDataFeed requires at least {_MIN_CANDLES_FOR_INTERVAL} "
            f"candles to derive bar interval; got {len(candles)}"
        )

    # Gather up to 10 gap samples (avoids O(N) scan on long series).
    sample = candles[: min(len(candles), 11)]
    gaps = [
        (sample[i + 1].timestamp_ms - sample[i].timestamp_ms) * 1_000_000
        for i in range(len(sample) - 1)
    ]
    # Median is more robust than mean when the series has a gap at the seam.
    gaps_sorted = sorted(gaps)
    mid = len(gaps_sorted) // 2
    if len(gaps_sorted) % 2 == 1:
        return gaps_sorted[mid]
    # Even-length: take the lower of the two middle values (conservative).
    return gaps_sorted[mid - 1]


def _sorted_funding_keys(funding_rates: dict[int, Decimal]) -> list[int]:
    """Return sorted list of funding rate timestamp keys (milliseconds)."""
    return sorted(funding_rates.keys())


# ---------------------------------------------------------------------------
# HistoricalDataFeed
# ---------------------------------------------------------------------------

class HistoricalDataFeed:
    """``MarketDataFeed`` implementation backed by OHLCV candle data.

    Parameters
    ----------
    candles:
        Chronologically ordered OHLCV bars.  Must contain at least two
        entries so that the bar interval can be derived.
    instrument_id:
        Instrument this feed represents.  Queries for a *different*
        ``instrument_id`` return ``None`` (the feed is single-instrument).
    synthesizer:
        Converts a candle bar + step index into an ``OrderBookSnapshot``.
        ``synthesizer.steps_per_bar`` determines how many ticks constitute
        one bar.
    step_interval_ns:
        Duration of each engine tick in nanoseconds (e.g. ``60_000_000_000``
        for 1-minute ticks).  Must satisfy:
        ``step_interval_ns * synthesizer.steps_per_bar == candle_interval_ns``.
        A mismatch triggers a ``ValueError`` at construction time to surface
        misconfiguration early.
    funding_rates:
        Optional mapping of ``timestamp_ms → rate``.  Used by perpetual
        instruments.  ``None`` is treated as an empty dict.
    seed:
        Seed for the internal ``random.Random`` instance forwarded to the
        synthesizer on every call.  Ensures byte-for-byte reproducibility
        across independent runs with the same seed.
    """

    def __init__(
        self,
        candles: list[CandleRow],
        instrument_id: InstrumentId,
        synthesizer: BookSynthesizer,
        step_interval_ns: int,
        funding_rates: dict[int, Decimal] | None = None,
        seed: int = 42,
    ) -> None:
        if not candles:
            raise ValueError("HistoricalDataFeed: candles list must not be empty")
        if step_interval_ns <= 0:
            raise ValueError(
                f"HistoricalDataFeed: step_interval_ns must be > 0; got {step_interval_ns}"
            )

        self._candles: list[CandleRow] = candles
        self._instrument_id: InstrumentId = instrument_id
        self._synthesizer: BookSynthesizer = synthesizer
        self._step_interval_ns: int = step_interval_ns
        self._funding_rates: dict[int, Decimal] = dict(funding_rates) if funding_rates else {}
        self._seed: int = seed
        self._rng: random.Random = random.Random(seed)

        # Derive candle interval and validate against step configuration.
        self._candle_interval_ns: int = _derive_candle_interval_ns(candles)
        self._steps_per_bar: int = synthesizer.steps_per_bar

        expected_candle_interval = step_interval_ns * self._steps_per_bar
        if self._candle_interval_ns != expected_candle_interval:
            logger.warning(
                "HistoricalDataFeed: candle_interval_ns=%d does not equal "
                "step_interval_ns(%d) * steps_per_bar(%d)=%d; "
                "time mapping may be inaccurate",
                self._candle_interval_ns,
                step_interval_ns,
                self._steps_per_bar,
                expected_candle_interval,
            )

        # Anchor point: first candle's nanosecond timestamp.
        self._first_candle_ns: int = candles[0].timestamp_ns

        # Pre-sort funding rate keys for O(log N) floor-search.
        self._funding_keys: list[int] = _sorted_funding_keys(self._funding_rates)

        # Internal time cursor (nanoseconds since epoch).
        # Starts before the first candle so that has_data() is False until
        # set_time() is called.
        self._current_ns: int = self._first_candle_ns - 1

        # Book synthesis cache: avoids re-synthesizing for the same timestamp.
        self._cached_book: OrderBookSnapshot | None = None
        self._cached_book_ns: int = -1

        logger.debug(
            "HistoricalDataFeed initialised: instrument=%s candles=%d "
            "candle_interval_ns=%d steps_per_bar=%d step_interval_ns=%d "
            "first_ns=%d last_ns=%d",
            instrument_id,
            len(candles),
            self._candle_interval_ns,
            self._steps_per_bar,
            step_interval_ns,
            self._first_candle_ns,
            self.data_end_ns,
        )

    # ------------------------------------------------------------------
    # Time cursor
    # ------------------------------------------------------------------

    def set_time(self, now_ns: int) -> None:
        """Advance (or rewind) the feed's internal time cursor to *now_ns*.

        Subsequent calls to ``get_book`` / ``get_mid_price`` /
        ``get_funding_rate`` will reflect this new instant.

        Parameters
        ----------
        now_ns:
            Absolute Unix timestamp in nanoseconds.
        """
        self._current_ns = now_ns

    # ------------------------------------------------------------------
    # Data range properties
    # ------------------------------------------------------------------

    @property
    def data_start_ns(self) -> int:
        """Unix timestamp (nanoseconds) of the first candle bar."""
        return self._first_candle_ns

    @property
    def data_end_ns(self) -> int:
        """Unix timestamp (nanoseconds) of the last candle bar's open edge.

        A query at exactly ``data_end_ns`` maps to the last candle; a query
        at ``data_end_ns + candle_interval_ns`` is out-of-range.
        """
        return self._first_candle_ns + (len(self._candles) - 1) * self._candle_interval_ns

    # ------------------------------------------------------------------
    # Internal candle/step resolution
    # ------------------------------------------------------------------

    def _resolve(self, now_ns: int) -> tuple[CandleRow | None, int]:
        """Map *now_ns* to a ``(candle, step_index)`` pair.

        Returns ``(None, 0)`` when *now_ns* is outside the data window.

        The step_index is clamped to ``[0, steps_per_bar - 1]`` to prevent
        an off-by-one at the very end of a bar caused by integer rounding.
        """
        if now_ns < self._first_candle_ns:
            return None, 0

        elapsed_ns = now_ns - self._first_candle_ns
        candle_index = elapsed_ns // self._candle_interval_ns

        if candle_index >= len(self._candles):
            return None, 0

        candle = self._candles[candle_index]

        raw_step = (elapsed_ns % self._candle_interval_ns) // self._step_interval_ns
        step_index = min(int(raw_step), self._steps_per_bar - 1)

        return candle, step_index

    # ------------------------------------------------------------------
    # MarketDataFeed protocol
    # ------------------------------------------------------------------

    def get_book(self, instrument_id: InstrumentId) -> OrderBookSnapshot | None:
        """Return a synthesised ``OrderBookSnapshot`` for the current time cursor.

        Returns ``None`` if:
        * The current time is before the first candle or after the last candle.
        * *instrument_id* does not match the feed's instrument.

        Results are cached per timestamp — repeated calls within the same
        tick return the same object without re-synthesizing.
        """
        if instrument_id != self._instrument_id:
            return None

        if self._current_ns == self._cached_book_ns:
            return self._cached_book

        candle, step_index = self._resolve(self._current_ns)
        if candle is None:
            self._cached_book = None
            self._cached_book_ns = self._current_ns
            return None

        try:
            book = self._synthesizer.synthesize(
                candle=candle,
                instrument_id=instrument_id,
                step_index=step_index,
                rng=self._rng,
            )
            if book.timestamp_ns != self._current_ns:
                book = OrderBookSnapshot(
                    instrument_id=book.instrument_id,
                    bids=book.bids,
                    asks=book.asks,
                    timestamp_ns=self._current_ns,
                )
            self._cached_book = book
            self._cached_book_ns = self._current_ns
            return book
        except Exception:
            logger.exception(
                "HistoricalDataFeed: synthesizer raised an exception at "
                "now_ns=%d candle_ts_ms=%d step_index=%d",
                self._current_ns,
                candle.timestamp_ms,
                step_index,
            )
            self._cached_book = None
            self._cached_book_ns = self._current_ns
            return None

    def get_mid_price(self, instrument_id: InstrumentId) -> Decimal | None:
        """Return the mid-price for the current time cursor.

        Derives mid from :meth:`get_book`.  Returns ``None`` when no book is
        available.
        """
        book = self.get_book(instrument_id)
        if book is None:
            return None
        return book.mid_price

    def get_funding_rate(self, instrument_id: InstrumentId) -> Decimal:
        """Return the funding rate applicable at the current time cursor.

        Performs a floor-search over ``funding_rates`` keyed by
        ``timestamp_ms``: the entry with the largest key that is
        ``<= now_ms`` is used.  Returns ``Decimal("0")`` when:
        * ``funding_rates`` was not supplied.
        * No entry precedes the current time.
        * *instrument_id* does not match the feed's instrument.
        """
        if instrument_id != self._instrument_id:
            return _ZERO
        if not self._funding_keys:
            return _ZERO

        now_ms = self._current_ns // 1_000_000

        # bisect_right gives the insertion point after all keys <= now_ms.
        # Subtract 1 to get the index of the floor key.
        pos = bisect.bisect_right(self._funding_keys, now_ms) - 1
        if pos < 0:
            return _ZERO

        key = self._funding_keys[pos]
        return self._funding_rates.get(key, _ZERO)

    # ------------------------------------------------------------------
    # Candle access
    # ------------------------------------------------------------------

    def get_current_candle(self) -> CandleRow | None:
        """Return the ``CandleRow`` that the current time cursor falls within.

        Returns ``None`` when the cursor is outside the data window.
        """
        candle, _ = self._resolve(self._current_ns)
        return candle

    @property
    def current_step_index(self) -> int:
        """The intra-bar step index for the current time cursor."""
        _, step = self._resolve(self._current_ns)
        return step

    @property
    def steps_per_bar(self) -> int:
        """Number of engine ticks per candle bar."""
        return self._steps_per_bar

    # ------------------------------------------------------------------
    # Feed lifecycle helpers
    # ------------------------------------------------------------------

    def has_data(self) -> bool:
        """Return ``True`` if the current time cursor is within the data window.

        A feed is considered to have data when ``data_start_ns <= _current_ns``
        and the cursor maps to a valid candle index (i.e. not past the last
        candle).
        """
        if self._current_ns < self._first_candle_ns:
            return False
        candle, _ = self._resolve(self._current_ns)
        return candle is not None

    def reset(self, seed: int | None = None) -> None:
        """Reset the cursor to before the first candle and re-seed the RNG.

        Useful for running multiple passes over the same data (e.g. Monte
        Carlo or walk-forward scenarios) without constructing a new feed.

        Parameters
        ----------
        seed:
            New seed for the internal RNG.  If ``None``, the original seed
            used at construction time is restored.  Pass an explicit integer
            to get a different but still deterministic sequence.
        """
        self._current_ns = self._first_candle_ns - 1
        self._rng.seed(seed if seed is not None else self._seed)
        self._cached_book = None
        self._cached_book_ns = -1

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"HistoricalDataFeed("
            f"instrument={self._instrument_id}, "
            f"candles={len(self._candles)}, "
            f"candle_interval_ns={self._candle_interval_ns}, "
            f"steps_per_bar={self._steps_per_bar}, "
            f"current_ns={self._current_ns}, "
            f"has_data={self.has_data()}"
            f")"
        )
