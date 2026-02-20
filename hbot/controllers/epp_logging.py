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
        write_header = not path.exists() or path.stat().st_size == 0
        with path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(fieldnames))
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
            "turnover_today_x",
            "cancel_per_min",
            "orders_active",
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
