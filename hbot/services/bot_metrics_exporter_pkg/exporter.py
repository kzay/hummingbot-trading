from __future__ import annotations

import csv
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from platform_lib.logging.log_namespace import iter_bot_log_files
from platform_lib.core.utils import env_int as _env_int
from platform_lib.core.utils import parse_iso_ts
from platform_lib.core.utils import safe_float as _safe_float

from services.bot_metrics_exporter_pkg.models import (
    BotSnapshot,
    FillStats,
    FillsFileSummary,
    MinuteFileScan,
    MinuteHistoryStats,
    OpenOrderSnapshot,
    PortfolioSnapshot,
    PositionSnapshot,
)
from services.bot_metrics_exporter_pkg.formatters import (
    _escape_label,
    _fmt_labels,
    _headroom_ratio,
    _median,
    _percentile,
    _safe_iso_ts_to_epoch,
    _split_reasons,
)

_LOGGER = logging.getLogger(__name__)

_DEFAULT_MIN_BASE_PCT = 0.15
_DEFAULT_MAX_BASE_PCT = 0.90
_DEFAULT_MAX_TOTAL_NOTIONAL_QUOTE = 1000.0
_DEFAULT_MAX_DAILY_TURNOVER_X_HARD = 6.0
_DEFAULT_MAX_DAILY_LOSS_PCT_HARD = 0.03
_DEFAULT_MAX_DRAWDOWN_PCT_HARD = 0.05
_DEFAULT_MARGIN_RATIO_SOFT_PAUSE_PCT = 0.20
_DEFAULT_MARGIN_RATIO_HARD_STOP_PCT = 0.10
_DEFAULT_POSITION_DRIFT_SOFT_PAUSE_PCT = 0.05

_HARD_GATE_REASONS = {
    "daily_turnover_hard_limit",
    "daily_loss_hard_limit",
    "drawdown_hard_limit",
    "margin_ratio_critical",
    "cancel_fail_hard_limit",
}
_DERISK_WATCHDOG_REASONS = {
    "base_pct_above_max",
    "base_pct_below_min",
    "eod_close_pending",
    "derisk_only",
    "derisk_force_taker",
    "derisk_hard_stop_flatten",
}


class BotMetricsExporter:
    def __init__(
        self,
        data_root: Path,
        log_tail_lines: int = 200,
        cache_ttl_seconds: int = 10,
    ):
        self._data_root = data_root
        self._log_tail_lines = log_tail_lines
        self._cache_ttl_seconds = max(1, int(cache_ttl_seconds))
        self._render_lock = threading.Lock()
        self._last_render_cache = ""
        self._last_render_monotonic = 0.0
        self._file_result_cache: dict[tuple[str, str], tuple[int, int, Any]] = {}
        self._render_requests_total = 0
        self._render_cache_hits_total = 0
        self._stale_cache_fallback_total = 0
        self._render_failures_total = 0
        self._render_duration_last_ms = 0.0
        self._render_duration_samples_ms: list[float] = []
        self._source_read_failures_total: dict[str, int] = {}
        self._redis_clients: dict[str, object] = {}

    def register_redis_client(self, name: str, client: object) -> None:
        """Register a RedisStreamClient (or any object with a .health() method) for metrics collection."""
        self._redis_clients[name] = client

    def _collect_redis_health(self) -> dict[str, dict]:
        results: dict[str, dict] = {}
        for name, client in self._redis_clients.items():
            health_fn = getattr(client, "health", None)
            if callable(health_fn):
                try:
                    results[name] = health_fn()
                except Exception:
                    pass
        return results

    def _record_source_read_failure(self, source: str) -> None:
        key = str(source or "unknown").strip() or "unknown"
        self._source_read_failures_total[key] = self._source_read_failures_total.get(key, 0) + 1

    def _record_render_duration(self, duration_ms: float) -> None:
        self._render_duration_last_ms = max(0.0, float(duration_ms))
        self._render_duration_samples_ms.append(self._render_duration_last_ms)
        if len(self._render_duration_samples_ms) > 50:
            self._render_duration_samples_ms = self._render_duration_samples_ms[-50:]

    def _cached_file_result(self, namespace: str, path: Path, loader: Callable[[], Any]) -> Any:
        key = (namespace, str(path))
        try:
            stat = path.stat()
            signature = (int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            return loader()
        cached = self._file_result_cache.get(key)
        if cached is not None and cached[0] == signature[0] and cached[1] == signature[1]:
            return cached[2]
        value = loader()
        self._file_result_cache[key] = (signature[0], signature[1], value)
        return value

    def _cached_fill_stats(self, fills_path: Path) -> FillStats:
        return self._cached_file_result("fill_stats", fills_path, lambda: self._compute_fill_stats(fills_path))

    def _cached_minute_history(self, minute_file: Path) -> MinuteHistoryStats | None:
        return self._cached_file_result("minute_history", minute_file, lambda: self._compute_minute_history(minute_file))

    def _cached_minute_file_scan(self, minute_file: Path) -> MinuteFileScan:
        return self._cached_file_result("minute_file_scan", minute_file, lambda: self._scan_minute_file(minute_file))

    def _cached_fills_summary(self, fills_path: Path, limit: int = 50) -> FillsFileSummary:
        safe_limit = max(1, int(limit))
        return self._cached_file_result(
            f"fills_summary_{safe_limit}",
            fills_path,
            lambda: self._scan_fills_file(fills_path, recent_limit=safe_limit),
        )

    def _exporter_self_metric_value_lines(self) -> list[str]:
        cache_hit_ratio = (
            float(self._render_cache_hits_total) / float(self._render_requests_total)
            if self._render_requests_total > 0
            else 0.0
        )
        lines = [
            f"hbot_exporter_render_requests_total {float(self._render_requests_total)}",
            f"hbot_exporter_render_cache_hits_total {float(self._render_cache_hits_total)}",
            f"hbot_exporter_render_cache_hit_ratio {cache_hit_ratio:.6f}",
            f"hbot_exporter_stale_cache_fallback_total {float(self._stale_cache_fallback_total)}",
            f"hbot_exporter_render_failures_total {float(self._render_failures_total)}",
            f"hbot_exporter_render_duration_last_ms {float(self._render_duration_last_ms):.3f}",
            f"hbot_exporter_render_duration_p50_ms {_percentile(self._render_duration_samples_ms, 0.50):.3f}",
            f"hbot_exporter_render_duration_p95_ms {_percentile(self._render_duration_samples_ms, 0.95):.3f}",
            f"hbot_exporter_render_duration_p99_ms {_percentile(self._render_duration_samples_ms, 0.99):.3f}",
        ]
        for source, count in sorted(self._source_read_failures_total.items()):
            lines.append(
                f'hbot_exporter_source_read_failures_total{{source="{_escape_label(source)}"}} {float(count)}'
            )
        return lines

    def _with_live_exporter_metrics(self, payload: str) -> str:
        exporter_value_prefixes = (
            "hbot_exporter_render_requests_total ",
            "hbot_exporter_render_cache_hits_total ",
            "hbot_exporter_render_cache_hit_ratio ",
            "hbot_exporter_stale_cache_fallback_total ",
            "hbot_exporter_render_failures_total ",
            "hbot_exporter_render_duration_last_ms ",
            "hbot_exporter_render_duration_p50_ms ",
            "hbot_exporter_render_duration_p95_ms ",
            "hbot_exporter_render_duration_p99_ms ",
            "hbot_exporter_source_read_failures_total{",
        )
        filtered = [
            line for line in str(payload or "").splitlines()
            if not any(line.startswith(prefix) for prefix in exporter_value_prefixes)
        ]
        return "\n".join(self._exporter_self_metric_value_lines() + filtered) + "\n"

    def collect(self) -> list[BotSnapshot]:
        snapshots: list[BotSnapshot] = []
        try:
            minute_files = list(iter_bot_log_files(self._data_root, "minute.csv"))
        except OSError:
            self._record_source_read_failure("minute_log_files")
            return snapshots
        for minute_file in minute_files:
            snapshot = self._collect_snapshot(minute_file)
            if snapshot is not None:
                snapshots.append(snapshot)
        return snapshots

    def _collect_snapshot(self, minute_file: Path) -> BotSnapshot | None:
        bot_name = minute_file.parts[-5]
        minute_scan = self._cached_minute_file_scan(minute_file)
        latest_minute = minute_scan.last_row
        if latest_minute is None:
            return None
        log_dir = minute_file.parent
        daily_state = self._read_daily_state_any(log_dir)
        bot_mode = str(latest_minute.get("bot_mode", "") or "").strip().lower() or "unknown"
        accounting_source = str(latest_minute.get("accounting_source", "") or "").strip().lower() or "minute_csv"
        fills_path = log_dir / "fills.csv"
        fills_summary = self._cached_fills_summary(fills_path, limit=50)
        fills_total = fills_summary.row_count
        fill_stats = fills_summary.fill_stats
        recent_error_lines = self._count_recent_error_lines(self._data_root / bot_name / "logs")
        portfolio = self._read_portfolio(log_dir / "paper_desk_v2.json")
        minute_history = self._cached_minute_history(minute_file)
        open_orders = self._read_open_orders(self._data_root / bot_name / "logs" / "recovery" / "open_orders_latest.json")
        recent_fills = fills_summary.recent_fills
        ts_epoch = _safe_iso_ts_to_epoch(str(latest_minute.get("ts", ""))) or 0.0
        equity_now = _safe_float(latest_minute.get("equity_quote"))
        equity_open = _safe_float(daily_state.get("equity_open")) if daily_state else 0.0
        daily_fills = _safe_float(daily_state.get("fills_count")) if daily_state else 0.0
        fills_today = _safe_float(latest_minute.get("fills_count_today"))
        if fills_today > 0:
            daily_fills = fills_today
        live_pnl = equity_now - equity_open if equity_open > 0 else 0.0
        realized_today = _safe_float(latest_minute.get("realized_pnl_today_quote"))
        funding_today = _safe_float(
            latest_minute.get("funding_cost_today_quote", latest_minute.get("funding_paid_today_quote"))
        )
        net_realized_today = _safe_float(
            latest_minute.get("net_realized_pnl_today_quote"),
            realized_today - funding_today,
        )
        return BotSnapshot(
            bot_name=bot_name,
            variant=str(latest_minute.get("bot_variant", "")),
            bot_mode=bot_mode,
            accounting_source=accounting_source if accounting_source else "minute_csv",
            exchange=str(latest_minute.get("exchange", "")),
            trading_pair=str(latest_minute.get("trading_pair", "")),
            state=str(latest_minute.get("state", "")),
            regime=str(latest_minute.get("regime", "")),
            ts_epoch=ts_epoch,
            net_edge_pct=_safe_float(latest_minute.get("net_edge_pct")),
            net_edge_gate_pct=_safe_float(latest_minute.get("net_edge_gate_pct")),
            spread_pct=_safe_float(latest_minute.get("spread_pct")),
            spread_floor_pct=_safe_float(latest_minute.get("spread_floor_pct")),
            market_spread_bps=_safe_float(latest_minute.get("market_spread_bps")),
            best_bid_price=_safe_float(latest_minute.get("best_bid_price")),
            best_ask_price=_safe_float(latest_minute.get("best_ask_price")),
            mid_price=_safe_float(latest_minute.get("mid")),
            best_bid_size=_safe_float(latest_minute.get("best_bid_size")),
            best_ask_size=_safe_float(latest_minute.get("best_ask_size")),
            book_imbalance=(
                (
                    _safe_float(latest_minute.get("best_bid_size")) - _safe_float(latest_minute.get("best_ask_size"))
                )
                / max(
                    _safe_float(latest_minute.get("best_bid_size")) + _safe_float(latest_minute.get("best_ask_size")),
                    1e-12,
                )
            ),
            turnover_today_x=_safe_float(latest_minute.get("turnover_today_x")),
            orders_active=_safe_float(latest_minute.get("orders_active")),
            maker_fee_pct=_safe_float(latest_minute.get("maker_fee_pct")),
            taker_fee_pct=_safe_float(latest_minute.get("taker_fee_pct")),
            soft_pause_edge=1.0 if str(latest_minute.get("soft_pause_edge", "")).lower() == "true" else 0.0,
            fee_source=str(latest_minute.get("fee_source", "")),
            equity_quote=equity_now,
            base_pct=_safe_float(latest_minute.get("base_pct")),
            target_base_pct=_safe_float(latest_minute.get("target_base_pct")),
            projected_total_quote=_safe_float(latest_minute.get("projected_total_quote")),
            daily_loss_pct=_safe_float(latest_minute.get("daily_loss_pct")),
            drawdown_pct=_safe_float(latest_minute.get("drawdown_pct")),
            edge_pause_threshold_pct=_safe_float(latest_minute.get("edge_pause_threshold_pct")),
            edge_resume_threshold_pct=_safe_float(latest_minute.get("edge_resume_threshold_pct")),
            min_base_pct=_safe_float(latest_minute.get("min_base_pct"), _DEFAULT_MIN_BASE_PCT),
            max_base_pct=_safe_float(latest_minute.get("max_base_pct"), _DEFAULT_MAX_BASE_PCT),
            max_total_notional_quote=_safe_float(
                latest_minute.get("max_total_notional_quote"), _DEFAULT_MAX_TOTAL_NOTIONAL_QUOTE
            ),
            max_daily_turnover_x_hard=_safe_float(
                latest_minute.get("max_daily_turnover_x_hard"), _DEFAULT_MAX_DAILY_TURNOVER_X_HARD
            ),
            max_daily_loss_pct_hard=_safe_float(
                latest_minute.get("max_daily_loss_pct_hard"), _DEFAULT_MAX_DAILY_LOSS_PCT_HARD
            ),
            max_drawdown_pct_hard=_safe_float(
                latest_minute.get("max_drawdown_pct_hard"), _DEFAULT_MAX_DRAWDOWN_PCT_HARD
            ),
            margin_ratio_soft_pause_pct=_safe_float(
                latest_minute.get("margin_ratio_soft_pause_pct"), _DEFAULT_MARGIN_RATIO_SOFT_PAUSE_PCT
            ),
            margin_ratio_hard_stop_pct=_safe_float(
                latest_minute.get("margin_ratio_hard_stop_pct"), _DEFAULT_MARGIN_RATIO_HARD_STOP_PCT
            ),
            position_drift_soft_pause_pct=_safe_float(
                latest_minute.get("position_drift_soft_pause_pct"), _DEFAULT_POSITION_DRIFT_SOFT_PAUSE_PCT
            ),
            cancel_per_min=_safe_float(latest_minute.get("cancel_per_min")),
            risk_reasons=str(latest_minute.get("risk_reasons", "")),
            daily_pnl_quote=live_pnl,
            daily_fills_count=daily_fills,
            fills_total=float(fills_total),
            recent_error_lines=float(recent_error_lines),
            tick_duration_ms=_safe_float(latest_minute.get("_tick_duration_ms")),
            indicator_duration_ms=_safe_float(latest_minute.get("_indicator_duration_ms")),
            connector_io_duration_ms=_safe_float(latest_minute.get("_connector_io_duration_ms")),
            position_drift_pct=_safe_float(latest_minute.get("position_drift_pct")),
            margin_ratio=_safe_float(latest_minute.get("margin_ratio"), 1.0),
            funding_rate=_safe_float(latest_minute.get("funding_rate")),
            funding_cost_today_quote=funding_today,
            realized_pnl_today_quote=realized_today,
            net_realized_pnl_today_quote=net_realized_today,
            ws_reconnect_count=_safe_float(latest_minute.get("ws_reconnect_count")),
            order_book_stale=1.0 if str(latest_minute.get("order_book_stale", "")).lower() == "true" else 0.0,
            history_seed_status=str(latest_minute.get("history_seed_status", "disabled") or "disabled"),
            history_seed_reason=str(latest_minute.get("history_seed_reason", "")),
            history_seed_source=str(latest_minute.get("history_seed_source", "")),
            history_seed_bars=_safe_float(latest_minute.get("history_seed_bars")),
            history_seed_latency_ms=_safe_float(latest_minute.get("history_seed_latency_ms")),
            derisk_runtime_recovered=1.0 if str(latest_minute.get("derisk_runtime_recovered", "")).lower() == "true" else 0.0,
            derisk_runtime_recovery_count=_safe_float(latest_minute.get("derisk_runtime_recovery_count")),
            pnl_governor_target_effective_pct=_safe_float(latest_minute.get("pnl_governor_target_effective_pct")),
            pnl_governor_size_mult_applied=_safe_float(latest_minute.get("pnl_governor_size_mult_applied"), 1.0),
            spread_competitiveness_cap_active=1.0 if str(latest_minute.get("spread_competitiveness_cap_active", "")).lower() == "true" else 0.0,
            spread_competitiveness_cap_side_pct=_safe_float(latest_minute.get("spread_competitiveness_cap_side_pct")),
            pnl_governor_target_mode=str(latest_minute.get("pnl_governor_target_mode", "disabled")),
            position_base=_safe_float(latest_minute.get("position_base")),
            position_gross_base=_safe_float(latest_minute.get("position_gross_base")),
            position_long_base=_safe_float(latest_minute.get("position_long_base")),
            position_short_base=_safe_float(latest_minute.get("position_short_base")),
            avg_entry_price=_safe_float(latest_minute.get("avg_entry_price")),
            avg_entry_price_long=_safe_float(latest_minute.get("avg_entry_price_long")),
            avg_entry_price_short=_safe_float(latest_minute.get("avg_entry_price_short")),
            bot1_signal_score=_safe_float(latest_minute.get("bot1_signal_score")),
            bot5_signal_score=_safe_float(latest_minute.get("bot5_signal_score")),
            bot6_signal_score=_safe_float(latest_minute.get("bot6_signal_score")),
            bot6_signal_score_active=_safe_float(latest_minute.get("bot6_signal_score_active")),
            bot6_cvd_divergence_ratio=_safe_float(latest_minute.get("bot6_cvd_divergence_ratio")),
            bot6_delta_spike_ratio=_safe_float(latest_minute.get("bot6_delta_spike_ratio")),
            bot7_signal_score=_safe_float(latest_minute.get("bot7_signal_score")),
            bot7_cvd=_safe_float(latest_minute.get("bot7_cvd")),
            bot7_grid_levels=_safe_float(latest_minute.get("bot7_grid_levels")),
            bot7_hedge_target_base_pct=_safe_float(latest_minute.get("bot7_hedge_target_base_pct")),
            fill_stats=fill_stats,
            portfolio=portfolio,
            minute_history=minute_history,
            derisk_stall_seconds=minute_history.derisk_stall_seconds if minute_history else 0.0,
            derisk_stall_active=minute_history.derisk_stall_active if minute_history else 0.0,
            minute_rows_total=float(minute_scan.row_count),
            minute_last_timestamp_seconds=ts_epoch,
            minute_last_age_seconds=max(0.0, datetime.now(UTC).timestamp() - ts_epoch) if ts_epoch > 0 else 1e9,
            fills_last_timestamp_seconds=fill_stats.last_fill_timestamp_seconds if fill_stats else 0.0,
            fills_last_age_seconds=(
                max(0.0, datetime.now(UTC).timestamp() - fill_stats.last_fill_timestamp_seconds)
                if fill_stats and fill_stats.last_fill_timestamp_seconds > 0
                else 1e9
            ),
            open_orders_total=float(len(open_orders)),
            open_orders_buy=float(sum(1 for o in open_orders if o.side == "BUY")),
            open_orders_sell=float(sum(1 for o in open_orders if o.side == "SELL")),
            open_orders=open_orders,
            recent_fills=recent_fills,
            order_failure_total=_safe_float(latest_minute.get("paper_reject_count")),
        )

    def render_prometheus(self) -> str:
        self._render_requests_total += 1
        now = time.monotonic()
        cache_is_fresh = (
            bool(self._last_render_cache)
            and (now - self._last_render_monotonic) <= self._cache_ttl_seconds
        )
        if cache_is_fresh:
            self._render_cache_hits_total += 1
            return self._with_live_exporter_metrics(self._last_render_cache)

        # Serve stale cache while another thread refreshes to avoid request pileups.
        if self._last_render_cache and not self._render_lock.acquire(blocking=False):
            self._render_cache_hits_total += 1
            self._stale_cache_fallback_total += 1
            return self._with_live_exporter_metrics(self._last_render_cache)
        if self._last_render_cache:
            try:
                return self._render_and_update_cache()
            finally:
                self._render_lock.release()

        # First request after startup should block until the first payload is ready.
        with self._render_lock:
            now = time.monotonic()
            cache_is_fresh = (
                bool(self._last_render_cache)
                and (now - self._last_render_monotonic) <= self._cache_ttl_seconds
            )
            if cache_is_fresh:
                self._render_cache_hits_total += 1
                return self._with_live_exporter_metrics(self._last_render_cache)
            return self._render_and_update_cache()

    def _render_and_update_cache(self) -> str:
        started = time.perf_counter()
        try:
            result = self._render_prometheus_impl()
            self._record_render_duration((time.perf_counter() - started) * 1000.0)
            self._last_render_cache = self._with_live_exporter_metrics(result)
            self._last_render_monotonic = time.monotonic()
            return self._last_render_cache
        except Exception:
            self._render_failures_total += 1
            self._record_render_duration((time.perf_counter() - started) * 1000.0)
            _LOGGER.exception("bot_metrics_exporter render failure; serving cached payload")
            if self._last_render_cache:
                self._stale_cache_fallback_total += 1
            return self._with_live_exporter_metrics(self._last_render_cache or "# hbot_exporter_error 1\n")

    def _render_prometheus_impl(self) -> str:
        now = datetime.now(UTC).timestamp()
        cluster_label = os.getenv("HB_CLUSTER", os.getenv("CLUSTER", "local"))
        environment_label = os.getenv("HB_ENVIRONMENT", os.getenv("ENVIRONMENT", "dev"))
        lines: list[str] = []
        lines.extend(
            [
                "# HELP hbot_exporter_render_requests_total Total exporter render requests.",
                "# TYPE hbot_exporter_render_requests_total counter",
                "# HELP hbot_exporter_render_cache_hits_total Exporter cache-hit responses, including stale-cache responses.",
                "# TYPE hbot_exporter_render_cache_hits_total counter",
                "# HELP hbot_exporter_render_cache_hit_ratio Ratio of cache-hit responses to total render requests.",
                "# TYPE hbot_exporter_render_cache_hit_ratio gauge",
                "# HELP hbot_exporter_stale_cache_fallback_total Exporter renders served from stale cache after a failed or contended refresh.",
                "# TYPE hbot_exporter_stale_cache_fallback_total counter",
                "# HELP hbot_exporter_render_failures_total Exporter render failures before cache fallback.",
                "# TYPE hbot_exporter_render_failures_total counter",
                "# HELP hbot_exporter_render_duration_last_ms Last exporter render duration in milliseconds.",
                "# TYPE hbot_exporter_render_duration_last_ms gauge",
                "# HELP hbot_exporter_render_duration_p50_ms Median exporter render duration in milliseconds.",
                "# TYPE hbot_exporter_render_duration_p50_ms gauge",
                "# HELP hbot_exporter_render_duration_p95_ms P95 exporter render duration in milliseconds.",
                "# TYPE hbot_exporter_render_duration_p95_ms gauge",
                "# HELP hbot_exporter_render_duration_p99_ms P99 exporter render duration in milliseconds.",
                "# TYPE hbot_exporter_render_duration_p99_ms gauge",
                "# HELP hbot_exporter_source_read_failures_total Non-fatal source read failures by source kind.",
                "# TYPE hbot_exporter_source_read_failures_total counter",
                "# HELP hbot_bot_snapshot_timestamp_seconds Latest bot snapshot timestamp from minute.csv.",
                "# TYPE hbot_bot_snapshot_timestamp_seconds gauge",
                "# HELP hbot_bot_snapshot_age_seconds Snapshot age in seconds.",
                "# TYPE hbot_bot_snapshot_age_seconds gauge",
                "# HELP hbot_bot_state Current bot state as a one-hot gauge.",
                "# TYPE hbot_bot_state gauge",
                "# HELP hbot_bot_net_edge_pct Net edge percentage from strategy minute snapshot.",
                "# TYPE hbot_bot_net_edge_pct gauge",
                "# HELP hbot_bot_net_edge_gate_pct Net edge value used by edge gate decision (may be smoothed).",
                "# TYPE hbot_bot_net_edge_gate_pct gauge",
                "# HELP hbot_bot_spread_pct Active spread percentage from minute snapshot.",
                "# TYPE hbot_bot_spread_pct gauge",
                "# HELP hbot_bot_spread_floor_pct Active spread floor percentage from minute snapshot.",
                "# TYPE hbot_bot_spread_floor_pct gauge",
                "# HELP hbot_bot_market_spread_bps Observed market spread in basis points from order book (minute snapshot).",
                "# TYPE hbot_bot_market_spread_bps gauge",
                "# HELP hbot_bot_best_bid_price Best bid price from order book (minute snapshot).",
                "# TYPE hbot_bot_best_bid_price gauge",
                "# HELP hbot_bot_best_ask_price Best ask price from order book (minute snapshot).",
                "# TYPE hbot_bot_best_ask_price gauge",
                "# HELP hbot_bot_mid_price Mid price from minute snapshot.",
                "# TYPE hbot_bot_mid_price gauge",
                "# HELP hbot_bot_best_bid_size Best bid size from minute snapshot.",
                "# TYPE hbot_bot_best_bid_size gauge",
                "# HELP hbot_bot_best_ask_size Best ask size from minute snapshot.",
                "# TYPE hbot_bot_best_ask_size gauge",
                "# HELP hbot_bot_book_imbalance Top-of-book size imbalance in [-1,1].",
                "# TYPE hbot_bot_book_imbalance gauge",
                "# HELP hbot_bot_turnover_today_x Daily turnover multiplier from minute snapshot.",
                "# TYPE hbot_bot_turnover_today_x gauge",
                "# HELP hbot_bot_orders_active Number of active orders in current minute snapshot.",
                "# TYPE hbot_bot_orders_active gauge",
                "# HELP hbot_bot_soft_pause_edge Whether edge gate is currently blocking execution (1=true).",
                "# TYPE hbot_bot_soft_pause_edge gauge",
                "# HELP hbot_bot_maker_fee_pct Effective maker fee percentage in decimal form.",
                "# TYPE hbot_bot_maker_fee_pct gauge",
                "# HELP hbot_bot_taker_fee_pct Effective taker fee percentage in decimal form.",
                "# TYPE hbot_bot_taker_fee_pct gauge",
                "# HELP hbot_bot_fee_source_info Fee source marker with source label.",
                "# TYPE hbot_bot_fee_source_info gauge",
                "# HELP hbot_bot_daily_pnl_quote Latest daily realized/unrealized pnl quote value.",
                "# TYPE hbot_bot_daily_pnl_quote gauge",
                "# HELP hbot_bot_daily_fills_count Latest daily fills count from daily.csv.",
                "# TYPE hbot_bot_daily_fills_count gauge",
                "# HELP hbot_bot_equity_quote Current equity quote from minute snapshot.",
                "# TYPE hbot_bot_equity_quote gauge",
                "# HELP hbot_bot_base_pct Current base allocation ratio from minute snapshot.",
                "# TYPE hbot_bot_base_pct gauge",
                "# HELP hbot_bot_target_base_pct Target base allocation ratio from minute snapshot.",
                "# TYPE hbot_bot_target_base_pct gauge",
                "# HELP hbot_bot_daily_loss_pct Current daily loss percentage from minute snapshot.",
                "# TYPE hbot_bot_daily_loss_pct gauge",
                "# HELP hbot_bot_drawdown_pct Current drawdown percentage from minute snapshot.",
                "# TYPE hbot_bot_drawdown_pct gauge",
                "# HELP hbot_bot_cancel_per_min Current cancel-per-minute rate from minute snapshot.",
                "# TYPE hbot_bot_cancel_per_min gauge",
                "# HELP hbot_bot_risk_reasons_info Risk reasons info marker with reason label.",
                "# TYPE hbot_bot_risk_reasons_info gauge",
                "# HELP hbot_bot_gate_active_total Count of currently active gate reasons.",
                "# TYPE hbot_bot_gate_active_total gauge",
                "# HELP hbot_bot_gate_active_hard_total Count of active hard-stop gate reasons.",
                "# TYPE hbot_bot_gate_active_hard_total gauge",
                "# HELP hbot_bot_gate_active_soft_total Count of active soft/operational gate reasons.",
                "# TYPE hbot_bot_gate_active_soft_total gauge",
                "# HELP hbot_bot_gate_reason_active Active gate reason marker with reason and severity labels.",
                "# TYPE hbot_bot_gate_reason_active gauge",
                "# HELP hbot_bot_gate_current_value Current value used in gate headroom calculation by gate label.",
                "# TYPE hbot_bot_gate_current_value gauge",
                "# HELP hbot_bot_gate_threshold_value Threshold value used in gate headroom calculation by gate label.",
                "# TYPE hbot_bot_gate_threshold_value gauge",
                "# HELP hbot_bot_gate_headroom_ratio Normalized gate headroom ratio by gate label; negative means breached.",
                "# TYPE hbot_bot_gate_headroom_ratio gauge",
                "# HELP hbot_bot_order_failure_total Paper engine order rejections since startup.",
                "# TYPE hbot_bot_order_failure_total gauge",
                "# HELP hbot_bot_fills_total Total fills rows observed in fills.csv.",
                "# TYPE hbot_bot_fills_total gauge",
                "# HELP hbot_bot_recent_error_lines Number of ERROR lines in recent bot log tail.",
                "# TYPE hbot_bot_recent_error_lines gauge",
                "# HELP hbot_bot_position_base Current position size in base asset (signed: >0 long, <0 short).",
                "# TYPE hbot_bot_position_base gauge",
                "# HELP hbot_bot_position_gross_base Gross open position size in base asset (long + short legs).",
                "# TYPE hbot_bot_position_gross_base gauge",
                "# HELP hbot_bot_position_long_base Open long-leg base size.",
                "# TYPE hbot_bot_position_long_base gauge",
                "# HELP hbot_bot_position_short_base Open short-leg base size.",
                "# TYPE hbot_bot_position_short_base gauge",
                "# HELP hbot_bot_avg_entry_price Average entry price of the current position.",
                "# TYPE hbot_bot_avg_entry_price gauge",
                "# HELP hbot_bot_avg_entry_price_long Average entry price of the long leg.",
                "# TYPE hbot_bot_avg_entry_price_long gauge",
                "# HELP hbot_bot_avg_entry_price_short Average entry price of the short leg.",
                "# TYPE hbot_bot_avg_entry_price_short gauge",
                "# HELP hbot_bot1_signal_score Bot1 baseline strategy signal score.",
                "# TYPE hbot_bot1_signal_score gauge",
                "# HELP hbot_bot5_signal_score Bot5 flow-conviction strategy signal score.",
                "# TYPE hbot_bot5_signal_score gauge",
                "# HELP hbot_bot6_signal_score Bot6 directional strategy signal score.",
                "# TYPE hbot_bot6_signal_score gauge",
                "# HELP hbot_bot7_cvd Bot7 cumulative volume delta from recent public trades.",
                "# TYPE hbot_bot7_cvd gauge",
                "# HELP hbot_bot7_signal_score Bot7 adaptive-grid strategy signal score.",
                "# TYPE hbot_bot7_signal_score gauge",
                "# HELP hbot_bot7_grid_levels Active bot7 grid-leg count target.",
                "# TYPE hbot_bot7_grid_levels gauge",
                "# HELP hbot_bot7_hedge_target_base_pct Bot7 hedge target as pct of equity/base budget.",
                "# TYPE hbot_bot7_hedge_target_base_pct gauge",
                "# HELP hbot_bot6_signal_score_active Bot6 active directional signal score.",
                "# TYPE hbot_bot6_signal_score_active gauge",
                "# HELP hbot_bot6_cvd_divergence_ratio Bot6 spot-vs-futures CVD divergence ratio.",
                "# TYPE hbot_bot6_cvd_divergence_ratio gauge",
                "# HELP hbot_bot6_delta_spike_ratio Bot6 liquidation-like delta spike ratio.",
                "# TYPE hbot_bot6_delta_spike_ratio gauge",
                "# HELP hbot_bot_fill_slippage_bps_sum Cumulative sum of fill price vs mid_ref in bps (positive = worse execution).",
                "# TYPE hbot_bot_fill_slippage_bps_sum gauge",
                "# HELP hbot_bot_fill_slippage_bps_count Count of fills contributing to hbot_bot_fill_slippage_bps_sum.",
                "# TYPE hbot_bot_fill_slippage_bps_count gauge",
                "# HELP hbot_bot_expected_spread_bps_sum Cumulative sum of expected spread in bps from fills.csv.",
                "# TYPE hbot_bot_expected_spread_bps_sum gauge",
                "# HELP hbot_bot_expected_spread_bps_count Count of fills contributing to hbot_bot_expected_spread_bps_sum.",
                "# TYPE hbot_bot_expected_spread_bps_count gauge",
                "# HELP hbot_bot_adverse_drift_30s_bps_sum Cumulative sum of adverse_drift_30s in bps from fills.csv.",
                "# TYPE hbot_bot_adverse_drift_30s_bps_sum gauge",
                "# HELP hbot_bot_adverse_drift_30s_bps_count Count of fills contributing to hbot_bot_adverse_drift_30s_bps_sum.",
                "# TYPE hbot_bot_adverse_drift_30s_bps_count gauge",
                "# HELP hbot_bot_fee_bps_sum Cumulative sum of per-fill fee rate in bps (fee_quote/notional_quote*1e4).",
                "# TYPE hbot_bot_fee_bps_sum gauge",
                "# HELP hbot_bot_fee_bps_count Count of fills contributing to hbot_bot_fee_bps_sum.",
                "# TYPE hbot_bot_fee_bps_count gauge",
                # FreqText header / table metrics
                "# HELP hbot_bot_open_pnl_quote Sum of unrealized_pnl across all open positions (from paper_desk_v2.json).",
                "# TYPE hbot_bot_open_pnl_quote gauge",
                "# HELP hbot_bot_paper_margin_call_events_total Total paper margin call events observed by paper desk risk counters.",
                "# TYPE hbot_bot_paper_margin_call_events_total gauge",
                "# HELP hbot_bot_paper_liquidation_events_total Total paper liquidation event groups observed by paper desk risk counters.",
                "# TYPE hbot_bot_paper_liquidation_events_total gauge",
                "# HELP hbot_bot_paper_liquidation_actions_total Total paper liquidation actions observed by paper desk risk counters.",
                "# TYPE hbot_bot_paper_liquidation_actions_total gauge",
                "# HELP hbot_bot_paper_margin_level_info Margin level label exported from paper desk risk counters.",
                "# TYPE hbot_bot_paper_margin_level_info gauge",
                "# HELP hbot_bot_closed_pnl_quote_total Total realized PnL (sum realized_pnl_quote across fills.csv).",
                "# TYPE hbot_bot_closed_pnl_quote_total gauge",
                "# HELP hbot_bot_trades_total Total number of fills rows in fills.csv.",
                "# TYPE hbot_bot_trades_total gauge",
                "# HELP hbot_bot_trade_wins_total Number of fills with realized_pnl_quote > 0.",
                "# TYPE hbot_bot_trade_wins_total gauge",
                "# HELP hbot_bot_trade_losses_total Number of fills with realized_pnl_quote < 0.",
                "# TYPE hbot_bot_trade_losses_total gauge",
                "# HELP hbot_bot_trade_winrate Win rate fraction wins/(wins+losses) from fills.csv.",
                "# TYPE hbot_bot_trade_winrate gauge",
                "# HELP hbot_bot_trade_expectancy_quote Mean realized PnL per non-zero fill (quote).",
                "# TYPE hbot_bot_trade_expectancy_quote gauge",
                "# HELP hbot_bot_trade_expectancy_rate_quote avg_win*wr - avg_loss*(1-wr) from fills.csv (quote).",
                "# TYPE hbot_bot_trade_expectancy_rate_quote gauge",
                "# HELP hbot_bot_trade_median_win_quote Median positive realized PnL (quote).",
                "# TYPE hbot_bot_trade_median_win_quote gauge",
                "# HELP hbot_bot_trade_median_loss_quote Median negative realized PnL magnitude (quote, negative sign).",
                "# TYPE hbot_bot_trade_median_loss_quote gauge",
                "# HELP hbot_bot_first_fill_timestamp_seconds Unix epoch of the earliest fill in fills.csv.",
                "# TYPE hbot_bot_first_fill_timestamp_seconds gauge",
                # Equity start for cumulative profit chart
                "# HELP hbot_bot_equity_start_quote Equity quote from the first row in minute.csv.",
                "# TYPE hbot_bot_equity_start_quote gauge",
                # Weekly / monthly realized PnL (day-boundary aggregation of minute.csv history)
                "# HELP hbot_bot_realized_pnl_week_quote 7-day realized PnL via day-boundary aggregation of minute.csv.",
                "# TYPE hbot_bot_realized_pnl_week_quote gauge",
                "# HELP hbot_bot_realized_pnl_month_quote 30-day realized PnL via day-boundary aggregation of minute.csv.",
                "# TYPE hbot_bot_realized_pnl_month_quote gauge",
                "# HELP hbot_bot_minute_rows_total Total rows observed in minute.csv.",
                "# TYPE hbot_bot_minute_rows_total gauge",
                "# HELP hbot_bot_minute_last_timestamp_seconds Last timestamp observed in minute.csv (epoch seconds).",
                "# TYPE hbot_bot_minute_last_timestamp_seconds gauge",
                "# HELP hbot_bot_minute_last_age_seconds Age of latest minute.csv row in seconds.",
                "# TYPE hbot_bot_minute_last_age_seconds gauge",
                "# HELP hbot_bot_fills_last_timestamp_seconds Last timestamp observed in fills.csv (epoch seconds).",
                "# TYPE hbot_bot_fills_last_timestamp_seconds gauge",
                "# HELP hbot_bot_fills_last_age_seconds Age of latest fills.csv row in seconds.",
                "# TYPE hbot_bot_fills_last_age_seconds gauge",
                "# HELP hbot_bot_fills_24h_count Number of fills during trailing 24h from fills.csv.",
                "# TYPE hbot_bot_fills_24h_count gauge",
                "# HELP hbot_bot_realized_pnl_24h_quote Realized PnL during trailing 24h from fills.csv (quote).",
                "# TYPE hbot_bot_realized_pnl_24h_quote gauge",
                "# HELP hbot_bot_open_order_price Open order price by order_id and side.",
                "# TYPE hbot_bot_open_order_price gauge",
                "# HELP hbot_bot_open_order_amount_base Open order amount in base units by order_id and side.",
                "# TYPE hbot_bot_open_order_amount_base gauge",
                "# HELP hbot_bot_open_order_age_seconds Open order age in seconds by order_id and side.",
                "# TYPE hbot_bot_open_order_age_seconds gauge",
                "# HELP hbot_bot_open_orders_total Count of currently open orders from strategy snapshot.",
                "# TYPE hbot_bot_open_orders_total gauge",
                "# HELP hbot_bot_open_orders_buy Count of open buy orders from strategy snapshot.",
                "# TYPE hbot_bot_open_orders_buy gauge",
                "# HELP hbot_bot_open_orders_sell Count of open sell orders from strategy snapshot.",
                "# TYPE hbot_bot_open_orders_sell gauge",
                "# HELP hbot_bot_fills_5m_count Number of fills in trailing 5 minutes.",
                "# TYPE hbot_bot_fills_5m_count gauge",
                "# HELP hbot_bot_fills_1h_count Number of fills in trailing 1 hour.",
                "# TYPE hbot_bot_fills_1h_count gauge",
                "# HELP hbot_bot_realized_pnl_1h_quote Realized PnL in trailing 1 hour (quote).",
                "# TYPE hbot_bot_realized_pnl_1h_quote gauge",
                "# HELP hbot_bot_derisk_runtime_recovered Whether derisk sizing was auto-recovered this tick (1=true).",
                "# TYPE hbot_bot_derisk_runtime_recovered gauge",
                "# HELP hbot_bot_derisk_runtime_recovery_count Cumulative count of derisk runtime sizing recoveries.",
                "# TYPE hbot_bot_derisk_runtime_recovery_count gauge",
                "# HELP hbot_bot_derisk_stall_seconds Continuous seconds with unchanged non-zero position during derisk/hard-stop flatten context.",
                "# TYPE hbot_bot_derisk_stall_seconds gauge",
                "# HELP hbot_bot_derisk_stall_active 1 when derisk/hard-stop flatten context is active and position is unchanged.",
                "# TYPE hbot_bot_derisk_stall_active gauge",
                "# HELP hbot_bot_pnl_governor_target_effective_pct Effective daily pnl target as pct of opening equity.",
                "# TYPE hbot_bot_pnl_governor_target_effective_pct gauge",
                "# HELP hbot_bot_pnl_governor_size_mult_applied Runtime sizing multiplier applied after clamps.",
                "# TYPE hbot_bot_pnl_governor_size_mult_applied gauge",
                "# HELP hbot_bot_spread_competitiveness_cap_active Whether spread competitiveness cap clipped spreads (1=true).",
                "# TYPE hbot_bot_spread_competitiveness_cap_active gauge",
                "# HELP hbot_bot_spread_competitiveness_cap_side_pct Per-side spread cap used by competitiveness guard.",
                "# TYPE hbot_bot_spread_competitiveness_cap_side_pct gauge",
                "# HELP hbot_bot_pnl_governor_target_mode_info Info metric for governor target mode label.",
                "# TYPE hbot_bot_pnl_governor_target_mode_info gauge",
                "# HELP hbot_history_seed_status Startup history seed status as a one-hot gauge by status label.",
                "# TYPE hbot_history_seed_status gauge",
                "# HELP hbot_history_seed_bars_count Number of bars loaded by the latest startup history seed.",
                "# TYPE hbot_history_seed_bars_count gauge",
                "# HELP hbot_history_seed_latency_ms Latency in milliseconds for the latest startup history seed.",
                "# TYPE hbot_history_seed_latency_ms gauge",
                "# HELP hbot_history_seed_info Info metric for latest startup history seed source/reason.",
                "# TYPE hbot_history_seed_info gauge",
                # Per-position metrics (one series per instrument_id)
                "# HELP hbot_bot_position_quantity_base Signed position quantity in base asset (from paper_desk_v2.json).",
                "# TYPE hbot_bot_position_quantity_base gauge",
                "# HELP hbot_bot_position_avg_entry_price Average entry price for the position (quote).",
                "# TYPE hbot_bot_position_avg_entry_price gauge",
                "# HELP hbot_bot_position_unrealized_pnl_quote Unrealized PnL for the position (quote).",
                "# TYPE hbot_bot_position_unrealized_pnl_quote gauge",
                "# HELP hbot_bot_position_opened_at_seconds Unix epoch when the position was opened.",
                "# TYPE hbot_bot_position_opened_at_seconds gauge",
                "# HELP hbot_bot_position_total_fees_paid_quote Total fees paid on the position (quote).",
                "# TYPE hbot_bot_position_total_fees_paid_quote gauge",
                "# HELP hbot_bot_position_unrealized_pnl_pct Unrealized pnl as pct of stake for open positions.",
                "# TYPE hbot_bot_position_unrealized_pnl_pct gauge",
                "# HELP hbot_bot_position_duration_seconds Open position age in seconds.",
                "# TYPE hbot_bot_position_duration_seconds gauge",
                "# HELP hbot_bot_position_stop_pct Placeholder stop pct for open positions (0 when unavailable).",
                "# TYPE hbot_bot_position_stop_pct gauge",
                "# HELP hbot_bot_position_side_info Side marker for open positions with side label long/short.",
                "# TYPE hbot_bot_position_side_info gauge",
                "# HELP hbot_bot_closed_trade_profit_quote Recent closed trade profit in quote terms.",
                "# TYPE hbot_bot_closed_trade_profit_quote gauge",
                "# HELP hbot_bot_closed_trade_profit_pct Recent closed trade profit as pct of notional.",
                "# TYPE hbot_bot_closed_trade_profit_pct gauge",
                "# HELP hbot_bot_closed_trade_opened_at_seconds Recent closed trade opened-at placeholder timestamp (fill ts when open ts unavailable).",
                "# TYPE hbot_bot_closed_trade_opened_at_seconds gauge",
                "# HELP hbot_bot_closed_trade_duration_seconds Recent closed trade duration in seconds (0 when unavailable).",
                "# TYPE hbot_bot_closed_trade_duration_seconds gauge",
                "# HELP hbot_bot_closed_trade_info Recent closed trade info marker with trade labels.",
                "# TYPE hbot_bot_closed_trade_info gauge",
                "# HELP hbot_csv_file_size_bytes Size of CSV log file in bytes.",
                "# TYPE hbot_csv_file_size_bytes gauge",
                "# HELP hbot_redis_client_connected Whether the Redis client is currently connected.",
                "# TYPE hbot_redis_client_connected gauge",
                "# HELP hbot_redis_client_reconnect_attempts_total Total reconnect attempts.",
                "# TYPE hbot_redis_client_reconnect_attempts_total counter",
                "# HELP hbot_redis_client_reconnect_successes_total Total successful reconnects.",
                "# TYPE hbot_redis_client_reconnect_successes_total counter",
                "# HELP hbot_redis_client_connection_errors_total Total connection errors.",
                "# TYPE hbot_redis_client_connection_errors_total counter",
                "# HELP hbot_redis_client_uptime_seconds Seconds since current connection was established.",
                "# TYPE hbot_redis_client_uptime_seconds gauge",
                "# HELP hbot_redis_io_latency_p50_ms Redis I/O latency p50 in milliseconds.",
                "# TYPE hbot_redis_io_latency_p50_ms gauge",
                "# HELP hbot_redis_io_latency_p99_ms Redis I/O latency p99 in milliseconds.",
                "# TYPE hbot_redis_io_latency_p99_ms gauge",
                "# HELP hbot_redis_io_timeout_count Total I/O timeouts.",
                "# TYPE hbot_redis_io_timeout_count counter",
            ]
        )
        self._append_exporter_self_metrics(lines)
        for snapshot in self.collect():
            base_labels = {
                "bot": snapshot.bot_name,
                "variant": snapshot.variant,
                "mode": snapshot.bot_mode,
                "accounting": snapshot.accounting_source,
                "exchange": snapshot.exchange,
                "pair": snapshot.trading_pair,
                "regime": snapshot.regime,
                "cluster": cluster_label,
                "environment": environment_label,
            }
            lines.append(f"hbot_bot_snapshot_timestamp_seconds{_fmt_labels(base_labels)} {snapshot.ts_epoch}")
            lines.append(f"hbot_bot_snapshot_age_seconds{_fmt_labels(base_labels)} {max(0.0, now - snapshot.ts_epoch)}")
            for state in ("running", "soft_pause", "hard_stop"):
                state_labels = dict(base_labels)
                state_labels["state"] = state
                state_value = 1.0 if snapshot.state == state else 0.0
                lines.append(f"hbot_bot_state{_fmt_labels(state_labels)} {state_value}")
            lines.append(f"hbot_bot_net_edge_pct{_fmt_labels(base_labels)} {snapshot.net_edge_pct}")
            lines.append(f"hbot_bot_net_edge_gate_pct{_fmt_labels(base_labels)} {snapshot.net_edge_gate_pct}")
            lines.append(f"hbot_bot_spread_pct{_fmt_labels(base_labels)} {snapshot.spread_pct}")
            lines.append(f"hbot_bot_spread_floor_pct{_fmt_labels(base_labels)} {snapshot.spread_floor_pct}")
            lines.append(f"hbot_bot_market_spread_bps{_fmt_labels(base_labels)} {snapshot.market_spread_bps}")
            lines.append(f"hbot_bot_best_bid_price{_fmt_labels(base_labels)} {snapshot.best_bid_price}")
            lines.append(f"hbot_bot_best_ask_price{_fmt_labels(base_labels)} {snapshot.best_ask_price}")
            lines.append(f"hbot_bot_mid_price{_fmt_labels(base_labels)} {snapshot.mid_price}")
            lines.append(f"hbot_bot_best_bid_size{_fmt_labels(base_labels)} {snapshot.best_bid_size}")
            lines.append(f"hbot_bot_best_ask_size{_fmt_labels(base_labels)} {snapshot.best_ask_size}")
            lines.append(f"hbot_bot_book_imbalance{_fmt_labels(base_labels)} {snapshot.book_imbalance}")
            lines.append(f"hbot_bot_turnover_today_x{_fmt_labels(base_labels)} {snapshot.turnover_today_x}")
            lines.append(f"hbot_bot_orders_active{_fmt_labels(base_labels)} {snapshot.orders_active}")
            lines.append(f"hbot_bot_soft_pause_edge{_fmt_labels(base_labels)} {snapshot.soft_pause_edge}")
            lines.append(f"hbot_bot_maker_fee_pct{_fmt_labels(base_labels)} {snapshot.maker_fee_pct}")
            lines.append(f"hbot_bot_taker_fee_pct{_fmt_labels(base_labels)} {snapshot.taker_fee_pct}")
            lines.append(f"hbot_bot_daily_pnl_quote{_fmt_labels(base_labels)} {snapshot.daily_pnl_quote}")
            lines.append(f"hbot_bot_daily_fills_count{_fmt_labels(base_labels)} {snapshot.daily_fills_count}")
            lines.append(f"hbot_bot_equity_quote{_fmt_labels(base_labels)} {snapshot.equity_quote}")
            lines.append(f"hbot_bot_base_pct{_fmt_labels(base_labels)} {snapshot.base_pct}")
            lines.append(f"hbot_bot_target_base_pct{_fmt_labels(base_labels)} {snapshot.target_base_pct}")
            lines.append(f"hbot_bot_daily_loss_pct{_fmt_labels(base_labels)} {snapshot.daily_loss_pct}")
            lines.append(f"hbot_bot_drawdown_pct{_fmt_labels(base_labels)} {snapshot.drawdown_pct}")
            lines.append(f"hbot_bot_cancel_per_min{_fmt_labels(base_labels)} {snapshot.cancel_per_min}")
            lines.append(f"hbot_bot_order_failure_total{_fmt_labels(base_labels)} {snapshot.order_failure_total}")
            lines.append(f"hbot_bot_fills_total{_fmt_labels(base_labels)} {snapshot.fills_total}")
            lines.append(f"hbot_bot_minute_rows_total{_fmt_labels(base_labels)} {snapshot.minute_rows_total}")
            lines.append(
                f"hbot_bot_minute_last_timestamp_seconds{_fmt_labels(base_labels)} {snapshot.minute_last_timestamp_seconds}"
            )
            lines.append(f"hbot_bot_minute_last_age_seconds{_fmt_labels(base_labels)} {snapshot.minute_last_age_seconds}")
            lines.append(
                f"hbot_bot_fills_last_timestamp_seconds{_fmt_labels(base_labels)} {snapshot.fills_last_timestamp_seconds}"
            )
            lines.append(f"hbot_bot_fills_last_age_seconds{_fmt_labels(base_labels)} {snapshot.fills_last_age_seconds}")
            lines.append(f"hbot_bot_recent_error_lines{_fmt_labels(base_labels)} {snapshot.recent_error_lines}")
            fee_labels = dict(base_labels)
            fee_labels["source"] = snapshot.fee_source or "unknown"
            lines.append(f"hbot_bot_fee_source_info{_fmt_labels(fee_labels)} 1")
            risk_labels = dict(base_labels)
            risk_labels["reasons"] = snapshot.risk_reasons or "none"
            lines.append(f"hbot_bot_risk_reasons_info{_fmt_labels(risk_labels)} 1")

            # Gate diagnostics exported as first-class Prometheus metrics.
            active_reasons = _split_reasons(snapshot.risk_reasons)
            if snapshot.soft_pause_edge >= 0.5 and "edge_gate_blocked" not in active_reasons:
                active_reasons.append("edge_gate_blocked")
            active_unique = sorted(set(active_reasons))
            hard_count = sum(1 for reason in active_unique if reason in _HARD_GATE_REASONS)
            active_total = len(active_unique)
            soft_count = max(0, active_total - hard_count)
            lines.append(f"hbot_bot_gate_active_total{_fmt_labels(base_labels)} {float(active_total)}")
            lines.append(f"hbot_bot_gate_active_hard_total{_fmt_labels(base_labels)} {float(hard_count)}")
            lines.append(f"hbot_bot_gate_active_soft_total{_fmt_labels(base_labels)} {float(soft_count)}")
            if active_unique:
                for reason in active_unique:
                    reason_labels = dict(base_labels)
                    reason_labels["reason"] = reason
                    reason_labels["severity"] = "hard" if reason in _HARD_GATE_REASONS else "soft"
                    lines.append(f"hbot_bot_gate_reason_active{_fmt_labels(reason_labels)} 1")
            else:
                reason_labels = dict(base_labels)
                reason_labels["reason"] = "none"
                reason_labels["severity"] = "none"
                lines.append(f"hbot_bot_gate_reason_active{_fmt_labels(reason_labels)} 1")

            gate_metrics = [
                ("daily_loss", snapshot.daily_loss_pct, snapshot.max_daily_loss_pct_hard, False),
                ("drawdown", snapshot.drawdown_pct, snapshot.max_drawdown_pct_hard, False),
                ("turnover", snapshot.turnover_today_x, snapshot.max_daily_turnover_x_hard, False),
                ("position_drift", snapshot.position_drift_pct, snapshot.position_drift_soft_pause_pct, False),
                ("margin_soft", snapshot.margin_ratio, snapshot.margin_ratio_soft_pause_pct, True),
                ("margin_hard", snapshot.margin_ratio, snapshot.margin_ratio_hard_stop_pct, True),
                ("base_min", snapshot.base_pct, snapshot.min_base_pct, True),
                ("base_max", snapshot.base_pct, snapshot.max_base_pct, False),
                ("notional_cap", snapshot.projected_total_quote, snapshot.max_total_notional_quote, False),
                ("edge_pause", snapshot.net_edge_gate_pct, snapshot.edge_pause_threshold_pct, True),
            ]
            for gate_name, current_value, threshold_value, lower_is_worse in gate_metrics:
                gate_labels = dict(base_labels)
                gate_labels["gate"] = gate_name
                headroom = _headroom_ratio(current_value, threshold_value, lower_is_worse)
                lines.append(f"hbot_bot_gate_current_value{_fmt_labels(gate_labels)} {current_value}")
                lines.append(f"hbot_bot_gate_threshold_value{_fmt_labels(gate_labels)} {threshold_value}")
                lines.append(f"hbot_bot_gate_headroom_ratio{_fmt_labels(gate_labels)} {headroom}")

            lines.append(f"hbot_bot_tick_duration_seconds{_fmt_labels(base_labels)} {snapshot.tick_duration_ms / 1000.0}")
            lines.append(f"hbot_bot_tick_indicator_seconds{_fmt_labels(base_labels)} {snapshot.indicator_duration_ms / 1000.0}")
            lines.append(f"hbot_bot_tick_connector_io_seconds{_fmt_labels(base_labels)} {snapshot.connector_io_duration_ms / 1000.0}")
            lines.append(f"hbot_bot_position_drift_pct{_fmt_labels(base_labels)} {snapshot.position_drift_pct}")
            lines.append(f"hbot_bot_margin_ratio{_fmt_labels(base_labels)} {snapshot.margin_ratio}")
            lines.append(f"hbot_bot_funding_rate{_fmt_labels(base_labels)} {snapshot.funding_rate}")
            lines.append(f"hbot_bot_realized_pnl_today_quote{_fmt_labels(base_labels)} {snapshot.realized_pnl_today_quote}")
            lines.append(
                f"hbot_bot_net_realized_pnl_today_quote{_fmt_labels(base_labels)} {snapshot.net_realized_pnl_today_quote}"
            )
            current_history_status = snapshot.history_seed_status or "disabled"
            for history_status in ("disabled", "fresh", "stale", "gapped", "degraded", "empty"):
                history_status_labels = dict(base_labels)
                history_status_labels["status"] = history_status
                history_status_value = 1.0 if current_history_status == history_status else 0.0
                lines.append(f"hbot_history_seed_status{_fmt_labels(history_status_labels)} {history_status_value}")
            lines.append(f"hbot_history_seed_bars_count{_fmt_labels(base_labels)} {snapshot.history_seed_bars}")
            lines.append(f"hbot_history_seed_latency_ms{_fmt_labels(base_labels)} {snapshot.history_seed_latency_ms}")
            history_info_labels = dict(base_labels)
            history_info_labels["status"] = current_history_status
            history_info_labels["source"] = snapshot.history_seed_source or "none"
            history_info_labels["reason"] = snapshot.history_seed_reason or "none"
            lines.append(f"hbot_history_seed_info{_fmt_labels(history_info_labels)} 1")
            lines.append(f"hbot_bot_ws_reconnect_total{_fmt_labels(base_labels)} {snapshot.ws_reconnect_count}")
            lines.append(f"hbot_bot_order_book_stale{_fmt_labels(base_labels)} {snapshot.order_book_stale}")
            lines.append(f"hbot_bot_derisk_runtime_recovered{_fmt_labels(base_labels)} {snapshot.derisk_runtime_recovered}")
            lines.append(f"hbot_bot_derisk_runtime_recovery_count{_fmt_labels(base_labels)} {snapshot.derisk_runtime_recovery_count}")
            lines.append(f"hbot_bot_derisk_stall_seconds{_fmt_labels(base_labels)} {snapshot.derisk_stall_seconds}")
            lines.append(f"hbot_bot_derisk_stall_active{_fmt_labels(base_labels)} {snapshot.derisk_stall_active}")
            lines.append(
                f"hbot_bot_pnl_governor_target_effective_pct{_fmt_labels(base_labels)} {snapshot.pnl_governor_target_effective_pct}"
            )
            lines.append(
                f"hbot_bot_pnl_governor_size_mult_applied{_fmt_labels(base_labels)} {snapshot.pnl_governor_size_mult_applied}"
            )
            lines.append(
                f"hbot_bot_spread_competitiveness_cap_active{_fmt_labels(base_labels)} {snapshot.spread_competitiveness_cap_active}"
            )
            lines.append(
                f"hbot_bot_spread_competitiveness_cap_side_pct{_fmt_labels(base_labels)} {snapshot.spread_competitiveness_cap_side_pct}"
            )
            target_mode_labels = dict(base_labels)
            target_mode_labels["target_mode"] = snapshot.pnl_governor_target_mode or "disabled"
            lines.append(f"hbot_bot_pnl_governor_target_mode_info{_fmt_labels(target_mode_labels)} 1")
            # Position metrics — always exported regardless of fill_stats
            lines.append(f"hbot_bot_position_base{_fmt_labels(base_labels)} {snapshot.position_base}")
            lines.append(f"hbot_bot_position_gross_base{_fmt_labels(base_labels)} {snapshot.position_gross_base}")
            lines.append(f"hbot_bot_position_long_base{_fmt_labels(base_labels)} {snapshot.position_long_base}")
            lines.append(f"hbot_bot_position_short_base{_fmt_labels(base_labels)} {snapshot.position_short_base}")
            lines.append(f"hbot_bot_avg_entry_price{_fmt_labels(base_labels)} {snapshot.avg_entry_price}")
            lines.append(f"hbot_bot_avg_entry_price_long{_fmt_labels(base_labels)} {snapshot.avg_entry_price_long}")
            lines.append(f"hbot_bot_avg_entry_price_short{_fmt_labels(base_labels)} {snapshot.avg_entry_price_short}")
            lines.append(f"hbot_bot1_signal_score{_fmt_labels(base_labels)} {snapshot.bot1_signal_score}")
            lines.append(f"hbot_bot5_signal_score{_fmt_labels(base_labels)} {snapshot.bot5_signal_score}")
            lines.append(f"hbot_bot6_signal_score{_fmt_labels(base_labels)} {snapshot.bot6_signal_score}")
            lines.append(
                f"hbot_bot6_signal_score_active{_fmt_labels(base_labels)} {snapshot.bot6_signal_score_active}"
            )
            lines.append(
                f"hbot_bot6_cvd_divergence_ratio{_fmt_labels(base_labels)} {snapshot.bot6_cvd_divergence_ratio}"
            )
            lines.append(
                f"hbot_bot6_delta_spike_ratio{_fmt_labels(base_labels)} {snapshot.bot6_delta_spike_ratio}"
            )
            lines.append(f"hbot_bot7_signal_score{_fmt_labels(base_labels)} {snapshot.bot7_signal_score}")
            lines.append(f"hbot_bot7_cvd{_fmt_labels(base_labels)} {snapshot.bot7_cvd}")
            lines.append(f"hbot_bot7_grid_levels{_fmt_labels(base_labels)} {snapshot.bot7_grid_levels}")
            lines.append(
                f"hbot_bot7_hedge_target_base_pct{_fmt_labels(base_labels)} {snapshot.bot7_hedge_target_base_pct}"
            )
            if snapshot.fill_stats:
                fs = snapshot.fill_stats
                lines.append(f"hbot_bot_fills_buy_count{_fmt_labels(base_labels)} {fs.buys}")
                lines.append(f"hbot_bot_fills_sell_count{_fmt_labels(base_labels)} {fs.sells}")
                lines.append(f"hbot_bot_fills_maker_count{_fmt_labels(base_labels)} {fs.maker_fills}")
                lines.append(f"hbot_bot_fills_taker_count{_fmt_labels(base_labels)} {fs.taker_fills}")
                lines.append(f"hbot_bot_buy_notional_quote{_fmt_labels(base_labels)} {fs.buy_notional}")
                lines.append(f"hbot_bot_sell_notional_quote{_fmt_labels(base_labels)} {fs.sell_notional}")
                lines.append(f"hbot_bot_total_fees_quote{_fmt_labels(base_labels)} {fs.total_fees}")
                lines.append(f"hbot_bot_avg_buy_price{_fmt_labels(base_labels)} {fs.avg_buy_price}")
                lines.append(f"hbot_bot_avg_sell_price{_fmt_labels(base_labels)} {fs.avg_sell_price}")
                lines.append(f"hbot_bot_fill_slippage_bps_sum{_fmt_labels(base_labels)} {fs.fill_slippage_bps_sum}")
                lines.append(f"hbot_bot_fill_slippage_bps_count{_fmt_labels(base_labels)} {float(fs.fill_slippage_bps_count)}")
                lines.append(f"hbot_bot_expected_spread_bps_sum{_fmt_labels(base_labels)} {fs.expected_spread_bps_sum}")
                lines.append(f"hbot_bot_expected_spread_bps_count{_fmt_labels(base_labels)} {float(fs.expected_spread_bps_count)}")
                lines.append(f"hbot_bot_adverse_drift_30s_bps_sum{_fmt_labels(base_labels)} {fs.adverse_drift_30s_bps_sum}")
                lines.append(f"hbot_bot_adverse_drift_30s_bps_count{_fmt_labels(base_labels)} {float(fs.adverse_drift_30s_bps_count)}")
                lines.append(f"hbot_bot_fee_bps_sum{_fmt_labels(base_labels)} {fs.fee_bps_sum}")
                lines.append(f"hbot_bot_fee_bps_count{_fmt_labels(base_labels)} {float(fs.fee_bps_count)}")
                # FreqText table metrics (from fill_stats extended fields)
                lines.append(f"hbot_bot_closed_pnl_quote_total{_fmt_labels(base_labels)} {fs.closed_pnl_total}")
                lines.append(f"hbot_bot_trades_total{_fmt_labels(base_labels)} {float(fs.trades_total)}")
                lines.append(f"hbot_bot_trade_wins_total{_fmt_labels(base_labels)} {float(fs.trade_wins_total)}")
                lines.append(f"hbot_bot_trade_losses_total{_fmt_labels(base_labels)} {float(fs.trade_losses_total)}")
                lines.append(f"hbot_bot_trade_winrate{_fmt_labels(base_labels)} {fs.trade_winrate}")
                lines.append(f"hbot_bot_trade_expectancy_quote{_fmt_labels(base_labels)} {fs.trade_expectancy_quote}")
                lines.append(f"hbot_bot_trade_expectancy_rate_quote{_fmt_labels(base_labels)} {fs.trade_expectancy_rate_quote}")
                lines.append(f"hbot_bot_trade_median_win_quote{_fmt_labels(base_labels)} {fs.trade_median_win_quote}")
                lines.append(f"hbot_bot_trade_median_loss_quote{_fmt_labels(base_labels)} {fs.trade_median_loss_quote}")
                lines.append(f"hbot_bot_first_fill_timestamp_seconds{_fmt_labels(base_labels)} {fs.first_fill_timestamp_seconds}")
                lines.append(f"hbot_bot_fills_24h_count{_fmt_labels(base_labels)} {float(fs.fills_24h_count)}")
                lines.append(f"hbot_bot_realized_pnl_24h_quote{_fmt_labels(base_labels)} {fs.realized_pnl_24h_quote}")
                lines.append(f"hbot_bot_fills_5m_count{_fmt_labels(base_labels)} {float(fs.fills_5m_count)}")
                lines.append(f"hbot_bot_fills_1h_count{_fmt_labels(base_labels)} {float(fs.fills_1h_count)}")
                lines.append(f"hbot_bot_realized_pnl_1h_quote{_fmt_labels(base_labels)} {fs.realized_pnl_1h_quote}")
            # Portfolio / open PnL metrics
            if snapshot.portfolio is not None:
                pf = snapshot.portfolio
                lines.append(f"hbot_bot_open_pnl_quote{_fmt_labels(base_labels)} {pf.open_pnl_quote}")
                lines.append(
                    f"hbot_bot_paper_margin_call_events_total{_fmt_labels(base_labels)} {pf.paper_margin_call_events_total}"
                )
                lines.append(
                    f"hbot_bot_paper_liquidation_events_total{_fmt_labels(base_labels)} {pf.paper_liquidation_events_total}"
                )
                lines.append(
                    f"hbot_bot_paper_liquidation_actions_total{_fmt_labels(base_labels)} {pf.paper_liquidation_actions_total}"
                )
                margin_level_labels = dict(base_labels)
                margin_level_labels["margin_level"] = pf.paper_margin_level or "unknown"
                lines.append(f"hbot_bot_paper_margin_level_info{_fmt_labels(margin_level_labels)} 1")
                for pos in pf.positions:
                    pos_labels = dict(base_labels)
                    pos_labels["instrument_id"] = pos.instrument_id
                    pos_labels["pair"] = pos.pair
                    stake_quote = abs(pos.quantity_base * pos.avg_entry_price)
                    pnl_pct = (pos.unrealized_pnl_quote / stake_quote) if stake_quote > 0 else 0.0
                    duration_s = max(0.0, now - pos.opened_at_seconds) if pos.opened_at_seconds > 0 else 0.0
                    side = "long" if pos.quantity_base >= 0 else "short"
                    lines.append(f"hbot_bot_position_quantity_base{_fmt_labels(pos_labels)} {pos.quantity_base}")
                    lines.append(f"hbot_bot_position_avg_entry_price{_fmt_labels(pos_labels)} {pos.avg_entry_price}")
                    lines.append(f"hbot_bot_position_unrealized_pnl_quote{_fmt_labels(pos_labels)} {pos.unrealized_pnl_quote}")
                    lines.append(f"hbot_bot_position_opened_at_seconds{_fmt_labels(pos_labels)} {pos.opened_at_seconds}")
                    lines.append(f"hbot_bot_position_total_fees_paid_quote{_fmt_labels(pos_labels)} {pos.total_fees_paid_quote}")
                    lines.append(f"hbot_bot_position_unrealized_pnl_pct{_fmt_labels(pos_labels)} {pnl_pct}")
                    lines.append(f"hbot_bot_position_duration_seconds{_fmt_labels(pos_labels)} {duration_s}")
                    lines.append(f"hbot_bot_position_stop_pct{_fmt_labels(pos_labels)} 0")
                    side_labels = dict(pos_labels)
                    side_labels["side"] = side
                    lines.append(f"hbot_bot_position_side_info{_fmt_labels(side_labels)} 1")
            else:
                lines.append(f"hbot_bot_open_pnl_quote{_fmt_labels(base_labels)} 0")
                lines.append(f"hbot_bot_paper_margin_call_events_total{_fmt_labels(base_labels)} 0")
                lines.append(f"hbot_bot_paper_liquidation_events_total{_fmt_labels(base_labels)} 0")
                lines.append(f"hbot_bot_paper_liquidation_actions_total{_fmt_labels(base_labels)} 0")
                margin_level_labels = dict(base_labels)
                margin_level_labels["margin_level"] = "unknown"
                lines.append(f"hbot_bot_paper_margin_level_info{_fmt_labels(margin_level_labels)} 1")
            # Minute history metrics (equity start + weekly/monthly PnL)
            if snapshot.minute_history is not None:
                mh = snapshot.minute_history
                lines.append(f"hbot_bot_equity_start_quote{_fmt_labels(base_labels)} {mh.equity_start_quote}")
                lines.append(f"hbot_bot_realized_pnl_week_quote{_fmt_labels(base_labels)} {mh.realized_pnl_week_quote}")
                lines.append(f"hbot_bot_realized_pnl_month_quote{_fmt_labels(base_labels)} {mh.realized_pnl_month_quote}")
            for order in snapshot.open_orders:
                order_labels = dict(base_labels)
                order_labels["order_id"] = order.order_id
                order_labels["side"] = order.side
                order_labels["pair"] = order.pair
                lines.append(f"hbot_bot_open_order_price{_fmt_labels(order_labels)} {order.price}")
                lines.append(f"hbot_bot_open_order_amount_base{_fmt_labels(order_labels)} {order.amount_base}")
                lines.append(f"hbot_bot_open_order_age_seconds{_fmt_labels(order_labels)} {order.age_sec}")
            lines.append(f"hbot_bot_open_orders_total{_fmt_labels(base_labels)} {snapshot.open_orders_total}")
            lines.append(f"hbot_bot_open_orders_buy{_fmt_labels(base_labels)} {snapshot.open_orders_buy}")
            lines.append(f"hbot_bot_open_orders_sell{_fmt_labels(base_labels)} {snapshot.open_orders_sell}")
            for i, fill in enumerate(snapshot.recent_fills):
                trade_id = str(fill.get("order_id", "")).strip() or f"fill_{i}"
                pair = str(snapshot.trading_pair)
                side = str(fill.get("side", "")).lower() or "unknown"
                close_ts = str(fill.get("ts", ""))
                close_epoch = _safe_iso_ts_to_epoch(close_ts) or 0.0
                pnl_quote = _safe_float(fill.get("pnl"))
                notional = _safe_float(fill.get("notional"))
                pnl_pct = (pnl_quote / notional) if notional > 0 else 0.0
                opened_at = close_epoch  # fill-level source has no true open timestamp
                duration_s = 0.0
                trade_labels = dict(base_labels)
                trade_labels["trade_id"] = trade_id
                trade_labels["pair"] = pair
                trade_labels["side"] = side
                trade_labels["close_ts"] = close_ts
                lines.append(f"hbot_bot_closed_trade_profit_quote{_fmt_labels(trade_labels)} {pnl_quote}")
                lines.append(f"hbot_bot_closed_trade_profit_pct{_fmt_labels(trade_labels)} {pnl_pct}")
                lines.append(f"hbot_bot_closed_trade_opened_at_seconds{_fmt_labels(trade_labels)} {opened_at}")
                lines.append(f"hbot_bot_closed_trade_duration_seconds{_fmt_labels(trade_labels)} {duration_s}")
                lines.append(f"hbot_bot_closed_trade_info{_fmt_labels(trade_labels)} 1")

        # ---------------------------------------------------------------------------
        # INFRA-5: Data plane consistency metrics from desk_snapshot_service
        # ---------------------------------------------------------------------------
        lines.extend([
            "# HELP hbot_desk_snapshot_age_seconds Age of the canonical desk snapshot in seconds.",
            "# TYPE hbot_desk_snapshot_age_seconds gauge",
            "# HELP hbot_desk_snapshot_completeness Fraction of required minute fields present (0-1).",
            "# TYPE hbot_desk_snapshot_completeness gauge",
            "# HELP hbot_desk_snapshot_minute_age_s Age of latest minute.csv tick as seen by snapshot service.",
            "# TYPE hbot_desk_snapshot_minute_age_s gauge",
            "# HELP hbot_desk_snapshot_fill_age_s Age of latest fill as seen by snapshot service.",
            "# TYPE hbot_desk_snapshot_fill_age_s gauge",
            "# HELP hbot_data_plane_consistency 1 if active bots have fresh snapshot+minute data, 0 otherwise.",
            "# TYPE hbot_data_plane_consistency gauge",
        ])
        try:
            snapshot_root = self._data_root.parent / "reports" / "desk_snapshot"
            all_fresh = True
            snapshot_count = 0
            for bot_dir in sorted(snapshot_root.iterdir()) if snapshot_root.exists() else []:
                if not bot_dir.is_dir():
                    continue
                snap_path = bot_dir / "latest.json"
                if not snap_path.exists():
                    all_fresh = False
                    continue
                try:
                    snap = json.loads(snap_path.read_text(encoding="utf-8"))
                except Exception:
                    all_fresh = False
                    continue
                bot_label = bot_dir.name
                bot_snap_labels = {"bot": bot_label}
                gen_ts = str(snap.get("generated_ts", ""))
                snap_age = 1e9
                try:
                    epoch = datetime.fromisoformat(gen_ts.replace("Z", "+00:00")).timestamp()
                    snap_age = now - epoch
                except Exception:
                    pass
                completeness = float(snap.get("completeness", 0.0))
                minute_age = snap.get("minute_age_s")
                fill_age = snap.get("fill_age_s")
                lines.append(f"hbot_desk_snapshot_age_seconds{_fmt_labels(bot_snap_labels)} {snap_age:.1f}")
                lines.append(f"hbot_desk_snapshot_completeness{_fmt_labels(bot_snap_labels)} {completeness:.3f}")
                if minute_age is not None:
                    lines.append(f"hbot_desk_snapshot_minute_age_s{_fmt_labels(bot_snap_labels)} {float(minute_age):.1f}")
                if fill_age is not None:
                    lines.append(f"hbot_desk_snapshot_fill_age_s{_fmt_labels(bot_snap_labels)} {float(fill_age):.1f}")
                _inactive_threshold_s = 6 * 3600
                _snapshot_stale_threshold_s = 180.0
                _minute_stale_threshold_s = 180.0
                _bot_inactive = minute_age is not None and float(minute_age) > _inactive_threshold_s
                _minute_stale = minute_age is None or float(minute_age) > _minute_stale_threshold_s
                if not _bot_inactive and (
                    snap_age > _snapshot_stale_threshold_s
                    or completeness < 0.8
                    or _minute_stale
                ):
                    all_fresh = False
                if not _bot_inactive:
                    snapshot_count += 1
            consistency = 1.0 if (snapshot_count > 0 and all_fresh) else 0.0
            lines.append(f"hbot_data_plane_consistency {consistency}")
        except Exception:
            lines.append("hbot_data_plane_consistency 0")

        try:
            for bot_dir in sorted(self._data_root.glob("bot*")):
                logs_dir = bot_dir / "logs"
                if not logs_dir.is_dir():
                    continue
                for csv_name in ("minute.csv", "fills.csv", "daily.csv"):
                    for csv_path in logs_dir.rglob(csv_name):
                        if csv_path.is_file():
                            size_bytes = csv_path.stat().st_size
                            csv_labels = {
                                "bot": bot_dir.name,
                                "file": csv_name,
                                "cluster": cluster_label,
                                "environment": environment_label,
                            }
                            lines.append(f"hbot_csv_file_size_bytes{_fmt_labels(csv_labels)} {size_bytes}")
        except Exception:
            pass

        try:
            redis_clients = self._collect_redis_health()
            for svc_name, h in redis_clients.items():
                rlabels = {"service": svc_name, "cluster": cluster_label, "environment": environment_label}
                rl = _fmt_labels(rlabels)
                lines.append(f"hbot_redis_client_connected{rl} {1 if h.get('connected') else 0}")
                lines.append(f"hbot_redis_client_reconnect_attempts_total{rl} {h.get('reconnect_attempts_total', 0)}")
                lines.append(f"hbot_redis_client_reconnect_successes_total{rl} {h.get('reconnect_successes_total', 0)}")
                lines.append(f"hbot_redis_client_connection_errors_total{rl} {h.get('connection_errors_total', 0)}")
                lines.append(f"hbot_redis_client_uptime_seconds{rl} {h.get('uptime_s', 0.0)}")
                lines.append(f"hbot_redis_io_latency_p50_ms{rl} {h.get('io_latency_p50_ms', 0.0)}")
                lines.append(f"hbot_redis_io_latency_p99_ms{rl} {h.get('io_latency_p99_ms', 0.0)}")
                lines.append(f"hbot_redis_io_timeout_count{rl} {h.get('io_timeout_count', 0)}")
        except Exception:
            pass

        return "\n".join(lines) + "\n"

    def _append_exporter_self_metrics(self, lines: list[str]) -> None:
        lines.extend(self._exporter_self_metric_value_lines())

    def _read_open_orders(self, snapshot_path: Path) -> list[OpenOrderSnapshot]:
        if not snapshot_path.exists():
            return []
        def _load() -> list[OpenOrderSnapshot]:
            try:
                payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
                orders_raw = payload.get("orders", [])
                if not isinstance(orders_raw, list):
                    return []
                out: list[OpenOrderSnapshot] = []
                for row in orders_raw:
                    if not isinstance(row, dict):
                        continue
                    order_id = str(row.get("order_id", "")).strip()
                    if not order_id:
                        continue
                    out.append(
                        OpenOrderSnapshot(
                            order_id=order_id,
                            side=str(row.get("side", "")).upper(),
                            pair=str(row.get("trading_pair", "")),
                            price=_safe_float(row.get("price")),
                            amount_base=_safe_float(row.get("amount")),
                            age_sec=_safe_float(row.get("age_sec")),
                        )
                    )
                return out
            except Exception:
                self._record_source_read_failure("open_orders")
                return []
        return self._cached_file_result("open_orders", snapshot_path, _load)

    def _read_portfolio(self, portfolio_path: Path) -> PortfolioSnapshot | None:
        """Read paper_desk_v2.json and return open position metrics."""
        if not portfolio_path.exists():
            return None
        def _load() -> PortfolioSnapshot | None:
            try:
                data = json.loads(portfolio_path.read_text(encoding="utf-8"))
                positions_raw = data.get("portfolio", {}).get("positions", {})
                risk_counters = data.get("risk_counters", {}) if isinstance(data.get("risk_counters"), dict) else {}
                total_unrealized = 0.0
                positions: list[PositionSnapshot] = []
                for key, pos in positions_raw.items():
                    if not isinstance(pos, dict):
                        continue
                    qty = _safe_float(pos.get("quantity"))
                    if qty == 0.0:
                        continue
                    unr = _safe_float(pos.get("unrealized_pnl"))
                    total_unrealized += unr
                    opened_ns = _safe_float(pos.get("opened_at_ns"))
                    opened_s = opened_ns / 1e9 if opened_ns > 0 else 0.0
                    parts = key.split(":")
                    pair = parts[1] if len(parts) >= 2 else key
                    positions.append(PositionSnapshot(
                        instrument_id=key,
                        pair=pair,
                        quantity_base=qty,
                        avg_entry_price=_safe_float(pos.get("avg_entry_price")),
                        unrealized_pnl_quote=unr,
                        opened_at_seconds=opened_s,
                        total_fees_paid_quote=_safe_float(pos.get("total_fees_paid")),
                    ))
                return PortfolioSnapshot(
                    open_pnl_quote=total_unrealized,
                    positions=positions,
                    paper_margin_call_events_total=float(risk_counters.get("margin_call_events_total", 0.0) or 0.0),
                    paper_liquidation_events_total=float(risk_counters.get("liquidation_events_total", 0.0) or 0.0),
                    paper_liquidation_actions_total=float(risk_counters.get("liquidation_actions_total", 0.0) or 0.0),
                    paper_margin_level=str(risk_counters.get("last_margin_level", "unknown") or "unknown").strip().lower(),
                )
            except Exception:
                self._record_source_read_failure("portfolio")
                return None
        return self._cached_file_result("portfolio", portfolio_path, _load)

    def _compute_minute_history(self, minute_file: Path) -> MinuteHistoryStats | None:
        """
        Scan all rows in minute.csv to compute:
        - equity_start_quote: equity_quote of the first row
        - realized_pnl_week_quote: 7-day day-boundary aggregation
        - realized_pnl_month_quote: 30-day day-boundary aggregation
        Matches DashboardData._pnl_since() and DashboardData.equity_series() logic.
        """
        if not minute_file.exists():
            return None
        try:
            rows: list[dict[str, str]] = []
            with minute_file.open("r", encoding="utf-8", newline="") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    rows.append(row)
            if not rows:
                return None

            equity_start = _safe_float(rows[0].get("equity_quote"))
            now_utc = datetime.now(UTC)

            def _pnl_since(days: int) -> float:
                cutoff = now_utc - timedelta(days=days)
                pnl = 0.0
                prev_date = None
                prev_pnl_today = 0.0
                for row in rows:
                    ts_str = row.get("ts", "")
                    dt = parse_iso_ts(ts_str)
                    if dt is None:
                        continue
                    if dt < cutoff:
                        continue
                    day = dt.date()
                    cur_pnl_today = _safe_float(row.get("realized_pnl_today_quote"))
                    if prev_date is not None and day != prev_date:
                        pnl += prev_pnl_today
                    prev_date = day
                    prev_pnl_today = cur_pnl_today
                pnl += prev_pnl_today
                return pnl

            derisk_stall_seconds = 0.0
            derisk_stall_active = 0.0
            latest_row = rows[-1]
            latest_dt = parse_iso_ts(latest_row.get("ts", ""))
            latest_position_base = _safe_float(latest_row.get("position_base"))
            latest_position_gross = _safe_float(latest_row.get("position_gross_base"), abs(latest_position_base))
            if latest_dt is not None and abs(latest_position_gross) > 1e-12:
                stall_start_dt = None
                for row in reversed(rows):
                    row_dt = parse_iso_ts(row.get("ts", ""))
                    if row_dt is None:
                        break
                    row_state = str(row.get("state", "")).strip().lower()
                    row_reasons = set(_split_reasons(str(row.get("risk_reasons", ""))))
                    row_position_base = _safe_float(row.get("position_base"))
                    row_position_gross = _safe_float(row.get("position_gross_base"), abs(row_position_base))
                    same_position = (
                        abs(row_position_base - latest_position_base) <= 1e-10
                        and abs(row_position_gross - latest_position_gross) <= 1e-10
                    )
                    # SOFT_PAUSE requires explicit derisk reason.
                    soft_pause_derisk = (
                        row_state == "soft_pause"
                        and bool(row_reasons.intersection(_DERISK_WATCHDOG_REASONS))
                    )
                    # HARD_STOP with non-zero position is treated as forced flatten context.
                    hard_stop_flatten = row_state == "hard_stop" and abs(row_position_gross) > 1e-12
                    if same_position and (soft_pause_derisk or hard_stop_flatten):
                        stall_start_dt = row_dt
                        continue
                    break
                if stall_start_dt is not None:
                    derisk_stall_seconds = max(0.0, (latest_dt - stall_start_dt).total_seconds())
                    derisk_stall_active = 1.0 if derisk_stall_seconds > 0 else 0.0

            return MinuteHistoryStats(
                equity_start_quote=equity_start,
                realized_pnl_week_quote=_pnl_since(7),
                realized_pnl_month_quote=_pnl_since(30),
                derisk_stall_seconds=derisk_stall_seconds,
                derisk_stall_active=derisk_stall_active,
            )
        except Exception:
            self._record_source_read_failure("minute_history")
            return None

    def _scan_minute_file(self, minute_file: Path) -> MinuteFileScan:
        scan = MinuteFileScan()
        if not minute_file.exists():
            return scan
        try:
            with minute_file.open("r", encoding="utf-8", newline="") as fp:
                reader = csv.DictReader(fp)
                last = None
                count = 0
                for row in reader:
                    last = row
                    count += 1
                scan.last_row = last
                scan.row_count = count
        except Exception:
            self._record_source_read_failure("minute_file_scan")
        return scan

    def _read_daily_state_any(self, log_dir: Path) -> dict[str, str] | None:
        """Read any daily_state*.json file (v1 or v2 naming convention)."""
        import json
        candidates = sorted(log_dir.glob("daily_state*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in candidates:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                self._record_source_read_failure("daily_state")
                continue
        return None


    def _read_last_csv_row(self, path: Path) -> dict[str, str] | None:
        if not path.exists():
            return None
        if path.name == "minute.csv":
            return self._cached_minute_file_scan(path).last_row
        def _load() -> dict[str, str] | None:
            try:
                with path.open("r", encoding="utf-8", newline="") as fp:
                    reader = csv.DictReader(fp)
                    last = None
                    for row in reader:
                        last = row
                    return last
            except Exception:
                self._record_source_read_failure("minute_last_row")
                return None
        return self._cached_file_result("last_csv_row", path, _load)

    def _scan_fills_file(self, fills_path: Path, recent_limit: int = 50) -> FillsFileSummary:
        summary = FillsFileSummary()
        if not fills_path.exists():
            return summary
        try:
            buy_prices, sell_prices = [], []
            pnl_values: list[float] = []
            recent_rows: list[dict[str, str]] = []
            first_ts_epoch: float = 0.0
            last_ts_epoch: float = 0.0
            cutoff_5m = datetime.now(UTC).timestamp() - (5 * 60)
            cutoff_1h = datetime.now(UTC).timestamp() - (60 * 60)
            cutoff_24h = datetime.now(UTC).timestamp() - (24 * 3600)
            safe_recent_limit = max(1, int(recent_limit))
            with fills_path.open("r", encoding="utf-8", newline="") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    summary.row_count += 1
                    side = str(row.get("side", "")).lower()
                    notional = _safe_float(row.get("notional_quote"))
                    fee = _safe_float(row.get("fee_quote"))
                    price = _safe_float(row.get("price"))
                    amount = _safe_float(row.get("amount_base"))
                    pnl = _safe_float(row.get("realized_pnl_quote"))
                    is_maker = str(row.get("is_maker", "")).lower() == "true"
                    mid_ref = _safe_float(row.get("mid_ref"))
                    expected_spread_pct = _safe_float(row.get("expected_spread_pct"))
                    adverse_drift_30s = _safe_float(row.get("adverse_drift_30s"))
                    ts_str = str(row.get("ts", ""))

                    stats = summary.fill_stats
                    stats.trades_total += 1
                    stats.total_fees += fee
                    stats.total_realized_pnl += pnl
                    pnl_values.append(pnl)

                    if first_ts_epoch == 0.0 and ts_str:
                        epoch = _safe_iso_ts_to_epoch(ts_str)
                        if epoch:
                            first_ts_epoch = epoch
                    if ts_str:
                        epoch = _safe_iso_ts_to_epoch(ts_str)
                        if epoch:
                            last_ts_epoch = max(last_ts_epoch, epoch)
                            if epoch >= cutoff_5m:
                                stats.fills_5m_count += 1
                            if epoch >= cutoff_1h:
                                stats.fills_1h_count += 1
                                stats.realized_pnl_1h_quote += pnl
                            if epoch >= cutoff_24h:
                                stats.fills_24h_count += 1
                                stats.realized_pnl_24h_quote += pnl

                    if is_maker:
                        stats.maker_fills += 1
                    else:
                        stats.taker_fills += 1
                    if side == "buy":
                        stats.buys += 1
                        stats.buy_notional += notional
                        buy_prices.append(price)
                    elif side == "sell":
                        stats.sells += 1
                        stats.sell_notional += notional
                        sell_prices.append(price)
                    stats.last_fill_ts = ts_str
                    stats.last_fill_side = side
                    stats.last_fill_price = price
                    stats.last_fill_amount = amount
                    stats.last_fill_pnl = pnl

                    if mid_ref > 0 and price > 0:
                        if side == "sell":
                            slippage_bps = ((mid_ref - price) / mid_ref) * 10000.0
                        else:
                            slippage_bps = ((price - mid_ref) / mid_ref) * 10000.0
                        stats.fill_slippage_bps_sum += slippage_bps
                        stats.fill_slippage_bps_count += 1

                    if expected_spread_pct != 0.0:
                        stats.expected_spread_bps_sum += expected_spread_pct * 10000.0
                        stats.expected_spread_bps_count += 1

                    if adverse_drift_30s != 0.0:
                        stats.adverse_drift_30s_bps_sum += adverse_drift_30s * 10000.0
                        stats.adverse_drift_30s_bps_count += 1

                    if notional > 0:
                        stats.fee_bps_sum += (fee / notional) * 10000.0
                        stats.fee_bps_count += 1

                    recent_rows.append(row)
                    if len(recent_rows) > safe_recent_limit:
                        recent_rows = recent_rows[-safe_recent_limit:]

            stats = summary.fill_stats
            if buy_prices:
                stats.avg_buy_price = sum(buy_prices) / len(buy_prices)
            if sell_prices:
                stats.avg_sell_price = sum(sell_prices) / len(sell_prices)

            stats.first_fill_timestamp_seconds = first_ts_epoch
            stats.last_fill_timestamp_seconds = last_ts_epoch
            stats.closed_pnl_total = sum(pnl_values)

            wins = [p for p in pnl_values if p > 0]
            losses = [p for p in pnl_values if p < 0]
            stats.trade_wins_total = len(wins)
            stats.trade_losses_total = len(losses)
            nonzero = wins + losses
            denom = len(wins) + len(losses)
            if denom > 0:
                stats.trade_winrate = len(wins) / denom
                stats.trade_expectancy_quote = sum(nonzero) / len(nonzero)
                avg_win = sum(wins) / len(wins) if wins else 0.0
                avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
                wr = stats.trade_winrate
                stats.trade_expectancy_rate_quote = avg_win * wr - avg_loss * (1 - wr)
            stats.trade_median_win_quote = _median(wins)
            stats.trade_median_loss_quote = _median(losses)

            recent_rows.reverse()
            summary.recent_fills = [
                {
                    "ts": row.get("ts", ""),
                    "side": row.get("side", ""),
                    "price": _safe_float(row.get("price")),
                    "amount": _safe_float(row.get("amount_base")),
                    "notional": _safe_float(row.get("notional_quote")),
                    "fee": _safe_float(row.get("fee_quote")),
                    "is_maker": str(row.get("is_maker", "")).lower() == "true",
                    "pnl": _safe_float(row.get("realized_pnl_quote")),
                    "order_id": row.get("order_id", ""),
                    "state": row.get("state", ""),
                    "spread_pct": _safe_float(row.get("expected_spread_pct")),
                }
                for row in recent_rows
            ]
        except Exception:
            self._record_source_read_failure("fills_summary")
        return summary

    def _compute_fill_stats(self, fills_path: Path) -> FillStats:
        return self._scan_fills_file(fills_path, recent_limit=1).fill_stats

    def _read_recent_fills(self, fills_path: Path, limit: int = 50) -> list[dict[str, object]]:
        if not fills_path.exists():
            return []
        safe_limit = max(1, int(limit))
        if safe_limit == 50:
            return list(self._cached_fills_summary(fills_path, limit=safe_limit).recent_fills)
        cache_key = f"recent_fills_{int(limit)}"
        def _load() -> list[dict[str, object]]:
            try:
                rows: list[dict[str, str]] = []
                with fills_path.open("r", encoding="utf-8", newline="") as fp:
                    reader = csv.DictReader(fp)
                    for row in reader:
                        rows.append(row)
                recent = rows[-limit:]
                recent.reverse()
                result = []
                for row in recent:
                    result.append({
                        "ts": row.get("ts", ""),
                        "side": row.get("side", ""),
                        "price": _safe_float(row.get("price")),
                        "amount": _safe_float(row.get("amount_base")),
                        "notional": _safe_float(row.get("notional_quote")),
                        "fee": _safe_float(row.get("fee_quote")),
                        "is_maker": str(row.get("is_maker", "")).lower() == "true",
                        "pnl": _safe_float(row.get("realized_pnl_quote")),
                        "order_id": row.get("order_id", ""),
                        "state": row.get("state", ""),
                        "spread_pct": _safe_float(row.get("expected_spread_pct")),
                    })
                return result
            except Exception:
                self._record_source_read_failure("recent_fills")
                return []
        return self._cached_file_result(cache_key, fills_path, _load)

    def _count_csv_rows(self, path: Path) -> int:
        if not path.exists():
            return 0
        if path.name == "minute.csv":
            return int(self._cached_minute_file_scan(path).row_count)
        if path.name == "fills.csv":
            return int(self._cached_fills_summary(path, limit=50).row_count)
        def _load() -> int:
            try:
                with path.open("r", encoding="utf-8", newline="") as fp:
                    reader = csv.reader(fp)
                    count = -1
                    for _ in reader:
                        count += 1
                    return max(0, count)
            except Exception:
                self._record_source_read_failure("csv_row_count")
                return 0
        return int(self._cached_file_result("csv_row_count", path, _load) or 0)

    def _count_recent_error_lines(self, bot_log_dir: Path) -> int:
        log_files = sorted(bot_log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not log_files:
            return 0
        target = log_files[0]
        try:
            size = target.stat().st_size
            avg_line_len = 200
            tail_bytes = self._log_tail_lines * avg_line_len
            with target.open("r", encoding="utf-8", errors="ignore") as fp:
                if size > tail_bytes:
                    fp.seek(max(0, size - tail_bytes))
                    fp.readline()
                lines = fp.readlines()
            tail = lines[-self._log_tail_lines:]
            return sum(1 for line in tail if "ERROR" in line)
        except Exception:
            self._record_source_read_failure("recent_error_lines")
            return 0


class MetricsHandler(BaseHTTPRequestHandler):
    exporter: BotMetricsExporter
    metrics_path: str = "/metrics"

    def _safe_write(self, body: bytes) -> None:
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_GET(self):
        import json as _json
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self._safe_write(b'{"status":"ok"}')
            return
        if self.path.startswith("/fills"):
            bot_filter = None
            if "?" in self.path:
                params = dict(p.split("=", 1) for p in self.path.split("?", 1)[1].split("&") if "=" in p)
                bot_filter = params.get("bot")
            limit = 50
            all_fills: list = []
            data_root = self.exporter._data_root
            for fills_file in iter_bot_log_files(data_root, "fills.csv"):
                bot_name = fills_file.parts[-5]
                if bot_filter and bot_name != bot_filter:
                    continue
                fills = self.exporter._read_recent_fills(fills_file, limit)
                for f in fills:
                    f["bot"] = bot_name
                all_fills.extend(fills)
            all_fills.sort(key=lambda x: x.get("ts", ""), reverse=True)
            all_fills = all_fills[:limit]
            body = _json.dumps(all_fills, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self._safe_write(body)
            return
        if self.path != self.metrics_path:
            self.send_response(404)
            self.end_headers()
            self._safe_write(b"not found")
            return
        body = self.exporter.render_prometheus().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self._safe_write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    data_root = Path(os.getenv("HB_DATA_ROOT", "/workspace/hbot/data")).resolve()
    port = _env_int("METRICS_PORT", 9400)
    metrics_path = os.getenv("METRICS_PATH", "/metrics")
    log_tail_lines = _env_int("EXPORTER_LOG_TAIL_LINES", 200)
    cache_ttl_seconds = _env_int("EXPORTER_CACHE_TTL_S", 10)

    exporter = BotMetricsExporter(
        data_root=data_root,
        log_tail_lines=log_tail_lines,
        cache_ttl_seconds=cache_ttl_seconds,
    )
    MetricsHandler.exporter = exporter
    MetricsHandler.metrics_path = metrics_path

    server = ThreadingHTTPServer(("0.0.0.0", port), MetricsHandler)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logger = logging.getLogger("bot_metrics_exporter")
    logger.info("listening on :%d%s, data_root=%s", port, metrics_path, data_root)
    server.serve_forever()


if __name__ == "__main__":
    main()
