from __future__ import annotations

import csv
from pathlib import Path

from scripts.analysis import bot1_multi_day_summary as mds
from scripts.analysis.testnet_daily_scorecard import build_scorecard


def test_multi_day_summary_reports_missing_days_and_nonzero_bps(monkeypatch) -> None:
    samples = {
        "2026-01-01": {
            "fills_agg": {"fills": 10, "realized_pnl_sum_quote": "10", "fees_quote": "1"},
            "minute_snapshot": {
                "rows": 10,
                "equity_quote": "1000",
                "turnover_today_x": "2.0",
                "drawdown_pct": "0.01",
                "daily_loss_pct": "0.00",
                "regime_counts": {"neutral_low_vol": 10},
            },
        },
        "2026-01-02": None,
    }

    def _fake(day: str, root: str):
        return samples.get(day)

    monkeypatch.setattr(mds, "_run_day_summary", _fake)
    out = mds.compute_summary("2026-01-01", "2026-01-02", root="unused", save=False)
    assert out["days_checked"] == 2
    assert out["days_with_data"] == 1
    assert out["missing_days_count"] == 1
    assert out["missing_days"] == ["2026-01-02"]
    assert out["daily_breakdown"][0]["net_pnl_bps"] > 0.0
    assert "daily_table_markdown" in out


def test_testnet_daily_scorecard_builds_metrics(tmp_path: Path) -> None:
    testnet_root = tmp_path / "testnet"
    paper_root = tmp_path / "paper"
    reports_root = tmp_path / "reports"
    testnet_root.mkdir(parents=True, exist_ok=True)
    paper_root.mkdir(parents=True, exist_ok=True)

    with (testnet_root / "fills.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ts", "pnl_vs_mid_pct", "event_type"])
        w.writeheader()
        w.writerow({"ts": "2026-01-01T00:10:00+00:00", "pnl_vs_mid_pct": "0.001", "event_type": "order_filled"})
    with (paper_root / "fills.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ts"])
        w.writeheader()
        w.writerow({"ts": "2026-01-01T00:10:00+00:00"})
    with (testnet_root / "minute.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ts", "cancel_per_min", "fills_count_today", "position_drift_pct"])
        w.writeheader()
        w.writerow(
            {
                "ts": "2026-01-01T00:11:00+00:00",
                "cancel_per_min": "0",
                "fills_count_today": "1",
                "position_drift_pct": "0.0",
            }
        )

    out = build_scorecard(
        "2026-01-01",
        testnet_root=testnet_root,
        paper_root=paper_root,
        reports_root=reports_root,
    )
    assert out["status"] == "pass"
    assert out["metrics"]["fill_count_ratio"] == 1.0
    assert out["metrics"]["rejection_rate"] == 0.0
