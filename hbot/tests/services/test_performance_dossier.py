from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.analysis.performance_dossier import _resolve_output_paths, build_dossier


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_build_dossier_includes_checks_and_daily_rollups(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PERF_DOSSIER_EXPECTANCY_ROLLING_WINDOW_FILLS", "2")
    monkeypatch.setenv("PERF_DOSSIER_EXPECTANCY_GATE_MIN_FILLS", "2")
    root = tmp_path / "hbot"
    bot = root / "data" / "bot1" / "logs" / "epp_v24" / "bot1_a"
    _write_csv(
        bot / "fills.csv",
        [
            "ts",
            "side",
            "price",
            "mid_ref",
            "notional_quote",
            "fee_quote",
            "realized_pnl_quote",
            "is_maker",
            "regime",
            "alpha_policy_state",
            "alpha_policy_reason",
        ],
        [
            {
                "ts": "2026-02-27T12:00:00+00:00",
                "side": "buy",
                "price": "100.1",
                "mid_ref": "100.0",
                "notional_quote": "10",
                "fee_quote": "0.01",
                "realized_pnl_quote": "0.05",
                "is_maker": "true",
                "regime": "neutral_low_vol",
                "alpha_policy_state": "maker_bias_buy",
                "alpha_policy_reason": "imbalance_alignment",
            },
            {
                "ts": "2026-02-27T12:01:00+00:00",
                "side": "sell",
                "price": "100.2",
                "mid_ref": "100.1",
                "notional_quote": "10",
                "fee_quote": "0.01",
                "realized_pnl_quote": "0.04",
                "is_maker": "false",
                "regime": "up",
                "alpha_policy_state": "aggressive_sell",
                "alpha_policy_reason": "inventory_relief",
            },
        ],
    )
    _write_csv(
        bot / "minute.csv",
        [
            "ts",
            "drawdown_pct",
            "soft_pause_edge",
            "selective_quote_state",
            "alpha_policy_state",
            "order_book_stale",
            "state",
            "cancel_per_min",
            "fills_count_today",
        ],
        [
            {
                "ts": "2026-02-27T12:00:00+00:00",
                "drawdown_pct": "0.001",
                "soft_pause_edge": "False",
                "selective_quote_state": "reduced",
                "alpha_policy_state": "maker_bias_buy",
                "order_book_stale": "False",
                "state": "running",
                "cancel_per_min": "0",
                "fills_count_today": "0",
            },
            {
                "ts": "2026-02-27T12:01:00+00:00",
                "drawdown_pct": "0.002",
                "soft_pause_edge": "True",
                "selective_quote_state": "blocked",
                "alpha_policy_state": "aggressive_sell",
                "order_book_stale": "False",
                "state": "soft_pause",
                "cancel_per_min": "3",
                "fills_count_today": "0",
            },
        ],
    )
    (root / "reports" / "reconciliation").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "portfolio_risk").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "promotion_gates").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "reconciliation" / "latest.json").write_text(
        json.dumps({"status": "ok", "critical_count": 0, "warning_count": 0}),
        encoding="utf-8",
    )
    (root / "reports" / "portfolio_risk" / "latest.json").write_text(
        json.dumps({"status": "ok", "critical_count": 0, "warning_count": 0}),
        encoding="utf-8",
    )
    (root / "reports" / "promotion_gates" / "strict_cycle_latest.json").write_text(
        json.dumps({"strict_gate_status": "PASS", "strict_gate_rc": 0}),
        encoding="utf-8",
    )

    out = build_dossier(root=root, bot_log_root=bot, lookback_days=3)

    assert out["status"] in {"pass", "warning"}
    assert out["data_source_mode"] == "csv"
    assert out["summary"]["days_included"] == 1
    assert out["summary"]["maker_ratio_weighted"] == 0.5
    assert out["summary"]["maker_ratio_mean_daily"] == 0.5
    assert out["summary"]["soft_pause_state_ratio"] == 0.5
    assert out["summary"]["soft_pause_edge_ratio"] == 0.5
    assert out["summary"]["selective_quote_block_rows"] == 1
    assert out["summary"]["selective_quote_block_ratio"] == 0.5
    assert out["summary"]["selective_quote_reduce_rows"] == 1
    assert out["summary"]["selective_quote_reduce_ratio"] == 0.5
    assert out["summary"]["alpha_no_trade_rows"] == 0
    assert out["summary"]["alpha_aggressive_rows"] == 1
    assert out["summary"]["alpha_aggressive_ratio"] == 0.5
    assert out["summary"]["cancel_before_fill_rows"] == 1
    assert out["summary"]["cancel_before_fill_rate"] == 0.5
    assert out["summary"]["rolling_expectancy_sample_count"] == 2
    assert out["summary"]["rolling_expectancy_gate_fail"] is False
    assert out["summary"]["rolling_expectancy_ci95_high_quote"] > 0
    assert out["summary"]["maker_expectancy_sample_count"] == 1
    assert out["summary"]["taker_expectancy_sample_count"] == 1
    assert out["summary"]["alpha_policy_expectancy"]["maker_bias_buy"]["fills"] == 1.0
    assert out["summary"]["regime_expectancy"]["up"]["fills"] == 1.0
    assert len(out["daily_breakdown"]) == 1
    assert len(out["checks"]) >= 5


def test_resolve_output_paths_supports_custom_stem(tmp_path: Path) -> None:
    repo_root = tmp_path / "hbot"
    json_path, md_path = _resolve_output_paths(repo_root, "reports/analysis", "bot5_performance_dossier_latest")

    assert json_path == repo_root / "reports" / "analysis" / "bot5_performance_dossier_latest.json"
    assert md_path == repo_root / "reports" / "analysis" / "bot5_performance_dossier_latest.md"


def test_rolling_expectancy_gate_fails_when_sample_below_minimum(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PERF_DOSSIER_EXPECTANCY_ROLLING_WINDOW_FILLS", "10")
    monkeypatch.setenv("PERF_DOSSIER_EXPECTANCY_GATE_MIN_FILLS", "5")
    root = tmp_path / "hbot"
    bot = root / "data" / "bot1" / "logs" / "epp_v24" / "bot1_a"

    _write_csv(
        bot / "fills.csv",
        [
            "ts",
            "side",
            "price",
            "mid_ref",
            "notional_quote",
            "fee_quote",
            "realized_pnl_quote",
            "is_maker",
            "regime",
            "alpha_policy_state",
            "alpha_policy_reason",
        ],
        [
            {
                "ts": "2026-02-27T12:00:00+00:00",
                "side": "buy",
                "price": "100.1",
                "mid_ref": "100.0",
                "notional_quote": "10",
                "fee_quote": "0.01",
                "realized_pnl_quote": "0.03",
                "is_maker": "true",
                "regime": "neutral_low_vol",
                "alpha_policy_state": "maker_two_sided",
                "alpha_policy_reason": "maker_baseline",
            },
        ],
    )
    _write_csv(
        bot / "minute.csv",
        [
            "ts",
            "drawdown_pct",
            "soft_pause_edge",
            "selective_quote_state",
            "alpha_policy_state",
            "order_book_stale",
            "state",
            "cancel_per_min",
            "fills_count_today",
        ],
        [
            {
                "ts": "2026-02-27T12:00:00+00:00",
                "drawdown_pct": "0.001",
                "soft_pause_edge": "False",
                "selective_quote_state": "inactive",
                "alpha_policy_state": "maker_two_sided",
                "order_book_stale": "False",
                "state": "running",
                "cancel_per_min": "0",
                "fills_count_today": "1",
            },
        ],
    )

    (root / "reports" / "reconciliation").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "portfolio_risk").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "promotion_gates").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "reconciliation" / "latest.json").write_text(
        json.dumps({"status": "ok", "critical_count": 0, "warning_count": 0}),
        encoding="utf-8",
    )
    (root / "reports" / "portfolio_risk" / "latest.json").write_text(
        json.dumps({"status": "ok", "critical_count": 0, "warning_count": 0}),
        encoding="utf-8",
    )
    (root / "reports" / "promotion_gates" / "strict_cycle_latest.json").write_text(
        json.dumps({"strict_gate_status": "PASS", "strict_gate_rc": 0}),
        encoding="utf-8",
    )

    out = build_dossier(root=root, bot_log_root=bot, lookback_days=3)

    rolling_check = next(c for c in out["checks"] if c["name"] == "rolling_expectancy_ci95_upper_non_negative")
    assert out["summary"]["rolling_expectancy_sample_count"] == 1
    assert out["summary"]["rolling_expectancy_gate_ready"] is False
    assert out["summary"]["rolling_expectancy_gate_fail"] is False
    assert rolling_check["pass"] is False
    assert "gate_ready=False" in str(rolling_check.get("note", ""))
