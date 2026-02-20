from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional


class CsvSplitLogger:
    def __init__(self, base_log_dir: str, instance_name: str, variant: str):
        root = Path(base_log_dir).expanduser().resolve()
        self.log_dir = root / "epp_v24" / f"{instance_name}_{variant.lower()}"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._paths = {
            "fills": self.log_dir / "fills.csv",
            "minute": self.log_dir / "minute.csv",
            "daily": self.log_dir / "daily.csv",
        }

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _append(self, key: str, row: Dict[str, object], fieldnames: Iterable[str]) -> None:
        path = self._paths[key]
        field_list = list(fieldnames)
        write_header = not path.exists() or path.stat().st_size == 0
        # If the schema changed, rotate the old file so new rows keep a valid header.
        if not write_header:
            try:
                with path.open("r", encoding="utf-8") as existing:
                    first_line = existing.readline().strip()
                expected = ",".join(field_list)
                if first_line != expected:
                    rotated = path.with_name(f"{path.stem}.legacy_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}{path.suffix}")
                    path.rename(rotated)
                    write_header = True
            except Exception:
                pass
        with path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=field_list)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

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
