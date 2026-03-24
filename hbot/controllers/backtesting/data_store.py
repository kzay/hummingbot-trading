"""Parquet persistence for CandleRow and TradeRow with Zstd compression.

Handles read/write, validation, and canonical path resolution for the
backtesting data pipeline.  pandas and pyarrow are imported lazily so that
the module can be imported without those dependencies being installed.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from controllers.backtesting.types import CandleRow, FundingRow, LongShortRatioRow, TradeRow

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

# Canonical column order for Parquet files.
_CANDLE_COLUMNS = ["timestamp_ms", "open", "high", "low", "close", "volume"]
_TRADE_COLUMNS = ["timestamp_ms", "side", "price", "size", "trade_id"]
_FUNDING_COLUMNS = ["timestamp_ms", "rate"]
_LS_RATIO_COLUMNS = ["timestamp_ms", "long_account_ratio", "short_account_ratio", "long_short_ratio"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_pandas() -> tuple:
    """Lazy import of pandas and pyarrow; raises ImportError with instructions."""
    try:
        import pandas as pd  # type: ignore[import-untyped]
        import pyarrow  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "pandas and pyarrow are required for Parquet I/O: "
            "pip install pandas pyarrow"
        ) from exc
    return pd, pyarrow  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Candle persistence
# ---------------------------------------------------------------------------

def save_candles(candles: list[CandleRow], path: Path) -> None:
    """Write *candles* to a Parquet file at *path* using Zstd compression.

    The file is written atomically: data is first written to a temporary
    sibling file and then renamed to *path* to avoid leaving a half-written
    file on crash.

    Schema:
        timestamp_ms  int64
        open          float64
        high          float64
        low           float64
        close         float64
        volume        float64
    """
    pd, _ = _require_pandas()

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = [
        {
            "timestamp_ms": c.timestamp_ms,
            "open": float(c.open),
            "high": float(c.high),
            "low": float(c.low),
            "close": float(c.close),
            "volume": float(c.volume),
        }
        for c in candles
    ]
    df = pd.DataFrame(rows, columns=_CANDLE_COLUMNS)
    df = df.astype({
        "timestamp_ms": "int64",
        "open": "float64",
        "high": "float64",
        "low": "float64",
        "close": "float64",
        "volume": "float64",
    })

    tmp_path = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp_path, index=False, compression="zstd", engine="pyarrow",
                  row_group_size=100_000)
    tmp_path.replace(path)
    logger.debug("Saved %d candles → %s", len(candles), path)


def load_candles(path: Path) -> list[CandleRow]:
    """Read a Parquet file written by :func:`save_candles` and return a list
    of :class:`~controllers.backtesting.types.CandleRow`.

    Raises :class:`FileNotFoundError` if *path* does not exist.
    """
    pd, _ = _require_pandas()

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Candle Parquet file not found: {path}")

    df = pd.read_parquet(path, engine="pyarrow", columns=_CANDLE_COLUMNS)
    ts = df["timestamp_ms"].values
    o = df["open"].values
    h = df["high"].values
    lo = df["low"].values
    c = df["close"].values
    v = df["volume"].values
    candles: list[CandleRow] = [
        CandleRow(
            timestamp_ms=int(ts[i]),
            open=Decimal(f"{o[i]:.10g}"),
            high=Decimal(f"{h[i]:.10g}"),
            low=Decimal(f"{lo[i]:.10g}"),
            close=Decimal(f"{c[i]:.10g}"),
            volume=Decimal(f"{v[i]:.10g}"),
        )
        for i in range(len(ts))
    ]
    logger.debug("Loaded %d candles ← %s", len(candles), path)
    return candles


# ---------------------------------------------------------------------------
# Trade persistence
# ---------------------------------------------------------------------------

def save_trades(trades: list[TradeRow], path: Path) -> None:
    """Write *trades* to a Parquet file at *path* using Zstd compression.

    Schema:
        timestamp_ms  int64
        side          object (string)
        price         float64
        size          float64
        trade_id      object (string)
    """
    pd, _ = _require_pandas()

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = [
        {
            "timestamp_ms": t.timestamp_ms,
            "side": t.side,
            "price": float(t.price),
            "size": float(t.size),
            "trade_id": t.trade_id,
        }
        for t in trades
    ]
    df = pd.DataFrame(rows, columns=_TRADE_COLUMNS)
    df = df.astype({
        "timestamp_ms": "int64",
        "price": "float64",
        "size": "float64",
    })

    tmp_path = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp_path, index=False, compression="zstd", engine="pyarrow",
                  row_group_size=100_000)
    tmp_path.replace(path)
    logger.debug("Saved %d trades → %s", len(trades), path)


def load_trades(path: Path) -> list[TradeRow]:
    """Read a Parquet file written by :func:`save_trades` and return a list
    of :class:`~controllers.backtesting.types.TradeRow`.
    """
    pd, _ = _require_pandas()

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Trade Parquet file not found: {path}")

    df = pd.read_parquet(path, engine="pyarrow", columns=_TRADE_COLUMNS)
    trades: list[TradeRow] = []
    for row in df.itertuples(index=False):
        trades.append(TradeRow(
            timestamp_ms=int(row.timestamp_ms),
            side=str(row.side),
            price=Decimal(str(row.price)),
            size=Decimal(str(row.size)),
            trade_id=str(row.trade_id) if row.trade_id else "",
        ))
    logger.debug("Loaded %d trades ← %s", len(trades), path)
    return trades


# ---------------------------------------------------------------------------
# Funding-rate persistence
# ---------------------------------------------------------------------------

def save_funding_rates(rates: list[FundingRow], path: Path) -> None:
    """Write *rates* to a Parquet file at *path* using Zstd compression."""
    pd, _ = _require_pandas()

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = [
        {
            "timestamp_ms": rate.timestamp_ms,
            "rate": float(rate.rate),
        }
        for rate in rates
    ]
    df = pd.DataFrame(rows, columns=_FUNDING_COLUMNS)
    df = df.astype({
        "timestamp_ms": "int64",
        "rate": "float64",
    })

    tmp_path = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp_path, index=False, compression="zstd", engine="pyarrow",
                  row_group_size=100_000)
    tmp_path.replace(path)
    logger.debug("Saved %d funding rows → %s", len(rates), path)


def load_funding_rates(path: Path) -> list[FundingRow]:
    """Read a Parquet file written by :func:`save_funding_rates`."""
    pd, _ = _require_pandas()

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Funding-rate Parquet file not found: {path}")

    df = pd.read_parquet(path, engine="pyarrow", columns=_FUNDING_COLUMNS)
    rates: list[FundingRow] = []
    for row in df.itertuples(index=False):
        rates.append(FundingRow(
            timestamp_ms=int(row.timestamp_ms),
            rate=Decimal(str(row.rate)),
        ))
    logger.debug("Loaded %d funding rows ← %s", len(rates), path)
    return rates


# ---------------------------------------------------------------------------
# Long/short ratio persistence
# ---------------------------------------------------------------------------

def save_long_short_ratio(rows: list[LongShortRatioRow], path: Path) -> None:
    """Write *rows* to a Parquet file at *path* using Zstd compression."""
    pd, _ = _require_pandas()

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = [
        {
            "timestamp_ms": r.timestamp_ms,
            "long_account_ratio": r.long_account_ratio,
            "short_account_ratio": r.short_account_ratio,
            "long_short_ratio": r.long_short_ratio,
        }
        for r in rows
    ]
    df = pd.DataFrame(data, columns=_LS_RATIO_COLUMNS)
    df = df.astype({
        "timestamp_ms": "int64",
        "long_account_ratio": "float64",
        "short_account_ratio": "float64",
        "long_short_ratio": "float64",
    })

    tmp_path = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp_path, index=False, compression="zstd", engine="pyarrow",
                  row_group_size=100_000)
    tmp_path.replace(path)
    logger.debug("Saved %d LS-ratio rows → %s", len(rows), path)


def load_long_short_ratio(path: Path) -> list[LongShortRatioRow]:
    """Read a Parquet file written by :func:`save_long_short_ratio`."""
    pd, _ = _require_pandas()

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"LS-ratio Parquet file not found: {path}")

    df = pd.read_parquet(path, engine="pyarrow", columns=_LS_RATIO_COLUMNS)
    rows: list[LongShortRatioRow] = []
    for row in df.itertuples(index=False):
        rows.append(LongShortRatioRow(
            timestamp_ms=int(row.timestamp_ms),
            long_account_ratio=float(row.long_account_ratio),
            short_account_ratio=float(row.short_account_ratio),
            long_short_ratio=float(row.long_short_ratio),
        ))
    logger.debug("Loaded %d LS-ratio rows ← %s", len(rows), path)
    return rows


# ---------------------------------------------------------------------------
# Filtered window loaders (predicate-pushed reads)
# ---------------------------------------------------------------------------

def load_candles_window(
    path: Path,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> list[CandleRow]:
    """Read a candle Parquet file, returning only rows within ``[start_ms, end_ms]``.

    Uses pyarrow row-group statistics for predicate pushdown so that
    irrelevant row groups are skipped entirely.  Returns ``CandleRow``
    objects in chronological order.

    When both *start_ms* and *end_ms* are ``None``, behaves identically
    to :func:`load_candles` (full file read).
    """
    pd, _ = _require_pandas()
    import pyarrow.parquet as pq

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Candle Parquet file not found: {path}")

    filters: list[tuple] = []
    if start_ms is not None:
        filters.append(("timestamp_ms", ">=", start_ms))
    if end_ms is not None:
        filters.append(("timestamp_ms", "<=", end_ms))

    table = pq.read_table(
        path,
        columns=_CANDLE_COLUMNS,
        filters=filters or None,
    )
    ts = table.column("timestamp_ms").to_pylist()
    o = table.column("open").to_pylist()
    h = table.column("high").to_pylist()
    lo = table.column("low").to_pylist()
    c = table.column("close").to_pylist()
    v = table.column("volume").to_pylist()

    candles: list[CandleRow] = [
        CandleRow(
            timestamp_ms=int(ts[i]),
            open=Decimal(f"{o[i]:.10g}"),
            high=Decimal(f"{h[i]:.10g}"),
            low=Decimal(f"{lo[i]:.10g}"),
            close=Decimal(f"{c[i]:.10g}"),
            volume=Decimal(f"{v[i]:.10g}"),
        )
        for i in range(len(ts))
    ]
    candles.sort(key=lambda r: r.timestamp_ms)
    logger.debug(
        "Loaded %d candles (window [%s, %s]) ← %s",
        len(candles), start_ms, end_ms, path,
    )
    return candles


def load_trades_window(
    path: Path,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> list[TradeRow]:
    """Read a trade Parquet file, returning only rows within ``[start_ms, end_ms]``.

    Uses pyarrow predicate pushdown.  Returns ``TradeRow`` objects in
    chronological order.
    """
    pd, _ = _require_pandas()
    import pyarrow.parquet as pq

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Trade Parquet file not found: {path}")

    filters: list[tuple] = []
    if start_ms is not None:
        filters.append(("timestamp_ms", ">=", start_ms))
    if end_ms is not None:
        filters.append(("timestamp_ms", "<=", end_ms))

    table = pq.read_table(
        path,
        columns=_TRADE_COLUMNS,
        filters=filters or None,
    )
    trades: list[TradeRow] = []
    for i in range(table.num_rows):
        trades.append(TradeRow(
            timestamp_ms=int(table.column("timestamp_ms")[i].as_py()),
            side=str(table.column("side")[i].as_py()),
            price=Decimal(str(table.column("price")[i].as_py())),
            size=Decimal(str(table.column("size")[i].as_py())),
            trade_id=str(table.column("trade_id")[i].as_py() or ""),
        ))
    trades.sort(key=lambda r: r.timestamp_ms)
    logger.debug(
        "Loaded %d trades (window [%s, %s]) ← %s",
        len(trades), start_ms, end_ms, path,
    )
    return trades


def load_funding_window(
    path: Path,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> list[FundingRow]:
    """Read a funding-rate Parquet file, returning only rows within ``[start_ms, end_ms]``.

    Uses pyarrow predicate pushdown.  Returns ``FundingRow`` objects in
    chronological order.
    """
    pd, _ = _require_pandas()
    import pyarrow.parquet as pq

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Funding-rate Parquet file not found: {path}")

    filters: list[tuple] = []
    if start_ms is not None:
        filters.append(("timestamp_ms", ">=", start_ms))
    if end_ms is not None:
        filters.append(("timestamp_ms", "<=", end_ms))

    table = pq.read_table(
        path,
        columns=_FUNDING_COLUMNS,
        filters=filters or None,
    )
    rates: list[FundingRow] = []
    for i in range(table.num_rows):
        rates.append(FundingRow(
            timestamp_ms=int(table.column("timestamp_ms")[i].as_py()),
            rate=Decimal(str(table.column("rate")[i].as_py())),
        ))
    rates.sort(key=lambda r: r.timestamp_ms)
    logger.debug(
        "Loaded %d funding rows (window [%s, %s]) ← %s",
        len(rates), start_ms, end_ms, path,
    )
    return rates


# ---------------------------------------------------------------------------
# Direct DataFrame loading (ML pipeline)
# ---------------------------------------------------------------------------

def load_candles_df(path: Path) -> pd.DataFrame:
    """Read a candle Parquet file directly into a float64 DataFrame.

    Bypasses the CandleRow / Decimal conversion round-trip used by
    :func:`load_candles`.  Intended for the ML feature pipeline where
    float64 is the native type and Decimal overhead is unnecessary.
    """
    pd, _ = _require_pandas()

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Candle Parquet file not found: {path}")

    df = pd.read_parquet(path, engine="pyarrow", columns=_CANDLE_COLUMNS)
    df = df.astype({
        "timestamp_ms": "int64",
        "open": "float64",
        "high": "float64",
        "low": "float64",
        "close": "float64",
        "volume": "float64",
    })
    logger.debug("Loaded %d candle rows as DataFrame ← %s", len(df), path)
    return df


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_candles(
    candles: list[CandleRow],
    *,
    expected_interval_ms: int = 60_000,
    max_gap_multiple: int = 3,
    max_return_pct: float = 20.0,
) -> list[str]:
    """Run integrity checks on *candles* and return a list of warning strings.

    Checks performed:
    * No duplicate ``timestamp_ms`` values.
    * Timestamps are monotonically increasing.
    * No zero or negative open/high/low/close prices.
    * No zero or negative volume.
    * OHLC consistency: ``high >= max(open, close)`` and ``low <= min(open, close)``.
    * Gap detection: warns when the gap between consecutive bars exceeds
      ``max_gap_multiple * expected_interval_ms``.
    * Spike detection: warns when single-bar return exceeds ``max_return_pct``.

    An empty *return* list means the data passed all checks. An empty *input*
    list is treated as valid (nothing to validate).
    """
    warnings: list[str] = []
    if not candles:
        return warnings

    seen_ts: set[int] = set()
    prev_ts: int | None = None
    _zero = Decimal("0")
    gap_threshold_ms = max_gap_multiple * expected_interval_ms
    gap_count = 0
    _MAX_GAP_WARNINGS = 10

    for idx, c in enumerate(candles):
        # Duplicate timestamps
        if c.timestamp_ms in seen_ts:
            warnings.append(
                f"Duplicate timestamp_ms={c.timestamp_ms} at index {idx}"
            )
        seen_ts.add(c.timestamp_ms)

        # Monotonically increasing
        if prev_ts is not None and c.timestamp_ms <= prev_ts:
            warnings.append(
                f"Non-monotonic timestamp at index {idx}: "
                f"{c.timestamp_ms} <= previous {prev_ts}"
            )

        # Gap detection (only report first N to avoid flooding)
        if prev_ts is not None and c.timestamp_ms > prev_ts:
            gap = c.timestamp_ms - prev_ts
            if gap > gap_threshold_ms:
                gap_count += 1
                if gap_count <= _MAX_GAP_WARNINGS:
                    gap_minutes = gap / 60_000
                    warnings.append(
                        f"Gap of {gap_minutes:.0f} minutes at index {idx} "
                        f"(timestamp_ms={c.timestamp_ms}, previous={prev_ts})"
                    )

        prev_ts = c.timestamp_ms

        for field_name, value in (
            ("open", c.open),
            ("high", c.high),
            ("low", c.low),
            ("close", c.close),
        ):
            if value <= _zero:
                warnings.append(
                    f"Zero or negative {field_name}={value} at index {idx} "
                    f"(timestamp_ms={c.timestamp_ms})"
                )

        if c.volume <= _zero:
            warnings.append(
                f"Zero or negative volume={c.volume} at index {idx} "
                f"(timestamp_ms={c.timestamp_ms})"
            )

        # OHLC consistency
        if c.open > _zero and c.high > _zero and c.low > _zero and c.close > _zero:
            oc_max = max(c.open, c.close)
            oc_min = min(c.open, c.close)
            if c.high < oc_max:
                warnings.append(
                    f"OHLC inconsistency: high={c.high} < max(open,close)={oc_max} "
                    f"at index {idx} (timestamp_ms={c.timestamp_ms})"
                )
            if c.low > oc_min:
                warnings.append(
                    f"OHLC inconsistency: low={c.low} > min(open,close)={oc_min} "
                    f"at index {idx} (timestamp_ms={c.timestamp_ms})"
                )

        # Spike detection: single-bar return
        if c.open > _zero and c.close > _zero:
            ret_pct = abs(float((c.close - c.open) / c.open)) * 100
            if ret_pct > max_return_pct:
                warnings.append(
                    f"Spike: {ret_pct:.1f}% single-bar return at index {idx} "
                    f"(timestamp_ms={c.timestamp_ms}, open={c.open}, close={c.close})"
                )

    if gap_count > _MAX_GAP_WARNINGS:
        warnings.append(
            f"... and {gap_count - _MAX_GAP_WARNINGS} more gap warnings suppressed "
            f"(total gaps: {gap_count})"
        )

    return warnings


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def resolve_data_path(
    exchange: str,
    pair: str,
    resolution: str,
    base_dir: str | Path,
) -> Path:
    """Return the canonical Parquet file path for a dataset.

    The returned path follows the pattern::

        {base_dir}/{exchange}/{pair}/{resolution}/data.parquet

    The pair component has ``/`` and ``:`` replaced with ``-`` so that it is
    safe to use as a directory name on all platforms (e.g.
    ``BTC/USDT:USDT`` → ``BTC-USDT-USDT``).
    """
    safe_pair = pair.replace("/", "-").replace(":", "-")
    return Path(base_dir) / exchange / safe_pair / resolution / "data.parquet"
