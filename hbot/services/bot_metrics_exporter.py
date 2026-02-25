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
class FillStats:
    buys: int = 0
    sells: int = 0
    maker_fills: int = 0
    taker_fills: int = 0
    buy_notional: float = 0.0
    sell_notional: float = 0.0
    total_fees: float = 0.0
    total_realized_pnl: float = 0.0
    avg_buy_price: float = 0.0
    avg_sell_price: float = 0.0
    last_fill_ts: str = ""
    last_fill_side: str = ""
    last_fill_price: float = 0.0
    last_fill_amount: float = 0.0
    last_fill_pnl: float = 0.0


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
    position_base: float = 0.0
    avg_entry_price: float = 0.0
    market_spread_bps: float = 0.0
    best_bid_price: float = 0.0
    best_ask_price: float = 0.0
    fill_stats: Optional[FillStats] = None


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
            daily_state = self._read_daily_state_json(log_dir / "daily_state.json")
            fills_path = log_dir / "fills.csv"
            fills_total = self._count_csv_rows(fills_path)
            fill_stats = self._compute_fill_stats(fills_path)
            recent_error_lines = self._count_recent_error_lines(self._data_root / bot_name / "logs")

            ts_epoch = _safe_iso_ts_to_epoch(str(latest_minute.get("ts", ""))) or 0.0

            equity_now = _safe_float(latest_minute.get("equity_quote"))
            equity_open = _safe_float(daily_state.get("equity_open")) if daily_state else 0.0
            live_pnl = equity_now - equity_open if equity_open > 0 else 0.0
            daily_fills = _safe_float(daily_state.get("fills_count")) if daily_state else 0.0

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
                    market_spread_bps=_safe_float(latest_minute.get("market_spread_bps")),
                    best_bid_price=_safe_float(latest_minute.get("best_bid_price")),
                    best_ask_price=_safe_float(latest_minute.get("best_ask_price")),
                    turnover_today_x=_safe_float(latest_minute.get("turnover_today_x")),
                    orders_active=_safe_float(latest_minute.get("orders_active")),
                    maker_fee_pct=_safe_float(latest_minute.get("maker_fee_pct")),
                    taker_fee_pct=_safe_float(latest_minute.get("taker_fee_pct")),
                    soft_pause_edge=1.0 if str(latest_minute.get("soft_pause_edge", "")).lower() == "true" else 0.0,
                    fee_source=str(latest_minute.get("fee_source", "")),
                    equity_quote=equity_now,
                    base_pct=_safe_float(latest_minute.get("base_pct")),
                    target_base_pct=_safe_float(latest_minute.get("target_base_pct")),
                    daily_loss_pct=_safe_float(latest_minute.get("daily_loss_pct")),
                    drawdown_pct=_safe_float(latest_minute.get("drawdown_pct")),
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
                    realized_pnl_today_quote=_safe_float(latest_minute.get("realized_pnl_today_quote")),
                    ws_reconnect_count=_safe_float(latest_minute.get("ws_reconnect_count")),
                    order_book_stale=1.0 if str(latest_minute.get("order_book_stale", "")).lower() == "true" else 0.0,
                    position_base=_safe_float(latest_minute.get("position_base")),
                    avg_entry_price=_safe_float(latest_minute.get("avg_entry_price")),
                    fill_stats=fill_stats,
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
                "# HELP hbot_bot_market_spread_bps Observed market spread in basis points from order book (minute snapshot).",
                "# TYPE hbot_bot_market_spread_bps gauge",
                "# HELP hbot_bot_best_bid_price Best bid price from order book (minute snapshot).",
                "# TYPE hbot_bot_best_bid_price gauge",
                "# HELP hbot_bot_best_ask_price Best ask price from order book (minute snapshot).",
                "# TYPE hbot_bot_best_ask_price gauge",
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
            lines.append(f"hbot_bot_market_spread_bps{_fmt_labels(base_labels)} {snapshot.market_spread_bps}")
            lines.append(f"hbot_bot_best_bid_price{_fmt_labels(base_labels)} {snapshot.best_bid_price}")
            lines.append(f"hbot_bot_best_ask_price{_fmt_labels(base_labels)} {snapshot.best_ask_price}")
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
                lines.append(f"hbot_bot_position_base{_fmt_labels(base_labels)} {snapshot.position_base}")
                lines.append(f"hbot_bot_avg_entry_price{_fmt_labels(base_labels)} {snapshot.avg_entry_price}")
        return "\n".join(lines) + "\n"

    def _read_daily_state_json(self, path: Path) -> Optional[Dict[str, str]]:
        """Read daily_state.json which is updated every 30s by the controller."""
        if not path.exists():
            return None
        try:
            import json
            data = json.loads(path.read_text(encoding="utf-8"))
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if data.get("day_key") == today:
                return data
            return data
        except Exception:
            return None

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

    def _compute_fill_stats(self, fills_path: Path) -> FillStats:
        stats = FillStats()
        if not fills_path.exists():
            return stats
        try:
            buy_prices, sell_prices = [], []
            with fills_path.open("r", encoding="utf-8", newline="") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    side = str(row.get("side", "")).lower()
                    notional = _safe_float(row.get("notional_quote"))
                    fee = _safe_float(row.get("fee_quote"))
                    price = _safe_float(row.get("price"))
                    amount = _safe_float(row.get("amount_base"))
                    pnl = _safe_float(row.get("realized_pnl_quote"))
                    is_maker = str(row.get("is_maker", "")).lower() == "true"
                    stats.total_fees += fee
                    stats.total_realized_pnl += pnl
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
                    stats.last_fill_ts = str(row.get("ts", ""))
                    stats.last_fill_side = side
                    stats.last_fill_price = price
                    stats.last_fill_amount = amount
                    stats.last_fill_pnl = pnl
            if buy_prices:
                stats.avg_buy_price = sum(buy_prices) / len(buy_prices)
            if sell_prices:
                stats.avg_sell_price = sum(sell_prices) / len(sell_prices)
        except Exception:
            pass
        return stats

    def _read_recent_fills(self, fills_path: Path, limit: int = 50) -> List[Dict[str, object]]:
        if not fills_path.exists():
            return []
        try:
            rows: List[Dict[str, str]] = []
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
            return []

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
        import json as _json
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return
        if self.path.startswith("/fills"):
            bot_filter = None
            if "?" in self.path:
                params = dict(p.split("=", 1) for p in self.path.split("?", 1)[1].split("&") if "=" in p)
                bot_filter = params.get("bot")
            limit = 50
            all_fills: list = []
            data_root = self.exporter._data_root
            for fills_file in data_root.glob("*/logs/epp_v24/*/fills.csv"):
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
            self.wfile.write(body)
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
