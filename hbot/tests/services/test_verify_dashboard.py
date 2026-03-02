from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.ops.verify_dashboard import build_report


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed_minimum_dashboard_data(root: Path, *, tradenote_status: str) -> float:
    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()
    ts = now.isoformat()

    _write_csv(
        root / "data" / "bot1" / "logs" / "epp_v24" / "bot1_a" / "fills.csv",
        [
            "ts",
            "exchange",
            "trading_pair",
            "side",
            "price",
            "amount_base",
            "notional_quote",
            "fee_quote",
            "order_id",
            "is_maker",
            "state",
            "realized_pnl_quote",
        ],
        [
            {
                "ts": ts,
                "exchange": "bitget_paper_trade",
                "trading_pair": "BTC-USDT",
                "side": "buy",
                "price": "65000",
                "amount_base": "0.001",
                "notional_quote": "65",
                "fee_quote": "0.013",
                "order_id": "paper-1",
                "is_maker": "true",
                "state": "running",
                "realized_pnl_quote": "0.10",
            }
        ],
    )
    _write_csv(
        root / "data" / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv",
        [
            "ts",
            "exchange",
            "trading_pair",
            "state",
            "regime",
            "mid",
            "equity_quote",
            "base_pct",
            "target_base_pct",
            "daily_loss_pct",
            "drawdown_pct",
            "cancel_per_min",
            "orders_active",
            "fills_count_today",
            "fees_paid_today_quote",
            "realized_pnl_today_quote",
        ],
        [
            {
                "ts": ts,
                "exchange": "bitget_perpetual",
                "trading_pair": "BTC-USDT",
                "state": "running",
                "regime": "neutral",
                "mid": "65000",
                "equity_quote": "1000",
                "base_pct": "0.50",
                "target_base_pct": "0.45",
                "daily_loss_pct": "0.0",
                "drawdown_pct": "0.01",
                "cancel_per_min": "0.1",
                "orders_active": "1",
                "fills_count_today": "1",
                "fees_paid_today_quote": "0.013",
                "realized_pnl_today_quote": "0.10",
            }
        ],
    )
    _write_json(
        root / "reports" / "tradenote" / "sync_latest.json",
        {
            "ts_utc": ts,
            "status": tradenote_status,
            "error": "" if tradenote_status == "ok" else "missing_tradenote_api_key",
        },
    )
    _write_json(root / "reports" / "ops_db_writer" / "latest.json", {"ts_utc": ts, "status": "pass"})
    _write_json(root / "reports" / "event_store" / "integrity_20260302.json", {"total_events": 5})
    return now_ts


def test_build_report_passes_with_minimum_ready_inputs(tmp_path: Path) -> None:
    now_ts = _seed_minimum_dashboard_data(tmp_path, tradenote_status="ok")
    report = build_report(
        root=tmp_path,
        max_data_age_s=900,
        tradenote_report_max_age_s=5400,
        tradenote_fill_max_age_s=7 * 24 * 3600,
        required_grafana_bot_variants=["bot1:a"],
        required_tradenote_bot_variants=["bot1:a"],
        now_ts=now_ts,
    )
    assert report["status"] == "pass"
    assert report["tradenote_ready"] is True
    assert report["grafana_ready"] is True
    assert report["failed_checks"] == []


def test_build_report_flags_tradenote_sync_error(tmp_path: Path) -> None:
    now_ts = _seed_minimum_dashboard_data(tmp_path, tradenote_status="config_error")
    report = build_report(
        root=tmp_path,
        max_data_age_s=900,
        tradenote_report_max_age_s=5400,
        tradenote_fill_max_age_s=7 * 24 * 3600,
        required_grafana_bot_variants=["bot1:a"],
        required_tradenote_bot_variants=["bot1:a"],
        now_ts=now_ts,
    )
    assert report["status"] == "fail"
    assert report["tradenote_ready"] is False
    assert "tradenote_sync_ok" in report["failed_checks"]
