"""CSV import utilities for the backtesting data pipeline.

Handles two source types:

1. **Generic OHLCV CSVs** — any CSV that has timestamp + OHLCV columns using
   common column name aliases (Binance exports, TradingView, etc.).
2. **tick_emitter CSVs** — the minute-level files produced by
   ``controllers/epp_logging.py``.  These carry ``mid``, ``best_bid_price``,
   and ``best_ask_price`` but no explicit O/H/L/C.  The importer synthesises
   OHLCV candles from these columns: open = close = mid for each row, high
   and low derived from bid/ask, volume set to zero (unavailable).

Column detection is case-insensitive and falls back gracefully with a
descriptive error list rather than crashing.
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import UTC
from decimal import Decimal, InvalidOperation
from pathlib import Path

from controllers.backtesting.types import CandleRow


@dataclass
class CsvImportResult:
    """Structured result from :func:`import_csv`.

    Prefer checking ``ok`` or ``errors`` rather than inspecting the type
    of the raw return value.
    """

    candles: list[CandleRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0 and len(self.candles) > 0

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Alias tables
# ---------------------------------------------------------------------------

# Each entry is a list of accepted column names, tried in order.
# Matching is case-insensitive after stripping whitespace.

_TIMESTAMP_ALIASES: list[str] = [
    "timestamp_ms",
    "timestamp",
    "ts",
    "time",
    "date",
    "datetime",
    "open_time",
    "close_time",
]

_OPEN_ALIASES: list[str] = ["open", "o", "Open", "OPEN"]
_HIGH_ALIASES: list[str] = ["high", "h", "High", "HIGH"]
_LOW_ALIASES: list[str] = ["low", "l", "Low", "LOW"]
_CLOSE_ALIASES: list[str] = ["close", "c", "Close", "CLOSE", "last", "price"]
_VOLUME_ALIASES: list[str] = [
    "volume", "vol", "Volume", "VOL", "VOLUME",
    "base_volume", "quote_volume", "taker_buy_base_asset_volume",
]

# tick_emitter-specific columns used for synthesising OHLCV.
_MID_ALIASES: list[str] = ["mid", "Mid", "MID", "reference_price"]
_BID_ALIASES: list[str] = ["best_bid_price", "bid_price", "bid", "BidPrice"]
_ASK_ALIASES: list[str] = ["best_ask_price", "ask_price", "ask", "AskPrice"]

# Columns required for a standard OHLCV import.
_REQUIRED_OHLCV = ("timestamp", "open", "high", "low", "close")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_col_index(headers: list[str]) -> dict[str, str]:
    """Return a mapping from canonical field name to actual CSV header name.

    Matching is case-insensitive.  The first alias that matches wins.
    """
    lower_to_actual: dict[str, str] = {h.strip().lower(): h for h in headers}

    def _find(aliases: list[str]) -> str | None:
        for alias in aliases:
            actual = lower_to_actual.get(alias.lower())
            if actual is not None:
                return actual
        return None

    mapping: dict[str, str] = {}
    ts_col = _find(_TIMESTAMP_ALIASES)
    if ts_col:
        mapping["timestamp"] = ts_col

    for canonical, aliases in (
        ("open",   _OPEN_ALIASES),
        ("high",   _HIGH_ALIASES),
        ("low",    _LOW_ALIASES),
        ("close",  _CLOSE_ALIASES),
        ("volume", _VOLUME_ALIASES),
    ):
        col = _find(aliases)
        if col:
            mapping[canonical] = col

    # tick_emitter extras
    for canonical, aliases in (
        ("mid", _MID_ALIASES),
        ("bid", _BID_ALIASES),
        ("ask", _ASK_ALIASES),
    ):
        col = _find(aliases)
        if col:
            mapping[canonical] = col

    return mapping


def _parse_timestamp_ms(value: str, col_name: str) -> int:
    """Parse a timestamp value to Unix milliseconds (int).

    Handles:
    * Integer milliseconds (13-digit Unix ts): returned as-is.
    * Integer seconds (10-digit Unix ts): multiplied by 1000.
    * ISO 8601 strings via ``datetime.fromisoformat``.
    * Numeric strings with a decimal point (float seconds).
    """
    value = value.strip()
    if not value:
        raise ValueError(f"Empty timestamp in column {col_name!r}")

    # Try numeric first (covers 99 % of cases and is fast).
    try:
        numeric = float(value)
        if numeric > 1e12:
            # Already in milliseconds.
            return int(numeric)
        # Assume seconds — convert.
        return int(numeric * 1000)
    except ValueError:
        pass

    # Fall back to ISO 8601 parsing.
    from datetime import datetime
    for fmt in (
        None,  # fromisoformat
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y/%m/%d %H:%M:%S",
    ):
        try:
            if fmt is None:
                dt = datetime.fromisoformat(value)
            else:
                dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return int(dt.timestamp() * 1000)
        except (ValueError, OverflowError):
            continue

    raise ValueError(
        f"Cannot parse timestamp value {value!r} from column {col_name!r}"
    )


def _safe_decimal(value: str, field_name: str, row_idx: int) -> Decimal:
    """Convert a CSV string to Decimal, raising a descriptive error on failure."""
    try:
        return Decimal(value.strip())
    except InvalidOperation as exc:
        raise ValueError(
            f"Row {row_idx}: cannot convert {field_name}={value!r} to Decimal"
        ) from exc


def _is_tick_emitter_format(col_map: dict[str, str]) -> bool:
    """Return True if the CSV looks like a tick_emitter output file."""
    has_ohlcv = all(k in col_map for k in ("open", "high", "low", "close"))
    has_mid = "mid" in col_map
    return has_mid and not has_ohlcv


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def import_csv(
    path: Path,
    exchange: str,
    pair: str,
    resolution: str,
) -> list[CandleRow] | list[str]:
    """Import a CSV file and return a list of :class:`CandleRow` objects.

    The function auto-detects the column layout using common alias sets and
    transparently handles both standard OHLCV exports and tick_emitter CSVs.

    Parameters
    ----------
    path:
        Path to the CSV file to import.
    exchange:
        Exchange identifier string (reserved; stored in catalog metadata).
    pair:
        Trading pair string (reserved; stored in catalog metadata).
    resolution:
        Bar resolution string, e.g. ``"1m"`` (reserved; stored in catalog
        metadata).

    Returns
    -------
    list[CandleRow]
        Parsed candle rows, sorted by ``timestamp_ms`` ascending and
        de-duplicated.
    list[str]
        **On error**, returns a list of human-readable error strings
        describing which required columns could not be mapped.  The caller
        can distinguish success from failure by checking
        ``isinstance(result[0], str)`` (or by checking that the list is
        non-empty and all elements are strings).

    Notes
    -----
    * For tick_emitter files (columns ``mid``, ``best_bid_price``,
      ``best_ask_price``): open = close = mid, high = ask, low = bid,
      volume = 0.
    * All numeric parsing errors on individual rows emit a ``WARNING`` log
      and skip that row rather than aborting the entire import.
    """
    path = Path(path)
    if not path.exists():
        return [f"File not found: {path}"]

    with path.open(newline="", encoding="utf-8-sig") as fh:
        # Sniff delimiter — handles comma, semicolon, tab.
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel  # type: ignore[assignment]

        reader = csv.DictReader(fh, dialect=dialect)
        if reader.fieldnames is None:
            return ["CSV file has no header row or is empty"]

        headers: list[str] = list(reader.fieldnames)
        col_map = _build_col_index(headers)

        # ------------------------------------------------------------------
        # Validate that we have enough columns to proceed.
        # ------------------------------------------------------------------
        is_tick = _is_tick_emitter_format(col_map)

        if is_tick:
            missing: list[str] = []
            if "timestamp" not in col_map:
                missing.append(
                    "timestamp — tried aliases: "
                    + ", ".join(_TIMESTAMP_ALIASES[:5])
                )
            if "mid" not in col_map:
                missing.append(
                    "mid (tick_emitter format) — tried aliases: "
                    + ", ".join(_MID_ALIASES)
                )
            if missing:
                return [
                    "tick_emitter CSV import failed — cannot map required columns:",
                    *[f"  missing: {m}" for m in missing],
                    f"  available columns: {headers}",
                ]
            logger.info(
                "Detected tick_emitter CSV format at %s (mid+bid/ask synthesis)", path
            )
        else:
            missing = []
            for required in _REQUIRED_OHLCV:
                if required not in col_map:
                    alias_hint = {
                        "timestamp": _TIMESTAMP_ALIASES[:5],
                        "open":      _OPEN_ALIASES,
                        "high":      _HIGH_ALIASES,
                        "low":       _LOW_ALIASES,
                        "close":     _CLOSE_ALIASES,
                    }.get(required, [])
                    missing.append(
                        f"{required} — tried aliases: "
                        + ", ".join(str(a) for a in alias_hint)
                    )
            if missing:
                return [
                    "OHLCV CSV import failed — cannot map required columns:",
                    *[f"  missing: {m}" for m in missing],
                    f"  available columns: {headers}",
                ]
            if "volume" not in col_map:
                logger.warning(
                    "%s: no volume column found; volume will default to 0", path
                )

        # ------------------------------------------------------------------
        # Parse rows.
        # ------------------------------------------------------------------
        _ZERO = Decimal("0")
        raw: list[tuple[int, CandleRow]] = []  # (ts_ms, row) for sorting

        for row_idx, row in enumerate(reader, start=2):  # row 1 is header
            try:
                ts_ms = _parse_timestamp_ms(
                    row[col_map["timestamp"]], col_map["timestamp"]
                )
            except (ValueError, KeyError) as exc:
                logger.warning("Row %d: skipping — bad timestamp: %s", row_idx, exc)
                continue

            try:
                if is_tick:
                    mid = _safe_decimal(row[col_map["mid"]], "mid", row_idx)

                    # Bid and ask are optional in tick_emitter files if the
                    # market snapshot was unavailable.
                    bid: Decimal = mid
                    ask: Decimal = mid
                    if "bid" in col_map:
                        raw_bid = row.get(col_map["bid"], "").strip()
                        if raw_bid:
                            bid = _safe_decimal(raw_bid, "bid", row_idx)
                    if "ask" in col_map:
                        raw_ask = row.get(col_map["ask"], "").strip()
                        if raw_ask:
                            ask = _safe_decimal(raw_ask, "ask", row_idx)

                    candle = CandleRow(
                        timestamp_ms=ts_ms,
                        open=mid,
                        high=max(ask, mid),
                        low=min(bid, mid),
                        close=mid,
                        volume=_ZERO,
                    )
                else:
                    open_val  = _safe_decimal(row[col_map["open"]],  "open",  row_idx)
                    high_val  = _safe_decimal(row[col_map["high"]],  "high",  row_idx)
                    low_val   = _safe_decimal(row[col_map["low"]],   "low",   row_idx)
                    close_val = _safe_decimal(row[col_map["close"]], "close", row_idx)

                    if "volume" in col_map:
                        raw_vol = row.get(col_map["volume"], "").strip()
                        volume_val = (
                            _safe_decimal(raw_vol, "volume", row_idx)
                            if raw_vol else _ZERO
                        )
                    else:
                        volume_val = _ZERO

                    candle = CandleRow(
                        timestamp_ms=ts_ms,
                        open=open_val,
                        high=high_val,
                        low=low_val,
                        close=close_val,
                        volume=volume_val,
                    )
            except (ValueError, KeyError) as exc:
                logger.warning("Row %d: skipping — parse error: %s", row_idx, exc)
                continue

            raw.append((ts_ms, candle))

    # De-duplicate (keep first) and sort.
    seen_ts: set[int] = set()
    candles: list[CandleRow] = []
    for ts_ms, candle in sorted(raw, key=lambda x: x[0]):
        if ts_ms in seen_ts:
            continue
        seen_ts.add(ts_ms)
        candles.append(candle)

    logger.info(
        "Imported %d candles from %s (format=%s)",
        len(candles), path, "tick_emitter" if is_tick else "ohlcv",
    )
    return candles


def import_csv_safe(
    path: Path,
    exchange: str = "",
    pair: str = "",
    resolution: str = "",
) -> CsvImportResult:
    """Type-safe wrapper around :func:`import_csv`.

    Returns a :class:`CsvImportResult` with separate ``candles`` and
    ``errors`` fields, avoiding the fragile union return type.
    """
    result = import_csv(path, exchange, pair, resolution)
    if isinstance(result, list) and result and isinstance(result[0], str):
        return CsvImportResult(errors=result)
    return CsvImportResult(candles=result)  # type: ignore[arg-type]


def import_and_register(
    csv_path: Path,
    exchange: str,
    pair: str,
    resolution: str,
    catalog_dir: str = "data/historical",
) -> CsvImportResult:
    """Import a CSV, save as Parquet, and register in the DataCatalog.

    End-to-end pipeline: CSV → CandleRow → Parquet → catalog entry.
    """
    result = import_csv_safe(csv_path, exchange, pair, resolution)
    if not result.ok:
        return result

    from controllers.backtesting.data_catalog import DataCatalog
    from controllers.backtesting.data_store import save_candles

    catalog = DataCatalog(base_dir=Path(catalog_dir))
    pair_key = pair.replace("/", "-").replace(":", "-")
    parquet_path = Path(catalog_dir) / exchange / pair_key / resolution / "candles.parquet"
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    save_candles(result.candles, parquet_path)
    catalog.register(
        exchange=exchange,
        pair=pair_key,
        resolution=resolution,
        file_path=str(parquet_path),
        row_count=len(result.candles),
        start_ms=result.candles[0].timestamp_ms,
        end_ms=result.candles[-1].timestamp_ms,
        file_size_bytes=parquet_path.stat().st_size,
    )
    logger.info(
        "Registered %d candles from %s → %s (catalog: %s)",
        len(result.candles), csv_path, parquet_path, catalog_dir,
    )
    return result
