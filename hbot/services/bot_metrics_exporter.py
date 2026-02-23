from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional


from services.common.utils import env_int as _env_int, safe_float as _safe_float, parse_iso_ts


def _safe_iso_ts_to_epoch(value: str) -> Optional[float]:
    dt = parse_iso_ts(value)
    return dt.timestamp() if dt else None


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt_labels(labels: Dict[str, str]) -> str:
    if not labels:
        return ""
    pairs = [f'{k}="{_escape_label(v)}"' for k, v in labels.items()]
    return "{" + ",".join(pairs) + "}"


@dataclass
class BotSnapshot:
    bot_name: str
    variant: str
    exchange: str
    trading_pair: str
    state: str
    regime: str
    ts_epoch: float
    net_edge_pct: float
    spread_pct: float
    spread_floor_pct: float
    turnover_today_x: float
    orders_active: float
    maker_fee_pct: float
    taker_fee_pct: float
    soft_pause_edge: float
    fee_source: str
    equity_quote: float
    base_pct: float
    target_base_pct: float
    daily_loss_pct: float
    drawdown_pct: float
    cancel_per_min: float
    risk_reasons: str
    daily_pnl_quote: float
    daily_fills_count: float
    fills_total: float
    recent_error_lines: float
    tick_duration_ms: float
    indicator_duration_ms: float
    connector_io_duration_ms: float
    position_drift_pct: float
    margin_ratio: float
    funding_rate: float
    realized_pnl_today_quote: float
    ws_reconnect_count: float
    order_book_stale: float


class BotMetricsExporter:
    def __init__(self, data_root: Path, log_tail_lines: int = 200):
        self._data_root = data_root
        self._log_tail_lines = log_tail_lines

    def collect(self) -> List[BotSnapshot]:
        snapshots: List[BotSnapshot] = []
        for minute_file in self._data_root.glob("*/logs/epp_v24/*/minute.csv"):
            bot_name = minute_file.parts[-5]
            latest_minute = self._read_last_csv_row(minute_file)
            if latest_minute is None:
                continue
            log_dir = minute_file.parent
            daily_row = self._read_last_csv_row(log_dir / "daily.csv") or {}
            fills_total = self._count_csv_rows(log_dir / "fills.csv")
            recent_error_lines = self._count_recent_error_lines(self._data_root / bot_name / "logs")

            ts_epoch = _safe_iso_ts_to_epoch(str(latest_minute.get("ts", ""))) or 0.0
            snapshots.append(
                BotSnapshot(
                    bot_name=bot_name,
                    variant=str(latest_minute.get("bot_variant", "")),
                    exchange=str(latest_minute.get("exchange", "")),
                    trading_pair=str(latest_minute.get("trading_pair", "")),
                    state=str(latest_minute.get("state", "")),
                    regime=str(latest_minute.get("regime", "")),
                    ts_epoch=ts_epoch,
                    net_edge_pct=_safe_float(latest_minute.get("net_edge_pct")),
                    spread_pct=_safe_float(latest_minute.get("spread_pct")),
                    spread_floor_pct=_safe_float(latest_minute.get("spread_floor_pct")),
                    turnover_today_x=_safe_float(latest_minute.get("turnover_today_x")),
                    orders_active=_safe_float(latest_minute.get("orders_active")),
                    maker_fee_pct=_safe_float(latest_minute.get("maker_fee_pct")),
                    taker_fee_pct=_safe_float(latest_minute.get("taker_fee_pct")),
                    soft_pause_edge=1.0 if str(latest_minute.get("soft_pause_edge", "")).lower() == "true" else 0.0,
                    fee_source=str(latest_minute.get("fee_source", "")),
                    equity_quote=_safe_float(latest_minute.get("equity_quote")),
                    base_pct=_safe_float(latest_minute.get("base_pct")),
                    target_base_pct=_safe_float(latest_minute.get("target_base_pct")),
                    daily_loss_pct=_safe_float(latest_minute.get("daily_loss_pct")),
                    drawdown_pct=_safe_float(latest_minute.get("drawdown_pct")),
                    cancel_per_min=_safe_float(latest_minute.get("cancel_per_min")),
                    risk_reasons=str(latest_minute.get("risk_reasons", "")),
                    daily_pnl_quote=_safe_float(daily_row.get("pnl_quote")),
                    daily_fills_count=_safe_float(daily_row.get("fills_count")),
                    fills_total=float(fills_total),
                    recent_error_lines=float(recent_error_lines),
                    tick_duration_ms=_safe_float(latest_minute.get("_tick_duration_ms")),
                    indicator_duration_ms=_safe_float(latest_minute.get("_indicator_duration_ms")),
                    connector_io_duration_ms=_safe_float(latest_minute.get("_connector_io_duration_ms")),
                    position_drift_pct=_safe_float(latest_minute.get("position_drift_pct")),
                    margin_ratio=_safe_float(latest_minute.get("margin_ratio"), 1.0),
                    funding_rate=_safe_float(latest_minute.get("funding_rate")),
                    realized_pnl_today_quote=_safe_float(latest_minute.get("realized_pnl_today_quote")),
                    ws_reconnect_count=_safe_float(latest_minute.get("ws_reconnect_count")),
                    order_book_stale=1.0 if str(latest_minute.get("order_book_stale", "")).lower() == "true" else 0.0,
                )
            )
        return snapshots

    def render_prometheus(self) -> str:
        now = datetime.now(timezone.utc).timestamp()
        lines: List[str] = []
        lines.extend(
            [
                "# HELP hbot_bot_snapshot_timestamp_seconds Latest bot snapshot timestamp from minute.csv.",
                "# TYPE hbot_bot_snapshot_timestamp_seconds gauge",
                "# HELP hbot_bot_snapshot_age_seconds Snapshot age in seconds.",
                "# TYPE hbot_bot_snapshot_age_seconds gauge",
                "# HELP hbot_bot_state Current bot state as a one-hot gauge.",
                "# TYPE hbot_bot_state gauge",
                "# HELP hbot_bot_net_edge_pct Net edge percentage from strategy minute snapshot.",
                "# TYPE hbot_bot_net_edge_pct gauge",
                "# HELP hbot_bot_spread_pct Active spread percentage from minute snapshot.",
                "# TYPE hbot_bot_spread_pct gauge",
                "# HELP hbot_bot_spread_floor_pct Active spread floor percentage from minute snapshot.",
                "# TYPE hbot_bot_spread_floor_pct gauge",
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
                "# HELP hbot_bot_fills_total Total fills rows observed in fills.csv.",
                "# TYPE hbot_bot_fills_total gauge",
                "# HELP hbot_bot_recent_error_lines Number of ERROR lines in recent bot log tail.",
                "# TYPE hbot_bot_recent_error_lines gauge",
            ]
        )
        for snapshot in self.collect():
            base_labels = {
                "bot": snapshot.bot_name,
                "variant": snapshot.variant,
                "exchange": snapshot.exchange,
                "pair": snapshot.trading_pair,
                "regime": snapshot.regime,
            }
            lines.append(f"hbot_bot_snapshot_timestamp_seconds{_fmt_labels(base_labels)} {snapshot.ts_epoch}")
            lines.append(f"hbot_bot_snapshot_age_seconds{_fmt_labels(base_labels)} {max(0.0, now - snapshot.ts_epoch)}")
            for state in ("running", "soft_pause", "hard_stop"):
                state_labels = dict(base_labels)
                state_labels["state"] = state
                state_value = 1.0 if snapshot.state == state else 0.0
                lines.append(f"hbot_bot_state{_fmt_labels(state_labels)} {state_value}")
            lines.append(f"hbot_bot_net_edge_pct{_fmt_labels(base_labels)} {snapshot.net_edge_pct}")
            lines.append(f"hbot_bot_spread_pct{_fmt_labels(base_labels)} {snapshot.spread_pct}")
            lines.append(f"hbot_bot_spread_floor_pct{_fmt_labels(base_labels)} {snapshot.spread_floor_pct}")
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
            lines.append(f"hbot_bot_fills_total{_fmt_labels(base_labels)} {snapshot.fills_total}")
            lines.append(f"hbot_bot_recent_error_lines{_fmt_labels(base_labels)} {snapshot.recent_error_lines}")
            fee_labels = dict(base_labels)
            fee_labels["source"] = snapshot.fee_source or "unknown"
            lines.append(f"hbot_bot_fee_source_info{_fmt_labels(fee_labels)} 1")
            risk_labels = dict(base_labels)
            risk_labels["reasons"] = snapshot.risk_reasons or "none"
            lines.append(f"hbot_bot_risk_reasons_info{_fmt_labels(risk_labels)} 1")
            lines.append(f"hbot_bot_tick_duration_seconds{_fmt_labels(base_labels)} {snapshot.tick_duration_ms / 1000.0}")
            lines.append(f"hbot_bot_tick_indicator_seconds{_fmt_labels(base_labels)} {snapshot.indicator_duration_ms / 1000.0}")
            lines.append(f"hbot_bot_tick_connector_io_seconds{_fmt_labels(base_labels)} {snapshot.connector_io_duration_ms / 1000.0}")
            lines.append(f"hbot_bot_position_drift_pct{_fmt_labels(base_labels)} {snapshot.position_drift_pct}")
            lines.append(f"hbot_bot_margin_ratio{_fmt_labels(base_labels)} {snapshot.margin_ratio}")
            lines.append(f"hbot_bot_funding_rate{_fmt_labels(base_labels)} {snapshot.funding_rate}")
            lines.append(f"hbot_bot_realized_pnl_today_quote{_fmt_labels(base_labels)} {snapshot.realized_pnl_today_quote}")
            lines.append(f"hbot_bot_ws_reconnect_total{_fmt_labels(base_labels)} {snapshot.ws_reconnect_count}")
            lines.append(f"hbot_bot_order_book_stale{_fmt_labels(base_labels)} {snapshot.order_book_stale}")
        return "\n".join(lines) + "\n"

    def _read_last_csv_row(self, path: Path) -> Optional[Dict[str, str]]:
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8", newline="") as fp:
                reader = csv.DictReader(fp)
                last = None
                for row in reader:
                    last = row
                return last
        except Exception:
            return None

    def _count_csv_rows(self, path: Path) -> int:
        if not path.exists():
            return 0
        try:
            with path.open("r", encoding="utf-8", newline="") as fp:
                reader = csv.reader(fp)
                count = -1
                for _ in reader:
                    count += 1
                return max(0, count)
        except Exception:
            return 0

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
            return 0


class MetricsHandler(BaseHTTPRequestHandler):
    exporter: BotMetricsExporter
    metrics_path: str = "/metrics"

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return
        if self.path != self.metrics_path:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return
        body = self.exporter.render_prometheus().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    data_root = Path(os.getenv("HB_DATA_ROOT", "/workspace/hbot/data")).resolve()
    port = _env_int("METRICS_PORT", 9400)
    metrics_path = os.getenv("METRICS_PATH", "/metrics")
    log_tail_lines = _env_int("EXPORTER_LOG_TAIL_LINES", 200)

    exporter = BotMetricsExporter(data_root=data_root, log_tail_lines=log_tail_lines)
    MetricsHandler.exporter = exporter
    MetricsHandler.metrics_path = metrics_path

    server = ThreadingHTTPServer(("0.0.0.0", port), MetricsHandler)
    print(f"bot_metrics_exporter listening on :{port}{metrics_path}, data_root={data_root}")
    server.serve_forever()


if __name__ == "__main__":
    main()
