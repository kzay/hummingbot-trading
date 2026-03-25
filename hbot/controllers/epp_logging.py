"""Buffered CSV split logger for strategy runtime controllers.

Keeps file handles open and buffers rows, flushing periodically or when a
buffer size threshold is reached.  Schema rotation (header mismatch) is
checked only on first open, not on every write.

Historical note: module filename is retained for backward compatibility.
Prefer importing from ``controllers.runtime.logging``.
"""
from __future__ import annotations

import csv
import logging
import os
import queue
import threading
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from io import TextIOWrapper
from pathlib import Path

logger = logging.getLogger(__name__)


class _CsvBuffer:
    """Manages one open CSV file with write buffering."""

    def __init__(self, path: Path, flush_rows: int = 10, flush_interval_s: float = 5.0):
        self._path = path
        self._flush_rows = flush_rows
        self._flush_interval_s = flush_interval_s
        self._fp: TextIOWrapper | None = None
        self._writer: csv.DictWriter | None = None
        self._field_list: list[str] | None = None
        self._pending: int = 0
        self._last_flush_ts: float = 0.0
        self._header_checked: bool = False

    def write(self, row: dict[str, object], fieldnames: Iterable[str]) -> None:
        field_list = list(fieldnames)
        if self._fp is None or self._field_list != field_list:
            self._open(field_list)
        if self._writer is None:
            return
        self._writer.writerow(row)
        self._pending += 1
        now = time.monotonic()
        if self._pending >= self._flush_rows or (now - self._last_flush_ts) >= self._flush_interval_s:
            self._do_flush(now)

    def flush(self) -> None:
        if self._fp is not None and self._pending > 0:
            self._do_flush(time.monotonic())

    def close(self) -> None:
        self.flush()
        if self._fp is not None:
            try:
                self._fp.close()
            except OSError:
                pass
            self._fp = None
            self._writer = None

    def _open(self, field_list: list[str]) -> None:
        self.close()
        self._field_list = field_list
        write_header = not self._path.exists() or self._path.stat().st_size == 0

        if not write_header and not self._header_checked:
            try:
                with self._path.open("r", encoding="utf-8") as existing:
                    first_line = existing.readline().strip()
                expected = ",".join(field_list)
                if first_line != expected:
                    rotated = self._path.with_name(
                        f"{self._path.stem}.legacy_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}{self._path.suffix}"
                    )
                    self._path.rename(rotated)
                    write_header = True
            except OSError:
                pass
            self._header_checked = True

        fp = None
        try:
            fp = self._path.open("a", newline="", encoding="utf-8")
            writer = csv.DictWriter(fp, fieldnames=field_list, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            self._fp = fp
            self._writer = writer
            self._last_flush_ts = time.monotonic()
            fp = None  # ownership transferred to self
        except Exception:
            logger.error("Failed to open CSV %s for writing", self._path, exc_info=True)
            self._fp = None
            self._writer = None
        finally:
            if fp is not None:
                try:
                    fp.close()
                except OSError:
                    pass

    def _do_flush(self, now: float) -> None:
        if self._fp is not None:
            try:
                self._fp.flush()
            except Exception:
                logger.warning("CSV flush failed for %s", self._path, exc_info=True)
        self._pending = 0
        self._last_flush_ts = now


class _BackgroundCsvWriter:
    """Wraps a ``_CsvBuffer`` with a queue + daemon thread for non-blocking writes.

    The caller's ``write()`` never touches disk; it just enqueues a shallow
    copy of the row dict.  A single daemon thread drains the queue and
    forwards rows to the underlying ``_CsvBuffer``.

    ``flush()`` and ``close()`` are blocking — they drain the queue before
    returning so that shutdown is clean.
    """

    _SENTINEL = object()

    def __init__(self, inner: _CsvBuffer, maxsize: int = 2000):
        self._inner = inner
        self._q: queue.Queue[tuple[dict[str, object], list[str] | None]] | None = queue.Queue(maxsize=maxsize)
        self._thread = threading.Thread(target=self._worker, daemon=True, name=f"csv_bg_{inner._path.stem}")
        self._thread.start()

    def write(self, row: dict[str, object], fieldnames: Iterable[str]) -> None:
        try:
            self._q.put_nowait((dict(row), list(fieldnames)))
        except queue.Full:
            logger.warning("CSV background queue full for %s — dropping row", self._inner._path)

    def flush(self) -> None:
        self._drain()
        self._inner.flush()

    def close(self) -> None:
        self._drain()
        self._inner.close()

    def _drain(self) -> None:
        while not self._q.empty():
            try:
                item = self._q.get_nowait()
                if item[0] is not None and item[1] is not None:
                    self._inner.write(item[0], item[1])
            except queue.Empty:
                break

    def _worker(self) -> None:
        while True:
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            if item[0] is None:
                break
            try:
                self._inner.write(item[0], item[1])  # type: ignore[arg-type]
            except Exception:
                logger.warning("CSV background write failed for %s", self._inner._path, exc_info=True)


class _FillWal:
    """Write-ahead log for fill events — atomic append, replay on startup.

    Each fill is appended as a single JSON line to ``fills.wal``.  On startup
    the CsvSplitLogger replays any WAL entries into the CSV, then truncates
    the WAL.  This ensures no fill data is lost even on a mid-flush crash.
    """

    def __init__(self, wal_path: Path, csv_buffer: _CsvBuffer, fill_fields: Iterable[str]):
        self._path = wal_path
        self._csv_buffer = csv_buffer
        self._fields = list(fill_fields)
        self._fp: TextIOWrapper | None = None
        self._replay_on_init()

    def append(self, row: dict[str, object]) -> None:
        try:
            try:
                import orjson as _orjson
                line = _orjson.dumps(row, default=str).decode() + "\n"
            except ImportError:
                import json as _json_wal
                line = _json_wal.dumps(row, default=str) + "\n"
            if self._fp is None:
                self._fp = self._path.open("a", encoding="utf-8")
            self._fp.write(line)
            self._fp.flush()
        except Exception:
            logger.warning("Fill WAL append failed", exc_info=True)
            if self._fp is not None:
                try:
                    self._fp.close()
                except OSError:
                    pass
            self._fp = None

    def mark_flushed(self) -> None:
        """Truncate WAL after CSV has been flushed."""
        try:
            if self._fp is not None:
                self._fp.close()
                self._fp = None
            self._path.write_text("", encoding="utf-8")
        except OSError:
            pass

    def close(self) -> None:
        if self._fp is not None:
            try:
                self._fp.close()
            except OSError:
                pass
            self._fp = None

    def _replay_on_init(self) -> None:
        if not self._path.exists() or self._path.stat().st_size == 0:
            return
        try:
            import orjson as _orjson
        except ImportError:
            import json as _orjson  # type: ignore[assignment]

        # Build a set of order_ids already committed to the CSV so WAL
        # replay after a crash-before-truncate does not produce duplicates.
        existing_keys: set[str] = set()
        csv_path = self._csv_buffer._path
        try:
            if csv_path.exists() and csv_path.stat().st_size > 0:
                import csv as _csv
                with csv_path.open("r", encoding="utf-8", newline="") as cf:
                    reader = _csv.DictReader(cf)
                    for csv_row in reader:
                        order_id = str(csv_row.get("order_id", "") or "").strip()
                        ts = str(csv_row.get("ts", "") or "").strip()
                        if order_id:
                            existing_keys.add(f"{order_id}|{ts}")
        except Exception:
            logger.warning("Fill WAL: could not read existing CSV for dedup — replaying all WAL entries", exc_info=True)

        replayed = 0
        skipped = 0
        try:
            with self._path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = _orjson.loads(line)
                    order_id = str(row.get("order_id", "") or "").strip()
                    ts = str(row.get("ts", "") or "").strip()
                    key = f"{order_id}|{ts}"
                    if key in existing_keys:
                        skipped += 1
                        continue
                    self._csv_buffer.write(row, self._fields)
                    existing_keys.add(key)
                    replayed += 1
            self._csv_buffer.flush()
            self._path.write_text("", encoding="utf-8")
            if replayed or skipped:
                logger.info("Fill WAL replayed %d entries into CSV (%d duplicates skipped)", replayed, skipped)
        except Exception:
            logger.warning("Fill WAL replay failed", exc_info=True)


class CsvSplitLogger:
    FILL_FIELDS = (
        "ts",
        "bot_variant",
        "exchange",
        "trading_pair",
        "side",
        "price",
        "amount_base",
        "notional_quote",
        "fee_quote",
        "order_id",
        "exchange_trade_id",
        "state",
        "regime",
        "alpha_policy_state",
        "alpha_policy_reason",
        "mid_ref",
        "expected_spread_pct",
        "adverse_drift_30s",
        "fee_source",
        "is_maker",
        "realized_pnl_quote",
    )

    def __init__(
        self,
        base_log_dir: str,
        instance_name: str,
        variant: str,
        namespace: str = "epp_v24",
        flush_rows: int = 10,
        flush_interval_s: float = 5.0,
    ):
        root = Path(base_log_dir).expanduser().resolve()
        namespace_tag = str(namespace or "epp_v24").strip().replace("\\", "_").replace("/", "_")
        if not namespace_tag:
            namespace_tag = "epp_v24"
        self.log_dir = root / namespace_tag / f"{instance_name}_{variant.lower()}"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._raw_buffers: dict[str, _CsvBuffer] = {}
        self._buffers: dict[str, _CsvBuffer | _BackgroundCsvWriter] = {}
        paths = {
            "fills": self.log_dir / "fills.csv",
            "minute": self.log_dir / "minute.csv",
            "daily": self.log_dir / "daily.csv",
        }
        for key, path in paths.items():
            buf = _CsvBuffer(path, flush_rows=flush_rows, flush_interval_s=flush_interval_s)
            self._raw_buffers[key] = buf
            if key in ("minute", "daily"):
                self._buffers[key] = _BackgroundCsvWriter(buf)
            else:
                self._buffers[key] = buf
        self._fill_wal = _FillWal(
            wal_path=self.log_dir / "fills.wal",
            csv_buffer=self._raw_buffers["fills"],
            fill_fields=self.FILL_FIELDS,
        )
        self._size_check_counter: int = 0
        self._size_warned: dict[str, bool] = {}

    def flush_all(self) -> None:
        for buf in self._buffers.values():
            buf.flush()
        self._fill_wal.mark_flushed()

    def close_all(self) -> None:
        for buf in self._buffers.values():
            buf.close()
        self._fill_wal.mark_flushed()
        self._fill_wal.close()

    _FILE_SIZE_WARN_MB: float = float(os.environ.get("CSV_SIZE_WARN_MB", "100"))
    _FILE_SIZE_CHECK_INTERVAL: int = 60

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat()

    def _append(self, key: str, row: dict[str, object], fieldnames: Iterable[str]) -> None:
        self._buffers[key].write(row, fieldnames)
        self._check_file_size_warning(key)

    def _check_file_size_warning(self, key: str) -> None:
        self._size_check_counter += 1
        if self._size_check_counter % self._FILE_SIZE_CHECK_INTERVAL != 0:
            return
        buf = self._raw_buffers.get(key)
        if buf is None:
            return
        try:
            size_mb = buf._path.stat().st_size / (1024 * 1024)
            if size_mb >= self._FILE_SIZE_WARN_MB and not self._size_warned.get(key):
                logger.warning(
                    "CSV file %s is %.1f MB — consider running artifact-retention",
                    buf._path, size_mb,
                )
                self._size_warned[key] = True
        except OSError:
            pass

    def log_fill(self, data: dict[str, object], ts: str | None = None) -> None:
        row = {"ts": ts or self._now_iso(), **data}
        self._fill_wal.append(row)
        self._append("fills", row, self.FILL_FIELDS)

    _MINUTE_CORE_FIELDS: tuple[str, ...] = (
        "ts",
        "bot_variant",
        "bot_mode",
        "accounting_source",
        "exchange",
        "trading_pair",
        "state",
        "regime",
        "mid",
        "equity_quote",
        "base_pct",
        "target_base_pct",
        "net_base_pct",
        "target_net_base_pct",
        "spread_pct",
        "spread_floor_pct",
        "base_spread_pct",
        "spread_competitiveness_cap_active",
        "spread_competitiveness_cap_side_pct",
        "net_edge_pct",
        "net_edge_gate_pct",
        "net_edge_ewma_pct",
        "adaptive_effective_min_edge_pct",
        "adaptive_fill_age_s",
        "adaptive_market_spread_bps_ewma",
        "adaptive_band_pct_ewma",
        "adaptive_market_floor_pct",
        "adaptive_vol_ratio",
        "pnl_governor_active",
        "pnl_governor_day_progress",
        "pnl_governor_target_pnl_pct",
        "pnl_governor_target_pnl_quote",
        "pnl_governor_expected_pnl_quote",
        "pnl_governor_actual_pnl_quote",
        "pnl_governor_deficit_ratio",
        "pnl_governor_edge_relax_bps",
        "pnl_governor_size_mult",
        "pnl_governor_size_boost_active",
        "pnl_governor_target_mode",
        "pnl_governor_target_source",
        "pnl_governor_target_equity_open_quote",
        "pnl_governor_target_effective_pct",
        "pnl_governor_size_mult_applied",
        "pnl_governor_activation_reason",
        "pnl_governor_size_boost_reason",
        "pnl_governor_activation_reason_counts",
        "pnl_governor_size_boost_reason_counts",
        "skew",
        "reservation_price_adjustment_pct",
        "inventory_urgency_pct",
        "inventory_skew_pct",
        "alpha_skew_pct",
        "adverse_drift_30s",
        "adverse_drift_smooth_30s",
        "drift_spread_mult",
        "soft_pause_edge",
        "selective_quote_state",
        "selective_quote_score",
        "selective_quote_reason",
        "selective_quote_adverse_ratio",
        "selective_quote_slippage_p95_bps",
        "alpha_policy_state",
        "alpha_policy_reason",
        "alpha_maker_score",
        "alpha_aggressive_score",
        "alpha_cross_allowed",
        "quote_side_mode",
        "quote_side_reason",
        "base_balance",
        "quote_balance",
        "market_spread_pct",
        "market_spread_bps",
        "best_bid_price",
        "best_ask_price",
        "best_bid_size",
        "best_ask_size",
        "turnover_today_x",
        "projected_total_quote",
        "cancel_per_min",
        "orders_active",
        "fills_count_today",
        "fees_paid_today_quote",
        "daily_loss_pct",
        "drawdown_pct",
        "edge_pause_threshold_pct",
        "edge_resume_threshold_pct",
        "risk_reasons",
        "min_base_pct",
        "max_base_pct",
        "max_total_notional_quote",
        "max_daily_turnover_x_hard",
        "max_daily_loss_pct_hard",
        "max_drawdown_pct_hard",
        "margin_ratio_soft_pause_pct",
        "margin_ratio_hard_stop_pct",
        "position_drift_soft_pause_pct",
        "fee_source",
        "maker_fee_pct",
        "taker_fee_pct",
        "realized_pnl_today_quote",
        "net_realized_pnl_today_quote",
        "position_base",
        "avg_entry_price",
        "funding_rate",
        "funding_cost_today_quote",
        "margin_ratio",
        "position_drift_pct",
    )

    _MINUTE_TAIL_FIELDS: tuple[str, ...] = (
        "ws_reconnect_count",
        "order_book_stale",
        "derisk_runtime_recovered",
        "derisk_runtime_recovery_count",
        "_tick_duration_ms",
        "_indicator_duration_ms",
        "_connector_io_duration_ms",
    )

    def log_minute(
        self,
        data: dict[str, object],
        ts: str | None = None,
        strategy_fields: tuple[str, ...] = (),
    ) -> None:
        row = {"ts": ts or self._now_iso(), **data}
        fields = self._MINUTE_CORE_FIELDS + strategy_fields + self._MINUTE_TAIL_FIELDS
        self._append("minute", row, fields)

    def log_daily(self, data: dict[str, object], ts: str | None = None) -> None:
        row = {"ts": ts or self._now_iso(), **data}
        fields = (
            "ts",
            "bot_variant",
            "exchange",
            "trading_pair",
            "state",
            "equity_open_quote",
            "equity_peak_quote",
            "equity_now_quote",
            "pnl_quote",
            "pnl_pct",
            "drawdown_pct",
            "max_drawdown_pct",
            "max_drawdown_peak_ts",
            "max_drawdown_trough_ts",
            "turnover_x",
            "fills_count",
            "fees_paid_today_quote",
            "funding_cost_today_quote",
            "realized_pnl_today_quote",
            "net_realized_pnl_today_quote",
            "ops_events",
        )
        self._append("daily", row, fields)
