"""Buffered CSV split logger for EPP v2.4.

Keeps file handles open and buffers rows, flushing periodically or when a
buffer size threshold is reached.  Schema rotation (header mismatch) is
checked only on first open, not on every write.
"""
from __future__ import annotations

import csv
import logging
import time
from datetime import datetime, timezone
from io import TextIOWrapper
from pathlib import Path
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


class _CsvBuffer:
    """Manages one open CSV file with write buffering."""

    def __init__(self, path: Path, flush_rows: int = 10, flush_interval_s: float = 5.0):
        self._path = path
        self._flush_rows = flush_rows
        self._flush_interval_s = flush_interval_s
        self._fp: Optional[TextIOWrapper] = None
        self._writer: Optional[csv.DictWriter] = None
        self._field_list: Optional[List[str]] = None
        self._pending: int = 0
        self._last_flush_ts: float = 0.0
        self._header_checked: bool = False

    def write(self, row: Dict[str, object], fieldnames: Iterable[str]) -> None:
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
            except Exception:
                pass
            self._fp = None
            self._writer = None

    def _open(self, field_list: List[str]) -> None:
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
                        f"{self._path.stem}.legacy_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}{self._path.suffix}"
                    )
                    self._path.rename(rotated)
                    write_header = True
            except Exception:
                pass
            self._header_checked = True

        try:
            self._fp = self._path.open("a", newline="", encoding="utf-8")
            self._writer = csv.DictWriter(self._fp, fieldnames=field_list)
            if write_header:
                self._writer.writeheader()
            self._last_flush_ts = time.monotonic()
        except Exception:
            logger.error("Failed to open CSV %s for writing", self._path, exc_info=True)
            self._fp = None
            self._writer = None

    def _do_flush(self, now: float) -> None:
        if self._fp is not None:
            try:
                self._fp.flush()
            except Exception:
                logger.warning("CSV flush failed for %s", self._path, exc_info=True)
        self._pending = 0
        self._last_flush_ts = now


class CsvSplitLogger:
    def __init__(
        self,
        base_log_dir: str,
        instance_name: str,
        variant: str,
        flush_rows: int = 10,
        flush_interval_s: float = 5.0,
    ):
        root = Path(base_log_dir).expanduser().resolve()
        self.log_dir = root / "epp_v24" / f"{instance_name}_{variant.lower()}"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._buffers: Dict[str, _CsvBuffer] = {}
        paths = {
            "fills": self.log_dir / "fills.csv",
            "minute": self.log_dir / "minute.csv",
            "daily": self.log_dir / "daily.csv",
        }
        for key, path in paths.items():
            self._buffers[key] = _CsvBuffer(path, flush_rows=flush_rows, flush_interval_s=flush_interval_s)

    def flush_all(self) -> None:
        for buf in self._buffers.values():
            buf.flush()

    def close_all(self) -> None:
        for buf in self._buffers.values():
            buf.close()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _append(self, key: str, row: Dict[str, object], fieldnames: Iterable[str]) -> None:
        self._buffers[key].write(row, fieldnames)

    def log_fill(self, data: Dict[str, object], ts: Optional[str] = None) -> None:
        row = {"ts": ts or self._now_iso(), **data}
        fields = (
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
            "state",
            "mid_ref",
            "expected_spread_pct",
            "adverse_drift_30s",
            "fee_source",
            "is_maker",
            "realized_pnl_quote",
        )
        self._append("fills", row, fields)

    def log_minute(self, data: Dict[str, object], ts: Optional[str] = None) -> None:
        row = {"ts": ts or self._now_iso(), **data}
        fields = (
            "ts",
            "bot_variant",
            "exchange",
            "trading_pair",
            "state",
            "regime",
            "mid",
            "equity_quote",
            "base_pct",
            "target_base_pct",
            "spread_pct",
            "spread_floor_pct",
            "net_edge_pct",
            "skew",
            "adverse_drift_30s",
            "soft_pause_edge",
            "base_balance",
            "quote_balance",
            "market_spread_pct",
            "market_spread_bps",
            "best_bid_size",
            "best_ask_size",
            "turnover_today_x",
            "cancel_per_min",
            "orders_active",
            "fills_count_today",
            "fees_paid_today_quote",
            "daily_loss_pct",
            "drawdown_pct",
            "risk_reasons",
            "fee_source",
            "maker_fee_pct",
            "taker_fee_pct",
        )
        self._append("minute", row, fields)

    def log_daily(self, data: Dict[str, object], ts: Optional[str] = None) -> None:
        row = {"ts": ts or self._now_iso(), **data}
        fields = (
            "ts",
            "bot_variant",
            "exchange",
            "trading_pair",
            "state",
            "equity_open_quote",
            "equity_now_quote",
            "pnl_quote",
            "pnl_pct",
            "turnover_x",
            "fills_count",
            "ops_events",
        )
        self._append("daily", row, fields)
