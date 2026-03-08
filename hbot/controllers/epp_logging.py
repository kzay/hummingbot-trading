"""Buffered CSV split logger for strategy runtime controllers.

Keeps file handles open and buffers rows, flushing periodically or when a
buffer size threshold is reached.  Schema rotation (header mismatch) is
checked only on first open, not on every write.

Historical note: module filename is retained for backward compatibility.
Prefer importing from ``controllers.strategy_runtime_logging``.
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
            # Never let extra fields crash the trading loop. When schemas evolve,
            # we rotate the file on header mismatch, but be defensive in case a
            # caller passes a superset dict (e.g. processed_data) to a narrower
            # field list.
            self._writer = csv.DictWriter(self._fp, fieldnames=field_list, extrasaction="ignore")
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
        self._replay_on_init()

    def append(self, row: Dict[str, object]) -> None:
        try:
            import json as _json
            line = _json.dumps(row, default=str) + "\n"
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
        except Exception:
            logger.warning("Fill WAL append failed", exc_info=True)

    def mark_flushed(self) -> None:
        """Truncate WAL after CSV has been flushed."""
        try:
            self._path.write_text("", encoding="utf-8")
        except Exception:
            pass

    def _replay_on_init(self) -> None:
        if not self._path.exists() or self._path.stat().st_size == 0:
            return
        import json as _json
        replayed = 0
        try:
            with self._path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = _json.loads(line)
                    self._csv_buffer.write(row, self._fields)
                    replayed += 1
            self._csv_buffer.flush()
            self._path.write_text("", encoding="utf-8")
            if replayed:
                logger.info("Fill WAL replayed %d entries into CSV", replayed)
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
        self._buffers: Dict[str, _CsvBuffer] = {}
        paths = {
            "fills": self.log_dir / "fills.csv",
            "minute": self.log_dir / "minute.csv",
            "daily": self.log_dir / "daily.csv",
        }
        for key, path in paths.items():
            self._buffers[key] = _CsvBuffer(path, flush_rows=flush_rows, flush_interval_s=flush_interval_s)
        self._fill_wal = _FillWal(
            wal_path=self.log_dir / "fills.wal",
            csv_buffer=self._buffers["fills"],
            fill_fields=self.FILL_FIELDS,
        )

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
        self._fill_wal.append(row)
        self._append("fills", row, self.FILL_FIELDS)
        self._buffers["fills"].flush()
        self._fill_wal.mark_flushed()

    def log_minute(self, data: Dict[str, object], ts: Optional[str] = None) -> None:
        row = {"ts": ts or self._now_iso(), **data}
        fields = (
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
            "bot6_signal_side",
            "bot6_signal_reason",
            "bot6_signal_score_long",
            "bot6_signal_score_short",
            "bot6_signal_score_active",
            "bot6_sma_fast",
            "bot6_sma_slow",
            "bot6_adx",
            "bot6_funding_bias",
            "bot6_futures_cvd",
            "bot6_spot_cvd",
            "bot6_cvd_divergence_ratio",
            "bot6_stacked_buy_count",
            "bot6_stacked_sell_count",
            "bot6_delta_spike_ratio",
            "bot6_hedge_state",
            "bot6_partial_exit_ratio",
            "ws_reconnect_count",
            "order_book_stale",
            "derisk_runtime_recovered",
            "derisk_runtime_recovery_count",
            "_tick_duration_ms",
            "_indicator_duration_ms",
            "_connector_io_duration_ms",
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
