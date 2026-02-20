from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _safe_iso_ts_to_epoch(value: str) -> Optional[float]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


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
    daily_pnl_quote: float
    daily_fills_count: float
    fills_total: float
    recent_error_lines: float


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
                    daily_pnl_quote=_safe_float(daily_row.get("pnl_quote")),
                    daily_fills_count=_safe_float(daily_row.get("fills_count")),
                    fills_total=float(fills_total),
                    recent_error_lines=float(recent_error_lines),
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
            lines.append(f"hbot_bot_fills_total{_fmt_labels(base_labels)} {snapshot.fills_total}")
            lines.append(f"hbot_bot_recent_error_lines{_fmt_labels(base_labels)} {snapshot.recent_error_lines}")
            fee_labels = dict(base_labels)
            fee_labels["source"] = snapshot.fee_source or "unknown"
            lines.append(f"hbot_bot_fee_source_info{_fmt_labels(fee_labels)} 1")
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
            with target.open("r", encoding="utf-8", errors="ignore") as fp:
                lines = fp.readlines()
            tail = lines[-self._log_tail_lines :]
            return sum(1 for line in tail if "ERROR" in line)
        except Exception:
            return 0


class MetricsHandler(BaseHTTPRequestHandler):
    exporter: BotMetricsExporter
    metrics_path: str = "/metrics"

    def do_GET(self):
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
