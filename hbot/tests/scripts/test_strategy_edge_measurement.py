from __future__ import annotations

import csv
from pathlib import Path

from scripts.analysis.strategy_edge_measurement import (
    _build_summary,
    _compute_strategy_edge,
    _discover_bot_log_dirs,
    _mean_ci95,
)


def _write_fills_csv(path: Path, rows: list[dict]) -> None:
    cols = [
        "ts", "bot_variant", "exchange", "trading_pair", "side", "price",
        "amount_base", "notional_quote", "fee_quote", "order_id", "state",
        "regime", "alpha_policy_state", "alpha_policy_reason", "mid_ref",
        "expected_spread_pct", "adverse_drift_30s", "fee_source", "is_maker",
        "realized_pnl_quote",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in cols})


def _write_minute_csv(path: Path, rows: list[dict]) -> None:
    cols = [
        "ts", "bot_variant", "bot_mode", "accounting_source", "exchange",
        "trading_pair", "state", "regime", "mid", "equity_quote",
        "base_pct", "cancel_per_min", "fills_count_today",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in cols})


def test_mean_ci95_empty() -> None:
    n, mean, lo, hi = _mean_ci95([])
    assert n == 0
    assert mean == 0.0


def test_mean_ci95_single() -> None:
    n, mean, lo, hi = _mean_ci95([5.0])
    assert n == 1
    assert mean == 5.0


def test_mean_ci95_multiple() -> None:
    n, mean, lo, hi = _mean_ci95([1.0, 2.0, 3.0, 4.0, 5.0])
    assert n == 5
    assert abs(mean - 3.0) < 1e-9
    assert lo < mean
    assert hi > mean


def test_compute_strategy_edge_no_fills(tmp_path: Path) -> None:
    log_dir = tmp_path / "bot_test" / "logs" / "epp_v24" / "test_a"
    log_dir.mkdir(parents=True)
    _write_fills_csv(log_dir / "fills.csv", [])
    result = _compute_strategy_edge("test", log_dir)
    assert result["status"] == "no_fills"
    assert result["verdict"] == "INSUFFICIENT_DATA"


def test_compute_strategy_edge_with_winning_fills(tmp_path: Path) -> None:
    log_dir = tmp_path / "log"
    log_dir.mkdir()

    fills = []
    for i in range(150):
        fills.append({
            "ts": f"2026-03-{10 + i // 30:02d}T12:{i % 60:02d}:00+00:00",
            "side": "buy",
            "price": "70000",
            "notional_quote": "70",
            "fee_quote": "0.01",
            "mid_ref": "70000",
            "is_maker": "true",
            "realized_pnl_quote": "0.10",
            "regime": "neutral_low_vol",
        })
    _write_fills_csv(log_dir / "fills.csv", fills)
    _write_minute_csv(log_dir / "minute.csv", [
        {"ts": f"2026-03-{10 + d:02d}T12:00:00+00:00", "equity_quote": "1000", "state": "running"}
        for d in range(5)
    ])

    result = _compute_strategy_edge("winner", log_dir)
    assert result["status"] == "ok"
    assert result["fill_count"] == 150
    assert result["expectancy_per_fill_quote"] > 0
    assert result["verdict"] == "EDGE_CONFIRMED"
    assert result["win_rate"] == 1.0
    assert result["maker_ratio"] == 1.0


def test_compute_strategy_edge_with_losing_fills(tmp_path: Path) -> None:
    log_dir = tmp_path / "log"
    log_dir.mkdir()

    fills = []
    for i in range(200):
        fills.append({
            "ts": f"2026-03-{10 + i // 40:02d}T12:{i % 60:02d}:00+00:00",
            "side": "sell",
            "price": "70000",
            "notional_quote": "70",
            "fee_quote": "0.02",
            "mid_ref": "70000",
            "is_maker": "false",
            "realized_pnl_quote": "-0.05",
            "regime": "neutral_high_vol",
        })
    _write_fills_csv(log_dir / "fills.csv", fills)
    _write_minute_csv(log_dir / "minute.csv", [])

    result = _compute_strategy_edge("loser", log_dir)
    assert result["status"] == "ok"
    assert result["fill_count"] == 200
    assert result["expectancy_per_fill_quote"] < 0
    assert result["verdict"] == "NO_EDGE"
    assert result["win_rate"] == 0.0


def test_discover_bot_log_dirs(tmp_path: Path) -> None:
    (tmp_path / "data" / "bot1" / "logs" / "epp_v24" / "bot1_a").mkdir(parents=True)
    _write_fills_csv(tmp_path / "data" / "bot1" / "logs" / "epp_v24" / "bot1_a" / "fills.csv", [])
    (tmp_path / "data" / "bot2" / "logs" / "epp_v24" / "bot2_a").mkdir(parents=True)

    dirs = _discover_bot_log_dirs(tmp_path)
    assert "bot1" in dirs
    assert "bot2" not in dirs

    dirs_filtered = _discover_bot_log_dirs(tmp_path, filter_bots=["bot1"])
    assert "bot1" in dirs_filtered


def test_build_summary() -> None:
    strategies = {
        "bot1": {"status": "ok", "verdict": "EDGE_CONFIRMED", "fill_count": 500, "expectancy_per_fill_quote": 0.05, "annualized_sharpe": 2.0, "total_net_pnl_quote": 25.0},
        "bot2": {"status": "ok", "verdict": "NO_EDGE", "fill_count": 300, "expectancy_per_fill_quote": -0.02, "annualized_sharpe": -1.0, "total_net_pnl_quote": -6.0},
    }
    summary = _build_summary(strategies)
    assert summary["total_strategies"] == 2
    assert summary["total_fills"] == 800
    assert "bot1" in summary["edge_confirmed"]
    assert "bot2" in summary["no_edge"]
    assert "SCALE" in summary["recommendation"]
