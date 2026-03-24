from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from scripts.analysis import bot1_multi_day_summary as multi_day_summary
from scripts.analysis import bot1_paper_day_summary as day_summary
from scripts.analysis import pnl_governor_ab_short_run as ab_short_run
from scripts.analysis import pnl_governor_ab_tuning as ab_tuning
from scripts.analysis import testnet_multi_day_summary as testnet_multi_day_summary
from scripts.analysis.bot1_tca_report import run_tca
from scripts.analysis.portfolio_diversification_check import build_diversification_report
from scripts.analysis.testnet_daily_scorecard import build_scorecard


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_scorecard_no_testnet_fills_only_when_testnet_is_empty(tmp_path: Path) -> None:
    testnet_root = tmp_path / "testnet"
    paper_root = tmp_path / "paper"
    reports_root = tmp_path / "reports"
    headers = ["ts", "pnl_vs_mid_pct"]
    _write_csv(
        testnet_root / "fills.csv",
        headers,
        [{"ts": "2026-02-27T12:00:00+00:00", "pnl_vs_mid_pct": "0.001"}],
    )
    _write_csv(testnet_root / "minute.csv", ["ts", "cancel_per_min", "fills_count_today", "position_drift_pct"], [])
    _write_csv(paper_root / "fills.csv", headers, [])

    payload = build_scorecard("2026-02-27", testnet_root=testnet_root, paper_root=paper_root, reports_root=reports_root)

    assert payload["metrics"]["testnet_fill_count"] == 1
    assert "no_testnet_fills" not in payload["failures"]
    assert payload["status"] == "pass"


def test_scorecard_flags_no_testnet_fills_when_empty(tmp_path: Path) -> None:
    testnet_root = tmp_path / "testnet"
    paper_root = tmp_path / "paper"
    reports_root = tmp_path / "reports"
    headers = ["ts", "pnl_vs_mid_pct"]
    _write_csv(testnet_root / "fills.csv", headers, [])
    _write_csv(testnet_root / "minute.csv", ["ts", "cancel_per_min", "fills_count_today", "position_drift_pct"], [])
    _write_csv(
        paper_root / "fills.csv",
        headers,
        [{"ts": "2026-02-27T12:00:00+00:00", "pnl_vs_mid_pct": "0.001"}],
    )

    payload = build_scorecard("2026-02-27", testnet_root=testnet_root, paper_root=paper_root, reports_root=reports_root)

    assert payload["metrics"]["testnet_fill_count"] == 0
    assert "no_testnet_fills" in payload["failures"]
    assert payload["status"] == "fail"


def test_scorecard_micro_benchmark_fails_when_deltas_exceed_thresholds(tmp_path: Path) -> None:
    testnet_root = tmp_path / "testnet"
    paper_root = tmp_path / "paper"
    reports_root = tmp_path / "reports"
    _write_csv(
        testnet_root / "fills.csv",
        ["ts", "pnl_vs_mid_pct"],
        [{"ts": "2026-02-27T12:00:00+00:00", "pnl_vs_mid_pct": "0.005"}],
    )
    _write_csv(
        paper_root / "fills.csv",
        ["ts", "pnl_vs_mid_pct"],
        [
            {"ts": "2026-02-27T12:00:00+00:00", "pnl_vs_mid_pct": "0.0001"},
            {"ts": "2026-02-27T12:01:00+00:00", "pnl_vs_mid_pct": "0.0001"},
            {"ts": "2026-02-27T12:02:00+00:00", "pnl_vs_mid_pct": "0.0001"},
        ],
    )
    _write_csv(
        testnet_root / "minute.csv",
        ["ts", "cancel_per_min", "fills_count_today", "position_drift_pct"],
        [{"ts": "2026-02-27T12:00:00+00:00", "cancel_per_min": "0", "fills_count_today": "1", "position_drift_pct": "0"}],
    )
    _write_csv(
        paper_root / "minute.csv",
        ["ts", "cancel_per_min", "fills_count_today", "position_drift_pct"],
        [
            {"ts": "2026-02-27T12:00:00+00:00", "cancel_per_min": "0", "fills_count_today": "1", "position_drift_pct": "0"},
            {"ts": "2026-02-27T12:01:00+00:00", "cancel_per_min": "0", "fills_count_today": "1", "position_drift_pct": "0"},
            {"ts": "2026-02-27T12:02:00+00:00", "cancel_per_min": "0", "fills_count_today": "1", "position_drift_pct": "0"},
        ],
    )

    payload = build_scorecard("2026-02-27", testnet_root=testnet_root, paper_root=paper_root, reports_root=reports_root)
    assert payload["micro_benchmark"]["status"] == "fail"
    assert "paper_vs_testnet_micro_benchmark_failed" in payload["failures"]
    assert payload["status"] == "fail"


def test_scorecard_fails_when_hard_stop_incident_detected(tmp_path: Path) -> None:
    testnet_root = tmp_path / "testnet"
    paper_root = tmp_path / "paper"
    reports_root = tmp_path / "reports"
    _write_csv(
        testnet_root / "fills.csv",
        ["ts", "pnl_vs_mid_pct", "realized_pnl_quote", "fee_quote"],
        [{"ts": "2026-02-27T12:00:00+00:00", "pnl_vs_mid_pct": "0.0001", "realized_pnl_quote": "1.0", "fee_quote": "0.1"}],
    )
    _write_csv(
        paper_root / "fills.csv",
        ["ts", "pnl_vs_mid_pct", "realized_pnl_quote", "fee_quote"],
        [{"ts": "2026-02-27T12:00:00+00:00", "pnl_vs_mid_pct": "0.0001", "realized_pnl_quote": "1.0", "fee_quote": "0.1"}],
    )
    _write_csv(
        testnet_root / "minute.csv",
        ["ts", "cancel_per_min", "fills_count_today", "position_drift_pct", "state"],
        [{"ts": "2026-02-27T12:00:00+00:00", "cancel_per_min": "0", "fills_count_today": "1", "position_drift_pct": "0", "state": "hard_stop"}],
    )
    _write_csv(
        paper_root / "minute.csv",
        ["ts", "cancel_per_min", "fills_count_today", "position_drift_pct", "state"],
        [{"ts": "2026-02-27T12:00:00+00:00", "cancel_per_min": "0", "fills_count_today": "1", "position_drift_pct": "0", "state": "running"}],
    )

    payload = build_scorecard("2026-02-27", testnet_root=testnet_root, paper_root=paper_root, reports_root=reports_root)
    assert payload["status"] == "fail"
    assert "hard_stop_incident_detected" in payload["failures"]
    assert payload["metrics"]["hard_stop_incident_count"] == 1


def test_testnet_multi_day_summary_passes_when_road5_criteria_are_met(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    strategy_root = reports_root / "strategy"

    for day in range(1, 29):
        _write_json(
            strategy_root / f"testnet_daily_scorecard_202601{day:02d}.json",
            {
                "status": "pass",
                "metrics": {
                    "testnet_fill_count": 10,
                    "paper_fill_count": 10,
                    "rejection_count": 0,
                    "avg_testnet_slippage_bps": 1.2,
                    "avg_paper_slippage_bps": 0.5,
                    "hard_stop_incident_count": 0,
                    "testnet_net_pnl_quote": 1.0 + day / 100.0,
                    "paper_net_pnl_quote": 1.1 + day / 100.0,
                },
            },
        )

    payload = testnet_multi_day_summary.build_summary(reports_root=reports_root)
    assert payload["coverage_days"] == 28
    assert payload["trading_days_count"] == 28
    assert payload["road5_gate"]["pass"] is True
    assert payload["road5_gate"]["failed_criteria"] == []


def test_testnet_multi_day_summary_fails_when_hard_stop_and_rejection_rate_exceed_limits(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    strategy_root = reports_root / "strategy"

    for day in range(1, 29):
        _write_json(
            strategy_root / f"testnet_daily_scorecard_202601{day:02d}.json",
            {
                "status": "pass",
                "metrics": {
                    "testnet_fill_count": 10,
                    "paper_fill_count": 10,
                    "rejection_count": 1,  # 10% reject rate over window -> fail
                    "avg_testnet_slippage_bps": 1.0,
                    "avg_paper_slippage_bps": 0.5,
                    "hard_stop_incident_count": 1 if day == 5 else 0,
                    "testnet_net_pnl_quote": 1.0 + day / 100.0,
                    "paper_net_pnl_quote": 1.2 + day / 100.0,
                },
            },
        )

    payload = testnet_multi_day_summary.build_summary(reports_root=reports_root)
    failed = payload["road5_gate"]["failed_criteria"]
    assert payload["road5_gate"]["pass"] is False
    assert "no_hard_stop_incidents" in failed
    assert "rejection_rate_lt_0_5pct" in failed


def test_tca_runs_with_parsed_timestamp_rows(tmp_path: Path) -> None:
    root = tmp_path / "bot1"
    fills_path = root / "fills.csv"
    minute_path = root / "minute.csv"
    _write_csv(
        fills_path,
        ["ts", "side", "price", "mid_ref", "fee_quote", "notional_quote", "is_maker"],
        [
            {
                "ts": "2026-02-27T12:00:30+00:00",
                "side": "buy",
                "price": "100.1",
                "mid_ref": "100.0",
                "fee_quote": "0.01",
                "notional_quote": "10.0",
                "is_maker": "true",
            }
        ],
    )
    _write_csv(
        minute_path,
        ["ts", "mid", "regime", "spread_pct"],
        [
            {"ts": "2026-02-27T12:00:00+00:00", "mid": "100.0", "regime": "neutral_low_vol", "spread_pct": "0.003"},
            {"ts": "2026-02-27T12:01:00+00:00", "mid": "100.2", "regime": "neutral_low_vol", "spread_pct": "0.003"},
        ],
    )

    out = run_tca(fills_path, minute_path, save=False)

    assert "overall" in out
    assert out["overall"]["fills"] == 1
    assert out["by_regime"][0]["label"] == "neutral_low_vol"


def test_day_summary_collects_rotated_minute_rows_with_dedupe(tmp_path: Path) -> None:
    root = tmp_path / "bot1"
    _write_csv(
        root / "minute.legacy_20260227T120000Z.csv",
        ["ts", "state", "equity_quote"],
        [
            {"ts": "2026-02-27T10:00:00+00:00", "state": "running", "equity_quote": "1000"},
            {"ts": "2026-02-27T10:01:00+00:00", "state": "running", "equity_quote": "1001"},
        ],
    )
    _write_csv(
        root / "minute.csv",
        ["ts", "state", "equity_quote"],
        [
            {"ts": "2026-02-27T10:01:00+00:00", "state": "running", "equity_quote": "1001"},
            {"ts": "2026-02-27T10:02:00+00:00", "state": "running", "equity_quote": "1002"},
        ],
    )
    rows = day_summary._collect_minute_rows_for_day(root, "2026-02-27")
    assert [r["ts"] for r in rows] == [
        "2026-02-27T10:00:00+00:00",
        "2026-02-27T10:01:00+00:00",
        "2026-02-27T10:02:00+00:00",
    ]


def test_multi_day_summary_marks_low_confidence_when_minute_missing(monkeypatch) -> None:
    def _fake_day(day: str, root: str):
        if day == "2026-02-27":
            return {
                "fills_agg": {"fills": 10, "realized_pnl_sum_quote": "1.0", "fees_quote": "0.1"},
                "minute_snapshot": {"rows": 3, "equity_quote": "500", "turnover_today_x": "1.2", "drawdown_pct": "0.002", "daily_loss_pct": "0", "regime_counts": {"neutral_low_vol": 3}},
            }
        return {
            "fills_agg": {"fills": 5, "realized_pnl_sum_quote": "0.5", "fees_quote": "0.05"},
            "minute_snapshot": {"rows": 0},
        }

    monkeypatch.setattr(multi_day_summary, "_run_day_summary", _fake_day)
    out = multi_day_summary.compute_summary("2026-02-26", "2026-02-27", root="ignored", save=False)

    assert out["n_days"] == 2
    assert out["data_source_mode_counts"]["csv"] == 2
    assert out["data_quality"]["low_confidence_days"] == 1
    assert any("low_confidence_days=1" in w for w in out["warnings"])


def test_multi_day_summary_aggregates_spread_cap_hit_ratio(monkeypatch) -> None:
    def _fake_day(day: str, root: str):
        if day == "2026-02-26":
            return {
                "fills_agg": {"fills": 4, "realized_pnl_sum_quote": "0.8", "fees_quote": "0.1"},
                "minute_snapshot": {
                    "rows": 10,
                    "equity_quote": "1000",
                    "turnover_today_x": "0.8",
                    "drawdown_pct": "0.002",
                    "daily_loss_pct": "0",
                    "regime_counts": {"neutral_low_vol": 10},
                    "spread_competitiveness_cap_active_rows": 3,
                    "spread_competitiveness_cap_observed_rows": 10,
                },
            }
        return {
            "fills_agg": {"fills": 3, "realized_pnl_sum_quote": "0.6", "fees_quote": "0.05"},
            "minute_snapshot": {
                "rows": 5,
                "equity_quote": "900",
                "turnover_today_x": "0.7",
                "drawdown_pct": "0.001",
                "daily_loss_pct": "0",
                "regime_counts": {"neutral_low_vol": 5},
                "spread_competitiveness_cap_active_rows": 2,
                "spread_competitiveness_cap_observed_rows": 5,
            },
        }

    monkeypatch.setattr(multi_day_summary, "_run_day_summary", _fake_day)
    out = multi_day_summary.compute_summary("2026-02-26", "2026-02-27", root="ignored", save=False)

    assert out["spread_competitiveness_cap_active_rows"] == 5
    assert out["spread_competitiveness_cap_observed_rows"] == 15
    assert abs(float(out["spread_competitiveness_cap_hit_ratio"]) - (5.0 / 15.0)) < 1e-9


def test_multi_day_summary_includes_funding_component(monkeypatch) -> None:
    def _fake_day(day: str, root: str):
        if day == "2026-02-26":
            return {
                "fills_agg": {"fills": 2, "realized_pnl_sum_quote": "1.0", "fees_quote": "0.1"},
                "minute_snapshot": {
                    "rows": 4,
                    "equity_quote": "1000",
                    "turnover_today_x": "0.5",
                    "drawdown_pct": "0.001",
                    "daily_loss_pct": "0",
                    "regime_counts": {"neutral_low_vol": 4},
                    "funding_cost_today_quote": "0.05",
                },
            }
        return {
            "fills_agg": {"fills": 3, "realized_pnl_sum_quote": "0.8", "fees_quote": "0.1"},
            "minute_snapshot": {
                "rows": 5,
                "equity_quote": "950",
                "turnover_today_x": "0.7",
                "drawdown_pct": "0.002",
                "daily_loss_pct": "0",
                "regime_counts": {"neutral_low_vol": 5},
                "funding_cost_today_quote": "0.10",
            },
        }

    monkeypatch.setattr(multi_day_summary, "_run_day_summary", _fake_day)
    out = multi_day_summary.compute_summary("2026-02-26", "2026-02-27", root="ignored", save=False)

    assert abs(float(out["total_net_pnl_usdt"]) - 1.6) < 1e-9
    assert abs(float(out["total_funding_cost_usdt"]) - 0.15) < 1e-9
    assert abs(float(out["total_net_pnl_including_funding_usdt"]) - 1.45) < 1e-9
    assert abs(float(out["mean_daily_pnl_including_funding_usdt"]) - 0.725) < 1e-9
    assert abs(float(out["daily_breakdown"][0]["net_pnl_including_funding_usdt"]) - 0.85) < 1e-9


def test_multi_day_summary_road1_gate_passes_with_20_consecutive_days_and_spread_capture(monkeypatch) -> None:
    def _fake_day(day: str, root: str):
        return {
            "fills_agg": {
                "fills": 10,
                "realized_pnl_sum_quote": "2.0",
                "fees_quote": "0.5",
                "notional_quote": "1000",
                "avg_edge_vs_mid_pct": "0.002",
                "pos_edge_frac": 0.8,
            },
            "minute_snapshot": {
                "rows": 10,
                "equity_quote": "1000",
                "turnover_today_x": "1.0",
                "drawdown_pct": "0.01",
                "daily_loss_pct": "0.0",
                "regime_counts": {"neutral_low_vol": 10},
                "funding_cost_today_quote": "0.0",
            },
        }

    monkeypatch.setattr(multi_day_summary, "_run_day_summary", _fake_day)
    out = multi_day_summary.compute_summary("2026-01-01", "2026-01-20", root="ignored", save=False)

    gate = out["road1_gate"]
    assert out["n_days"] == 20
    assert gate["pass"] is True
    assert gate["failed_criteria"] == []
    assert gate["criteria"]["min_days_gte_20"] is True
    assert gate["criteria"]["consecutive_days_complete"] is True
    assert gate["criteria"]["mean_daily_net_pnl_bps_positive"] is True
    assert gate["criteria"]["spread_capture_dominant_source"] is True
    assert out["pnl_decomposition"]["dominant_source"] == "spread_capture"


def test_multi_day_summary_road1_gate_fails_on_missing_days_and_non_dominant_spread_capture(monkeypatch) -> None:
    missing_day = "2026-01-10"

    def _fake_day(day: str, root: str):
        if day == missing_day:
            return None
        return {
            "fills_agg": {
                "fills": 5,
                "realized_pnl_sum_quote": "1.0",
                "fees_quote": "0.1",
                "notional_quote": "100",
                "avg_edge_vs_mid_pct": "0.0001",
                "pos_edge_frac": 0.55,
            },
            "minute_snapshot": {
                "rows": 8,
                "equity_quote": "1000",
                "turnover_today_x": "0.8",
                "drawdown_pct": "0.005",
                "daily_loss_pct": "0.0",
                "regime_counts": {"neutral_low_vol": 8},
                "funding_cost_today_quote": "0.0",
            },
        }

    monkeypatch.setattr(multi_day_summary, "_run_day_summary", _fake_day)
    out = multi_day_summary.compute_summary("2026-01-01", "2026-01-20", root="ignored", save=False)

    gate = out["road1_gate"]
    assert out["n_days"] == 19
    assert out["missing_days_count"] == 1
    assert gate["pass"] is False
    assert gate["criteria"]["min_days_gte_20"] is False
    assert gate["criteria"]["consecutive_days_complete"] is False
    assert gate["criteria"]["spread_capture_dominant_source"] is False
    assert "road1_window_shortfall_days=1" in out["warnings"]


def test_ab_short_run_writes_2h_and_24h_reports(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "bot"
    minute_path = root / "minute.csv"
    fills_path = root / "fills.csv"
    _write_csv(
        minute_path,
        ["ts", "spread_pct", "net_edge_pct", "turnover_today_x", "pnl_governor_deficit_ratio", "pnl_governor_active", "pnl_governor_size_boost_active", "pnl_governor_size_mult", "net_realized_pnl_today_quote"],
        [
            {"ts": "2026-02-27T10:00:00+00:00", "spread_pct": "0.002", "net_edge_pct": "0.0005", "turnover_today_x": "0.8", "pnl_governor_deficit_ratio": "0.1", "pnl_governor_active": "false", "pnl_governor_size_boost_active": "false", "pnl_governor_size_mult": "1.0", "net_realized_pnl_today_quote": "1.0"},
            {"ts": "2026-02-27T11:00:00+00:00", "spread_pct": "0.0022", "net_edge_pct": "0.0006", "turnover_today_x": "0.9", "pnl_governor_deficit_ratio": "0.2", "pnl_governor_active": "true", "pnl_governor_size_boost_active": "true", "pnl_governor_size_mult": "1.1", "net_realized_pnl_today_quote": "1.5"},
        ],
    )
    _write_csv(
        fills_path,
        ["ts", "price"],
        [{"ts": "2026-02-27T11:00:00+00:00", "price": "100.0"}],
    )
    out_dir = tmp_path / "reports"

    fixed_now = datetime.fromisoformat("2026-02-27T12:00:00+00:00")
    monkeypatch.setattr(ab_short_run, "_utc_now", lambda: fixed_now)
    monkeypatch.setattr(
        "sys.argv",
        [
            "pnl_governor_ab_short_run.py",
            "--single-root",
            str(root),
            "--out-dir",
            str(out_dir),
        ],
    )

    rc = ab_short_run.main()
    assert rc == 0
    assert (out_dir / "pnl_governor_ab_2h_latest.json").exists()
    assert (out_dir / "pnl_governor_ab_24h_latest.json").exists()
    assert (out_dir / "pnl_governor_ab_short_run_latest.json").exists()


def test_ab_tuning_computes_governor_reason_aggregation(tmp_path: Path) -> None:
    root = tmp_path / "bot"
    minute_path = root / "minute.csv"
    _write_csv(
        minute_path,
        [
            "ts",
            "spread_pct",
            "net_edge_pct",
            "turnover_today_x",
            "pnl_governor_deficit_ratio",
            "pnl_governor_active",
            "pnl_governor_size_boost_active",
            "pnl_governor_size_mult",
            "net_realized_pnl_today_quote",
            "pnl_governor_activation_reason",
            "pnl_governor_size_boost_reason",
        ],
        [
            {
                "ts": "2026-02-27T10:00:00+00:00",
                "spread_pct": "0.002",
                "net_edge_pct": "0.0005",
                "turnover_today_x": "0.8",
                "pnl_governor_deficit_ratio": "0.1",
                "pnl_governor_active": "false",
                "pnl_governor_size_boost_active": "false",
                "pnl_governor_size_mult": "1.0",
                "net_realized_pnl_today_quote": "1.0",
                "pnl_governor_activation_reason": "within_activation_buffer",
                "pnl_governor_size_boost_reason": "deficit_below_activation",
            },
            {
                "ts": "2026-02-27T11:00:00+00:00",
                "spread_pct": "0.0021",
                "net_edge_pct": "0.0006",
                "turnover_today_x": "0.9",
                "pnl_governor_deficit_ratio": "0.3",
                "pnl_governor_active": "true",
                "pnl_governor_size_boost_active": "true",
                "pnl_governor_size_mult": "1.1",
                "net_realized_pnl_today_quote": "1.5",
                "pnl_governor_activation_reason": "active",
                "pnl_governor_size_boost_reason": "active",
            },
            {
                "ts": "2026-02-27T11:30:00+00:00",
                "spread_pct": "0.0021",
                "net_edge_pct": "0.0006",
                "turnover_today_x": "0.9",
                "pnl_governor_deficit_ratio": "0.3",
                "pnl_governor_active": "false",
                "pnl_governor_size_boost_active": "false",
                "pnl_governor_size_mult": "1.0",
                "net_realized_pnl_today_quote": "1.5",
                "pnl_governor_activation_reason": "within_activation_buffer",
                "pnl_governor_size_boost_reason": "turnover_soft_cap",
            },
        ],
    )
    _write_csv(root / "fills.csv", ["ts", "price"], [{"ts": "2026-02-27T11:00:00+00:00", "price": "100.0"}])

    since = datetime.fromisoformat("2026-02-27T09:00:00+00:00")
    until = datetime.fromisoformat("2026-02-27T12:00:00+00:00")
    m = ab_tuning._compute_metrics(root, since, until)
    assert m.governor_activation_reason_counts["within_activation_buffer"] == 2
    assert m.governor_activation_reason_counts["active"] == 1
    assert m.dominant_activation_block_reason == "within_activation_buffer"
    assert m.dominant_size_boost_block_reason in {"deficit_below_activation", "turnover_soft_cap"}


def test_portfolio_diversification_passes_for_low_correlation(tmp_path: Path) -> None:
    btc_path = tmp_path / "btc_minute.csv"
    eth_path = tmp_path / "eth_minute.csv"
    _write_csv(
        btc_path,
        ["ts", "mid"],
        [
            {"ts": "2026-02-27T10:00:00+00:00", "mid": "100"},
            {"ts": "2026-02-27T10:01:00+00:00", "mid": "101"},
            {"ts": "2026-02-27T10:02:00+00:00", "mid": "102"},
            {"ts": "2026-02-27T10:03:00+00:00", "mid": "103"},
            {"ts": "2026-02-27T10:04:00+00:00", "mid": "104"},
            {"ts": "2026-02-27T10:05:00+00:00", "mid": "105"},
        ],
    )
    _write_csv(
        eth_path,
        ["ts", "mid"],
        [
            {"ts": "2026-02-27T10:00:00+00:00", "mid": "200"},
            {"ts": "2026-02-27T10:01:00+00:00", "mid": "201"},
            {"ts": "2026-02-27T10:02:00+00:00", "mid": "200"},
            {"ts": "2026-02-27T10:03:00+00:00", "mid": "201"},
            {"ts": "2026-02-27T10:04:00+00:00", "mid": "200"},
            {"ts": "2026-02-27T10:05:00+00:00", "mid": "201"},
        ],
    )

    payload = build_diversification_report(
        btc_minute_path=btc_path,
        eth_minute_path=eth_path,
        max_abs_correlation=0.7,
        min_overlap_points=3,
    )
    assert payload["status"] == "pass"
    alloc = payload["allocation_recommendation_inverse_variance"]
    assert abs(float(alloc["btc"]) + float(alloc["eth"]) - 1.0) < 1e-9


def test_portfolio_diversification_fails_for_high_correlation(tmp_path: Path) -> None:
    btc_path = tmp_path / "btc_minute.csv"
    eth_path = tmp_path / "eth_minute.csv"
    _write_csv(
        btc_path,
        ["ts", "mid"],
        [
            {"ts": "2026-02-27T10:00:00+00:00", "mid": "100"},
            {"ts": "2026-02-27T10:01:00+00:00", "mid": "101"},
            {"ts": "2026-02-27T10:02:00+00:00", "mid": "102"},
            {"ts": "2026-02-27T10:03:00+00:00", "mid": "103"},
            {"ts": "2026-02-27T10:04:00+00:00", "mid": "104"},
            {"ts": "2026-02-27T10:05:00+00:00", "mid": "105"},
        ],
    )
    _write_csv(
        eth_path,
        ["ts", "mid"],
        [
            {"ts": "2026-02-27T10:00:00+00:00", "mid": "200"},
            {"ts": "2026-02-27T10:01:00+00:00", "mid": "202"},
            {"ts": "2026-02-27T10:02:00+00:00", "mid": "204"},
            {"ts": "2026-02-27T10:03:00+00:00", "mid": "206"},
            {"ts": "2026-02-27T10:04:00+00:00", "mid": "208"},
            {"ts": "2026-02-27T10:05:00+00:00", "mid": "210"},
        ],
    )

    payload = build_diversification_report(
        btc_minute_path=btc_path,
        eth_minute_path=eth_path,
        max_abs_correlation=0.7,
        min_overlap_points=3,
    )
    assert payload["status"] == "fail"


def test_portfolio_diversification_aligns_offset_rows_by_minute(tmp_path: Path) -> None:
    btc_path = tmp_path / "btc_minute.csv"
    eth_path = tmp_path / "eth_minute.csv"
    _write_csv(
        btc_path,
        ["ts", "mid"],
        [
            {"ts": "2026-02-27T10:00:00+00:00", "mid": "100"},
            {"ts": "2026-02-27T10:01:00+00:00", "mid": "102"},
            {"ts": "2026-02-27T10:02:00+00:00", "mid": "101"},
            {"ts": "2026-02-27T10:03:00+00:00", "mid": "103"},
        ],
    )
    _write_csv(
        eth_path,
        ["ts", "mid"],
        [
            {"ts": "2026-02-27T10:00:05+00:00", "mid": "200"},
            {"ts": "2026-02-27T10:01:05+00:00", "mid": "199"},
            {"ts": "2026-02-27T10:02:05+00:00", "mid": "201"},
            {"ts": "2026-02-27T10:03:05+00:00", "mid": "200"},
        ],
    )

    payload = build_diversification_report(
        btc_minute_path=btc_path,
        eth_minute_path=eth_path,
        max_abs_correlation=0.7,
        min_overlap_points=2,
    )
    assert payload["status"] in {"pass", "fail"}
    assert int(payload["metrics"]["overlap_points"]) >= 2
