from __future__ import annotations

import json
import os
from pathlib import Path

from tests.services.conftest import _Proc
from scripts.release.run_promotion_gates import (
    _enabled_policy_bots,
    _freshest_report,
    _history_backfill_gate_status,
    _history_read_rollout_enabled,
    _history_seed_rollout_status,
    _run_event_store_once,
    _day2_freshness,
    _day2_lag_within_tolerance,
    _live_account_mode_bots,
    _parity_active_scope,
    _parity_drift_audit_status,
    _paper_exchange_threshold_inputs_readiness,
    _parity_core_insufficient_active_bots,
    _performance_dossier_expectancy_diag,
    _portfolio_diversification_gate,
    _reconciliation_active_bot_coverage,
    _run_performance_dossier,
    _trading_validation_ladder_status,
    _run_canonical_plane_gate,
    _run_paper_exchange_golden_path_check,
    _run_paper_exchange_load_check,
    _run_paper_exchange_sustained_qualification,
    _run_paper_exchange_perf_baseline_capture,
    _run_paper_exchange_perf_regression_check,
    _run_paper_exchange_threshold_inputs_builder,
    _run_paper_exchange_preflight_check,
    _run_replay_regression_multi_window,
    _run_alerting_health_check,
    _run_road9_allocation_rebalance,
    _run_realtime_l2_data_quality_check,
    _run_runtime_performance_budgets_check,
    _report_ts_utc,
    _run_testnet_multi_day_summary,
)


def test_history_read_rollout_enabled_detects_non_legacy_modes(monkeypatch) -> None:
    monkeypatch.setenv("HB_HISTORY_PROVIDER_ENABLED", "false")
    monkeypatch.setenv("HB_HISTORY_SEED_ENABLED", "false")
    monkeypatch.setenv("HB_HISTORY_UI_READ_MODE", "legacy")
    monkeypatch.setenv("HB_HISTORY_ANALYTICS_READ_MODE", "legacy")
    monkeypatch.setenv("HB_HISTORY_OPS_READ_MODE", "legacy")
    monkeypatch.setenv("HB_HISTORY_ML_READ_MODE", "legacy")
    assert _history_read_rollout_enabled() is False

    monkeypatch.setenv("HB_HISTORY_UI_READ_MODE", "shadow")
    assert _history_read_rollout_enabled() is True


def test_history_backfill_gate_status_requires_fresh_clean_report(tmp_path: Path) -> None:
    report_path = tmp_path / "market_bar_v2_backfill_latest.json"
    report_path.write_text("{}", encoding="utf-8")
    diag = _history_backfill_gate_status(
        {
            "ts_utc": "3026-03-01T00:00:00Z",
            "status": "pass",
            "missing_count_after": 0,
            "sample_mismatch_count": 0,
        },
        report_path,
        enforced=True,
        max_age_min=60.0,
    )
    assert diag["ready"] is True
    assert "PASS" in str(diag["reason"])


def test_report_ts_utc_falls_back_to_last_update_utc() -> None:
    assert _report_ts_utc({"ts_utc": "3026-03-01T00:00:00Z"}) == "3026-03-01T00:00:00Z"
    assert _report_ts_utc({"last_update_utc": "3026-03-01T00:01:00Z"}) == "3026-03-01T00:01:00Z"
    assert _report_ts_utc({}) == ""


def test_freshest_report_prefers_fresher_timestamped_artifact(tmp_path: Path) -> None:
    stale_latest = tmp_path / "latest.json"
    fresh_report = tmp_path / "reconciliation_30260301T000500Z.json"
    stale_latest.write_text(json.dumps({"ts_utc": "3026-03-01T00:00:00Z"}), encoding="utf-8")
    fresh_report.write_text(json.dumps({"ts_utc": "3026-03-01T00:05:00Z"}), encoding="utf-8")

    path, payload, _age = _freshest_report([stale_latest, fresh_report])

    assert path == fresh_report
    assert payload["ts_utc"] == "3026-03-01T00:05:00Z"


def test_history_seed_rollout_status_detects_bad_seed_states(tmp_path: Path) -> None:
    minute_file = tmp_path / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    minute_file.parent.mkdir(parents=True, exist_ok=True)
    minute_file.write_text(
        "\n".join(
            [
                "ts,history_seed_status,history_seed_source",
                "3026-03-01T00:00:00+00:00,gapped,db_v2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    diag = _history_seed_rollout_status(tmp_path, enabled=True, max_age_min=30.0)
    assert diag["ready"] is False
    assert diag["failing_bots"] == ["bot1:gapped"]


def test_history_seed_rollout_status_passes_for_fresh_seeded_bot(tmp_path: Path) -> None:
    minute_file = tmp_path / "bot7" / "logs" / "epp_v24" / "bot7_a" / "minute.csv"
    minute_file.parent.mkdir(parents=True, exist_ok=True)
    minute_file.write_text(
        "\n".join(
            [
                "ts,history_seed_status,history_seed_source,history_seed_bars",
                "3026-03-01T00:00:00+00:00,fresh,db_v2,33",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    diag = _history_seed_rollout_status(tmp_path, enabled=True, max_age_min=30.0)
    assert diag["ready"] is True
    assert diag["active_bots"] == ["bot7"]


def test_history_seed_rollout_status_ignores_bots_outside_allowed_scope(tmp_path: Path) -> None:
    stale_bot = tmp_path / "bot2" / "logs" / "epp_v24" / "bot2_a" / "minute.csv"
    healthy_bot = tmp_path / "bot7" / "logs" / "epp_v24" / "bot7_a" / "minute.csv"
    stale_bot.parent.mkdir(parents=True, exist_ok=True)
    healthy_bot.parent.mkdir(parents=True, exist_ok=True)
    stale_bot.write_text(
        "ts,history_seed_status\n3026-03-01T00:00:00+00:00,disabled\n",
        encoding="utf-8",
    )
    healthy_bot.write_text(
        "ts,history_seed_status\n3026-03-01T00:00:00+00:00,fresh\n",
        encoding="utf-8",
    )

    diag = _history_seed_rollout_status(tmp_path, enabled=True, max_age_min=30.0, allowed_bots={"bot7"})

    assert diag["ready"] is True
    assert diag["active_bots"] == ["bot7"]


def test_history_seed_rollout_status_accepts_stale_when_runtime_policy_allows(monkeypatch, tmp_path: Path) -> None:
    minute_file = tmp_path / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    minute_file.parent.mkdir(parents=True, exist_ok=True)
    minute_file.write_text(
        "ts,history_seed_status\n3026-03-01T00:00:00+00:00,stale\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HB_HISTORY_RUNTIME_MIN_STATUS", "degraded")

    diag = _history_seed_rollout_status(tmp_path, enabled=True, max_age_min=30.0)

    assert diag["ready"] is True
    assert diag["failing_bots"] == []


def test_history_seed_rollout_status_rejects_stale_when_runtime_policy_requires_fresh(monkeypatch, tmp_path: Path) -> None:
    minute_file = tmp_path / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    minute_file.parent.mkdir(parents=True, exist_ok=True)
    minute_file.write_text(
        "ts,history_seed_status\n3026-03-01T00:00:00+00:00,stale\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HB_HISTORY_RUNTIME_MIN_STATUS", "fresh")

    diag = _history_seed_rollout_status(tmp_path, enabled=True, max_age_min=30.0)

    assert diag["ready"] is False
    assert diag["failing_bots"] == ["bot1:stale"]


def test_history_seed_rollout_status_rejects_degraded_when_runtime_policy_requires_fresh(monkeypatch, tmp_path: Path) -> None:
    minute_file = tmp_path / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    minute_file.parent.mkdir(parents=True, exist_ok=True)
    minute_file.write_text(
        "ts,history_seed_status\n3026-03-01T00:00:00+00:00,degraded\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HB_HISTORY_RUNTIME_MIN_STATUS", "fresh")

    diag = _history_seed_rollout_status(tmp_path, enabled=True, max_age_min=30.0)

    assert diag["ready"] is False
    assert diag["failing_bots"] == ["bot1:degraded"]


def test_enabled_policy_bots_returns_enabled_only(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "multi_bot_policy_v1.json").write_text(
        """{
  "bots": {
    "bot1": {"enabled": true},
    "bot2": {"enabled": false},
    "bot7": {"enabled": true}
  }
}""",
        encoding="utf-8",
    )

    assert _enabled_policy_bots(tmp_path) == ["bot1", "bot7"]


def test_parity_core_insufficient_flags_only_active_bots() -> None:
    parity = {
        "status": "pass",
        "bots": [
            {
                "bot": "bot1",
                "summary": {
                    "intents_total": 2,
                    "actionable_intents": 0,
                    "fills_total": 0,
                    "equity_first": 100.0,
                    "equity_last": 100.0,
                },
                "metrics": [
                    {"metric": "fill_ratio_delta", "note": "insufficient_data", "value": None, "delta": None},
                    {"metric": "slippage_delta_bps", "note": "insufficient_data", "value": None, "delta": None},
                    {"metric": "reject_rate_delta", "note": "insufficient_data", "value": None, "delta": None},
                ],
            },
            {
                "bot": "bot4",
                "summary": {
                    "intents_total": 0,
                    "actionable_intents": 0,
                    "fills_total": 0,
                    "equity_first": None,
                    "equity_last": None,
                },
                "metrics": [
                    {"metric": "fill_ratio_delta", "note": "insufficient_data", "value": None, "delta": None},
                    {"metric": "slippage_delta_bps", "note": "insufficient_data", "value": None, "delta": None},
                    {"metric": "reject_rate_delta", "note": "insufficient_data", "value": None, "delta": None},
                ],
            },
        ],
    }
    insufficient, active = _parity_core_insufficient_active_bots(parity)
    assert active == ["bot1"]
    assert insufficient == ["bot1"]


def test_parity_active_scope_prefers_explicit_active_bots() -> None:
    parity = {
        "active_bots": ["bot4", "bot1"],
        "bots": [
            {"bot": "bot1", "summary": {"intents_total": 0}},
            {"bot": "bot4", "summary": {"intents_total": 0}},
            {"bot": "bot7", "summary": {"intents_total": 3}},
        ],
    }
    assert _parity_active_scope(parity) == ["bot1", "bot4"]


def test_parity_core_insufficient_passes_when_any_core_metric_has_data() -> None:
    parity = {
        "status": "pass",
        "bots": [
            {
                "bot": "bot1",
                "summary": {
                    "intents_total": 1,
                    "actionable_intents": 1,
                    "fills_total": 0,
                    "equity_first": 100.0,
                    "equity_last": 101.0,
                },
                "metrics": [
                    {"metric": "fill_ratio_delta", "note": "insufficient_data", "value": None, "delta": None},
                    {"metric": "slippage_delta_bps", "note": "", "value": 1.2, "delta": -0.3},
                    {"metric": "reject_rate_delta", "note": "insufficient_data", "value": None, "delta": None},
                ],
            }
        ],
    }
    insufficient, active = _parity_core_insufficient_active_bots(parity)
    assert active == ["bot1"]
    assert insufficient == []


def test_parity_drift_audit_status_flags_active_bot_findings() -> None:
    diag = _parity_drift_audit_status(
        {
            "ts_utc": "3026-03-01T00:00:00Z",
            "active_bots": ["bot1", "bot2"],
            "bots": [
                {"bot": "bot1", "pass": False, "buckets": ["fill_path_insufficient_evidence"]},
                {"bot": "bot2", "pass": True, "buckets": []},
                {"bot": "bot9", "pass": False, "buckets": ["fill_path_insufficient_evidence"]},
            ],
        },
        max_report_age_min=60.0,
    )
    assert diag["fresh"] is True
    assert diag["active_bots"] == ["bot1", "bot2"]
    assert diag["failing_active_bots"] == ["bot1"]
    assert diag["insufficient_active_bots"] == ["bot1"]


def test_day2_lag_within_tolerance_ignores_negative_deltas_as_non_lag(tmp_path: Path) -> None:
    reports = tmp_path / "event_store"
    reports.mkdir(parents=True, exist_ok=True)
    source_compare = reports / "source_compare_20260228T000002Z.json"
    source_compare.write_text(
        """{
  "delta_produced_minus_ingested_since_baseline": {
    "hb.market_data.v1": -26,
    "hb.signal.v1": -1
  }
}""",
        encoding="utf-8",
    )
    day2 = {"source_compare_file": str(source_compare)}
    ok, diag = _day2_lag_within_tolerance(day2, reports, max_allowed_delta=5)
    assert ok is True
    assert diag["max_delta_observed"] == 0
    assert diag["offending_streams"] == {}


def test_day2_freshness_uses_file_mtime_when_ts_missing(tmp_path: Path) -> None:
    day2_path = tmp_path / "day2_gate_eval_latest.json"
    day2_path.write_text("{}", encoding="utf-8")
    is_fresh, age_min = _day2_freshness({}, day2_path, max_report_age_min=60.0)
    assert is_fresh is True
    assert age_min < 1.0


def test_day2_lag_within_tolerance_fails_when_delta_exceeds_threshold(tmp_path: Path) -> None:
    reports = tmp_path / "event_store"
    reports.mkdir(parents=True, exist_ok=True)
    source_compare = reports / "source_compare_20260228T000000Z.json"
    source_compare.write_text(
        """{
  "lag_produced_minus_ingested_since_baseline": {
    "hb.market_data.v1": 9,
    "hb.signal.v1": 0
  }
}""",
        encoding="utf-8",
    )
    day2 = {"source_compare_file": str(source_compare)}
    ok, diag = _day2_lag_within_tolerance(day2, reports, max_allowed_delta=5)
    assert ok is False
    assert diag["max_delta_observed"] == 9
    assert diag["worst_stream"] == "hb.market_data.v1"
    assert diag["offending_streams"] == {"hb.market_data.v1": 9}


def test_day2_lag_within_tolerance_recovers_when_delta_is_within_threshold(tmp_path: Path) -> None:
    reports = tmp_path / "event_store"
    reports.mkdir(parents=True, exist_ok=True)
    source_compare = reports / "source_compare_20260228T000001Z.json"
    source_compare.write_text(
        """{
  "lag_produced_minus_ingested_since_baseline": {
    "hb.market_data.v1": 4,
    "hb.signal.v1": 1
  }
}""",
        encoding="utf-8",
    )
    day2 = {"source_compare_file": str(source_compare)}
    ok, diag = _day2_lag_within_tolerance(day2, reports, max_allowed_delta=5)
    assert ok is True
    assert diag["max_delta_observed"] == 4
    assert diag["offending_streams"] == {}


def test_portfolio_diversification_gate_passes_for_pass_and_insufficient_data() -> None:
    ok_pass, reason_pass = _portfolio_diversification_gate({"status": "pass"})
    ok_ins, reason_ins = _portfolio_diversification_gate({"status": "insufficient_data"})
    assert ok_pass is True
    assert "within threshold" in reason_pass
    assert ok_ins is True
    assert "insufficient overlap" in reason_ins


def test_portfolio_diversification_gate_fails_for_fail_or_missing_status() -> None:
    ok_fail, reason_fail = _portfolio_diversification_gate({"status": "fail"})
    ok_missing, reason_missing = _portfolio_diversification_gate({})
    assert ok_fail is False
    assert "above threshold" in reason_fail
    assert ok_missing is False
    assert "missing or invalid" in reason_missing


def test_paper_exchange_threshold_inputs_readiness_ready_when_clean() -> None:
    diag = _paper_exchange_threshold_inputs_readiness(
        {
            "status": "ok",
            "diagnostics": {
                "unresolved_metric_count": 0,
                "stale_sources": [],
                "missing_sources": [],
            },
        }
    )
    assert diag["ready"] is True
    assert diag["unresolved_metric_count"] == 0
    assert diag["stale_source_count"] == 0
    assert diag["missing_source_count"] == 0


def test_paper_exchange_threshold_inputs_readiness_not_ready_with_unresolved_or_stale_sources() -> None:
    diag = _paper_exchange_threshold_inputs_readiness(
        {
            "status": "warning",
            "diagnostics": {
                "unresolved_metric_count": 2,
                "unresolved_metrics": ["m1", "m2"],
                "stale_sources": ["parity_latest"],
                "missing_sources": [],
            },
        }
    )
    assert diag["ready"] is False
    assert diag["unresolved_metric_count"] == 2
    assert diag["stale_source_count"] == 1
    assert diag["missing_source_count"] == 0


def test_paper_exchange_threshold_inputs_readiness_not_ready_with_blocking_manual_metrics() -> None:
    diag = _paper_exchange_threshold_inputs_readiness(
        {
            "status": "warning",
            "diagnostics": {
                "unresolved_metric_count": 0,
                "stale_sources": [],
                "missing_sources": [],
                "manual_metric_count": 2,
                "manual_metrics_blocking_count": 2,
            },
        }
    )
    assert diag["ready"] is False
    assert diag["manual_metric_count"] == 2
    assert diag["manual_metrics_blocking_count"] == 2
    assert diag["manual_metrics_blocking"] is True


def test_reconciliation_active_bot_coverage_detects_uncovered_bots() -> None:
    diag = _reconciliation_active_bot_coverage(
        {
            "active_bots": ["bot1", "bot2"],
            "covered_active_bots": ["bot1"],
            "active_bots_unchecked": ["bot2"],
        }
    )
    assert diag["coverage_ok"] is False
    assert diag["active_bot_count"] == 2
    assert diag["covered_active_bot_count"] == 1
    assert diag["uncovered_active_bots"] == ["bot2"]


def test_freshest_report_supports_reconciliation_family_selection(tmp_path: Path) -> None:
    reports = tmp_path / "reconciliation"
    reports.mkdir(parents=True, exist_ok=True)
    latest = reports / "latest.json"
    stamped = reports / "reconciliation_30260301T000500Z.json"
    latest.write_text(json.dumps({"ts_utc": "3026-03-01T00:00:00Z", "status": "critical"}), encoding="utf-8")
    stamped.write_text(json.dumps({"ts_utc": "3026-03-01T00:05:00Z", "status": "ok"}), encoding="utf-8")

    path, payload, _age = _freshest_report([latest, *sorted(reports.glob("reconciliation_*.json"))])

    assert path == stamped
    assert payload["status"] == "ok"


def test_freshest_report_supports_parity_family_selection(tmp_path: Path) -> None:
    reports = tmp_path / "parity"
    dated = reports / "30260301"
    dated.mkdir(parents=True, exist_ok=True)
    latest = reports / "latest.json"
    stamped = dated / "parity_30260301T000500Z.json"
    latest.write_text(json.dumps({"ts_utc": "3026-03-01T00:00:00Z", "status": "fail"}), encoding="utf-8")
    stamped.write_text(json.dumps({"ts_utc": "3026-03-01T00:05:00Z", "status": "pass"}), encoding="utf-8")

    path, payload, _age = _freshest_report([latest, *sorted(reports.glob("**/parity_*.json"))])

    assert path == stamped
    assert payload["status"] == "pass"


def test_freshest_report_supports_realtime_l2_family_selection(tmp_path: Path) -> None:
    reports = tmp_path / "verification"
    reports.mkdir(parents=True, exist_ok=True)
    latest = reports / "realtime_l2_data_quality_latest.json"
    stamped = reports / "realtime_l2_data_quality_30260301T000500Z.json"
    latest.write_text(json.dumps({"ts_utc": "3026-03-01T00:00:00Z", "status": "fail"}), encoding="utf-8")
    stamped.write_text(json.dumps({"ts_utc": "3026-03-01T00:05:00Z", "status": "pass"}), encoding="utf-8")

    path, payload, _age = _freshest_report([latest, *sorted(reports.glob("realtime_l2_data_quality_*.json"))])

    assert path == stamped
    assert payload["status"] == "pass"


def test_freshest_report_supports_event_store_integrity_family_selection(tmp_path: Path) -> None:
    reports = tmp_path / "event_store"
    reports.mkdir(parents=True, exist_ok=True)
    stale = reports / "integrity_30260301T000000Z.json"
    fresh = reports / "integrity_30260301T000500Z.json"
    stale.write_text(json.dumps({"ts_utc": "3026-03-01T00:00:00Z", "missing_correlation_count": 0}), encoding="utf-8")
    fresh.write_text(json.dumps({"ts_utc": "3026-03-01T00:05:00Z", "missing_correlation_count": 0}), encoding="utf-8")

    path, payload, _age = _freshest_report(sorted(reports.glob("integrity_*.json")))

    assert path == fresh
    assert payload["ts_utc"] == "3026-03-01T00:05:00Z"


def test_live_account_mode_bots_filters_disabled_policy_scope(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "exchange_account_map.json").write_text(
        """{
  "bots": {
    "bot1": {"account_mode": "live"},
    "bot2": {"account_mode": "live"},
    "bot3": {"account_mode": "paper_only"}
  }
}""",
        encoding="utf-8",
    )
    (config / "multi_bot_policy_v1.json").write_text(
        """{
  "bots": {
    "bot1": {"enabled": true},
    "bot2": {"enabled": false},
    "bot3": {"enabled": true}
  }
}""",
        encoding="utf-8",
    )
    assert _live_account_mode_bots(tmp_path) == ["bot1"]


def test_run_paper_exchange_preflight_uses_pythonpath_env(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def _fake_run(cmd, cwd, capture_output, text, check, env):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _Proc(stdout="ok")

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)

    rc, msg = _run_paper_exchange_preflight_check(tmp_path, strict=True)
    assert rc == 0
    assert msg == "ok"
    assert str(tmp_path) == captured["cwd"]
    assert "--strict" in captured["cmd"]
    env = captured["env"]
    py_path = str(env.get("PYTHONPATH", ""))
    assert str(tmp_path) in py_path.split(os.pathsep)


def test_run_replay_regression_multi_window_forwards_portfolio_flag(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def _fake_run(cmd, cwd, capture_output, text, check):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return _Proc(stdout="ok")

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)

    rc, msg = _run_replay_regression_multi_window(tmp_path, require_portfolio_risk_healthy=False)
    assert rc == 0
    assert msg == "ok"
    assert str(tmp_path) == captured["cwd"]
    assert "--no-require-portfolio-risk-healthy" in captured["cmd"]


def test_run_testnet_multi_day_summary_forwards_window(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def _fake_run(cmd, cwd, capture_output, text, check):  # noqa: ARG001
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return _Proc(stdout="ok")

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)

    rc, msg = _run_testnet_multi_day_summary(tmp_path, end_day_utc="2026-03-05", window_days=28)
    assert rc == 0
    assert msg == "ok"
    assert str(tmp_path) == captured["cwd"]
    cmd = captured["cmd"]
    assert str(tmp_path / "scripts" / "analysis" / "testnet_multi_day_summary.py") in cmd
    assert "--start" in cmd
    assert "--end" in cmd


def test_run_performance_dossier_forwards_args_and_pythonpath(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def _fake_run(cmd, cwd, capture_output, text, check, env):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _Proc(stdout="ok")

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)

    rc, msg = _run_performance_dossier(
        tmp_path,
        bot_log_root="data/bot1/logs/epp_v24/bot1_a",
        lookback_days=14,
    )
    assert rc == 0
    assert msg == "ok"
    assert str(tmp_path) == captured["cwd"]
    cmd = captured["cmd"]
    assert str(tmp_path / "scripts" / "analysis" / "performance_dossier.py") in cmd
    assert "--lookback-days" in cmd
    assert "--bot-log-root" in cmd
    assert "--save" in cmd
    env = captured["env"]
    py_path = str(env.get("PYTHONPATH", ""))
    assert str(tmp_path) in py_path.split(os.pathsep)


def test_performance_dossier_expectancy_diag_detects_negative_rolling_ci_gate() -> None:
    diag = _performance_dossier_expectancy_diag(
        {
            "status": "warning",
            "summary": {
                "rolling_expectancy_sample_count": 300,
                "rolling_expectancy_gate_min_fills": 300,
                "rolling_expectancy_window_fills": 300,
                "rolling_expectancy_ci95_high_quote": -0.01,
                "rolling_expectancy_gate_fail": True,
            },
        }
    )
    assert diag["summary_present"] is True
    assert diag["rolling_gate_armed"] is True
    assert diag["gate_pass"] is False
    assert diag["rolling_gate_fail"] is True


def test_performance_dossier_expectancy_diag_passes_when_gate_not_armed() -> None:
    diag = _performance_dossier_expectancy_diag(
        {
            "status": "ok",
            "summary": {
                "rolling_expectancy_sample_count": 40,
                "rolling_expectancy_gate_min_fills": 300,
                "rolling_expectancy_window_fills": 300,
                "rolling_expectancy_ci95_high_quote": -0.05,
                "rolling_expectancy_gate_fail": False,
            },
        }
    )
    assert diag["summary_present"] is True
    assert diag["rolling_gate_armed"] is False
    assert diag["gate_pass"] is True
    assert "not armed" in str(diag["reason"]).lower()


def test_run_road9_allocation_rebalance_forwards_script(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def _fake_run(cmd, cwd, capture_output, text, check):  # noqa: ARG001
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return _Proc(stdout="ok")

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)

    rc, msg = _run_road9_allocation_rebalance(tmp_path)
    assert rc == 0
    assert msg == "ok"
    assert str(tmp_path) == captured["cwd"]
    cmd = captured["cmd"]
    assert str(tmp_path / "scripts" / "analysis" / "rebalance_multi_bot_policy.py") in cmd
    assert "--update-max-alloc" in cmd


def test_run_canonical_plane_gate_forwards_threshold_args(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def _fake_run(cmd, cwd, capture_output, text, check, env):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _Proc(stdout="ok")

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)

    rc, msg = _run_canonical_plane_gate(
        tmp_path,
        max_db_ingest_age_min=25.0,
        max_parity_delta_ratio=0.05,
        min_duplicate_suppression_rate=0.995,
        max_replay_lag_delta=6,
    )
    assert rc == 0
    assert msg == "ok"
    assert str(tmp_path) == captured["cwd"]
    assert str(tmp_path / "scripts" / "release" / "check_canonical_plane_gate.py") in captured["cmd"]
    assert "--max-db-ingest-age-min" in captured["cmd"]
    assert "--max-parity-delta-ratio" in captured["cmd"]
    assert "--min-duplicate-suppression-rate" in captured["cmd"]
    assert "--max-replay-lag-delta" in captured["cmd"]
    env = captured["env"]
    py_path = str(env.get("PYTHONPATH", ""))
    assert str(tmp_path) in py_path.split(os.pathsep)


def test_run_threshold_inputs_builder_forwards_manual_metrics_path(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def _fake_run(cmd, cwd, capture_output, text, check, env):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _Proc(stdout="ok")

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)

    rc, msg = _run_paper_exchange_threshold_inputs_builder(
        tmp_path,
        strict=True,
        max_source_age_min=60.0,
        manual_metrics_path="reports/verification/paper_exchange_threshold_metrics_manual.json",
    )
    assert rc == 0
    assert msg == "ok"
    assert str(tmp_path) == captured["cwd"]
    cmd = captured["cmd"]
    assert str(tmp_path / "scripts" / "release" / "build_paper_exchange_threshold_inputs.py") in cmd
    assert "--strict" in cmd
    assert "--max-source-age-min" in cmd
    assert "--manual-metrics-path" in cmd
    env = captured["env"]
    py_path = str(env.get("PYTHONPATH", ""))
    assert str(tmp_path) in py_path.split(os.pathsep)


def test_run_paper_exchange_perf_regression_forwards_threshold_args(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def _fake_run(cmd, cwd, capture_output, text, check, env):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _Proc(stdout="ok")

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)

    rc, msg = _run_paper_exchange_perf_regression_check(
        tmp_path,
        strict=True,
        current_report_path="reports/verification/paper_exchange_load_latest.json",
        baseline_report_path="reports/verification/paper_exchange_load_baseline_latest.json",
        waiver_path="reports/verification/paper_exchange_perf_regression_waiver_latest.json",
        max_latency_regression_pct=15.0,
        max_backlog_regression_pct=10.0,
        min_throughput_ratio=0.9,
        max_restart_regression=0.0,
        max_waiver_hours=12.0,
    )
    assert rc == 0
    assert msg == "ok"
    assert str(tmp_path) == captured["cwd"]
    cmd = captured["cmd"]
    assert str(tmp_path / "scripts" / "release" / "check_paper_exchange_perf_regression.py") in cmd
    assert "--strict" in cmd
    assert "--max-latency-regression-pct" in cmd
    assert "--max-backlog-regression-pct" in cmd
    assert "--min-throughput-ratio" in cmd
    assert "--max-restart-regression" in cmd
    assert "--max-waiver-hours" in cmd
    env = captured["env"]
    py_path = str(env.get("PYTHONPATH", ""))
    assert str(tmp_path) in py_path.split(os.pathsep)


def test_run_paper_exchange_perf_baseline_capture_forwards_profile(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def _fake_run(cmd, cwd, capture_output, text, check, env):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _Proc(stdout="ok")

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)

    rc, msg = _run_paper_exchange_perf_baseline_capture(
        tmp_path,
        strict=True,
        source_report_path="reports/verification/paper_exchange_load_latest.json",
        baseline_output_path="reports/verification/paper_exchange_load_baseline_latest.json",
        profile_label="sustained_2h",
        require_source_pass=True,
    )
    assert rc == 0
    assert msg == "ok"
    assert str(tmp_path) == captured["cwd"]
    cmd = captured["cmd"]
    assert str(tmp_path / "scripts" / "release" / "capture_paper_exchange_perf_baseline.py") in cmd
    assert "--strict" in cmd
    assert "--source-report-path" in cmd
    assert "--baseline-output-path" in cmd
    assert "--profile-label" in cmd
    assert "--require-source-pass" in cmd
    env = captured["env"]
    py_path = str(env.get("PYTHONPATH", ""))
    assert str(tmp_path) in py_path.split(os.pathsep)


def test_run_paper_exchange_load_check_forwards_sustained_window_and_budgets(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def _fake_run(cmd, cwd, capture_output, text, check, env):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _Proc(stdout="ok")

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)

    rc, msg = _run_paper_exchange_load_check(
        tmp_path,
        strict=True,
        lookback_sec=900,
        sample_count=9000,
        min_latency_samples=300,
        min_window_sec=180,
        sustained_window_sec=7200,
        min_instance_coverage=3,
        enforce_budget_checks=True,
        min_throughput_cmds_per_sec=55.0,
        max_latency_p95_ms=450.0,
        max_latency_p99_ms=900.0,
        max_backlog_growth_pct_per_10min=0.8,
        max_restart_count=0.0,
        command_stream="hb.paper_exchange.command.v1",
        event_stream="hb.paper_exchange.event.v1",
        heartbeat_stream="hb.paper_exchange.heartbeat.v1",
        consumer_group="hb_group_paper_exchange",
        heartbeat_consumer_group="hb_group_paper_exchange",
        heartbeat_consumer_name="paper_exchange_service",
        load_run_id="run-1",
    )
    assert rc == 0
    assert msg == "ok"
    assert str(tmp_path) == captured["cwd"]
    cmd = captured["cmd"]
    assert str(tmp_path / "scripts" / "release" / "check_paper_exchange_load.py") in cmd
    assert "--strict" in cmd
    assert "--sustained-window-sec" in cmd
    assert "--enforce-budget-checks" in cmd
    assert "--min-instance-coverage" in cmd
    assert "--min-throughput-cmds-per-sec" in cmd
    assert "--max-latency-p95-ms" in cmd
    assert "--max-latency-p99-ms" in cmd
    assert "--max-backlog-growth-pct-per-10min" in cmd
    assert "--max-restart-count" in cmd
    assert "--load-run-id" in cmd
    env = captured["env"]
    py_path = str(env.get("PYTHONPATH", ""))
    assert str(tmp_path) in py_path.split(os.pathsep)


def test_run_paper_exchange_sustained_qualification_forwards_profile(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def _fake_run(cmd, cwd, capture_output, text, check, env):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _Proc(stdout="ok")

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)

    rc, msg = _run_paper_exchange_sustained_qualification(
        tmp_path,
        strict=True,
        duration_sec=7200.0,
        target_cmd_rate=60.0,
        min_commands=0,
        command_maxlen=0,
        producer="hb_bridge_active_adapter",
        instance_name="bot1",
        instance_names="bot1,bot3,bot4",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        min_instance_coverage=3,
        result_timeout_sec=45.0,
        poll_interval_ms=250,
        scan_count=30000,
        lookback_sec=0,
        sample_count=0,
        sustained_window_sec=0,
        command_stream="hb.paper_exchange.command.v1",
        event_stream="hb.paper_exchange.event.v1",
        heartbeat_stream="hb.paper_exchange.heartbeat.v1",
        consumer_group="hb_group_paper_exchange",
        heartbeat_consumer_group="hb_group_paper_exchange",
        heartbeat_consumer_name="paper_exchange_1",
        min_throughput_cmds_per_sec=50.0,
        max_latency_p95_ms=500.0,
        max_latency_p99_ms=1000.0,
        max_backlog_growth_pct_per_10min=1.0,
        max_restart_count=0.0,
    )
    assert rc == 0
    assert msg == "ok"
    assert str(tmp_path) == captured["cwd"]
    cmd = captured["cmd"]
    assert str(tmp_path / "scripts" / "release" / "run_paper_exchange_sustained_qualification.py") in cmd
    assert "--strict" in cmd
    assert "--duration-sec" in cmd
    assert "--target-cmd-rate" in cmd
    assert "--sustained-window-sec" in cmd
    assert "--sample-count" in cmd
    assert "--min-instance-coverage" in cmd
    assert "--min-throughput-cmds-per-sec" in cmd
    env = captured["env"]
    py_path = str(env.get("PYTHONPATH", ""))
    assert str(tmp_path) in py_path.split(os.pathsep)


def test_run_paper_exchange_golden_path_forwards_strict_and_pythonpath(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def _fake_run(cmd, cwd, capture_output, text, check, env):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _Proc(stdout="ok")

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)

    rc, msg = _run_paper_exchange_golden_path_check(tmp_path, strict=True)
    assert rc == 0
    assert msg == "ok"
    assert str(tmp_path) == captured["cwd"]
    cmd = captured["cmd"]
    assert str(tmp_path / "scripts" / "release" / "run_paper_exchange_golden_path.py") in cmd
    assert "--strict" in cmd
    env = captured["env"]
    py_path = str(env.get("PYTHONPATH", ""))
    assert str(tmp_path) in py_path.split(os.pathsep)


def test_run_alerting_health_check_forwards_strict(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def _fake_run(cmd, cwd, capture_output, text, check):  # noqa: ARG001
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return _Proc(stdout="ok")

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)

    rc, msg = _run_alerting_health_check(tmp_path, strict=True)
    assert rc == 0
    assert msg == "ok"
    assert str(tmp_path) == captured["cwd"]
    cmd = captured["cmd"]
    assert str(tmp_path / "scripts" / "release" / "check_alerting_health.py") in cmd
    assert "--strict" in cmd


def test_run_realtime_l2_data_quality_check_forwards_threshold_args(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def _fake_run(cmd, cwd, capture_output, text, check, env):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _Proc(stdout="ok")

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)

    rc, msg = _run_realtime_l2_data_quality_check(
        tmp_path,
        max_age_sec=120,
        max_sequence_gap=25,
        min_sampled_events=2,
        max_raw_to_sampled_ratio=40.0,
        max_depth_stream_share=0.9,
        max_depth_event_bytes=3500,
        lookback_depth_events=2000,
    )
    assert rc == 0
    assert msg == "ok"
    assert str(tmp_path) == captured["cwd"]
    cmd = captured["cmd"]
    assert str(tmp_path / "scripts" / "release" / "check_realtime_l2_data_quality.py") in cmd
    assert "--max-age-sec" in cmd
    assert "--max-sequence-gap" in cmd
    assert "--max-raw-to-sampled-ratio" in cmd
    assert "--max-depth-stream-share" in cmd
    env = captured["env"]
    py_path = str(env.get("PYTHONPATH", ""))
    assert str(tmp_path) in py_path.split(os.pathsep)


def test_run_runtime_performance_budgets_check_forwards_threshold_args(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def _fake_run(cmd, cwd, capture_output, text, check, env):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _Proc(stdout="ok")

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)

    rc, msg = _run_runtime_performance_budgets_check(
        tmp_path,
        exporter_render_samples=7,
        max_controller_tick_p95_ms=210.0,
        max_exporter_render_p95_ms=420.0,
        max_event_store_ingest_p95_ms=180.0,
        max_source_age_min=15.0,
    )

    assert rc == 0
    assert msg == "ok"
    assert str(tmp_path) == captured["cwd"]
    cmd = captured["cmd"]
    assert str(tmp_path / "scripts" / "release" / "check_runtime_performance_budgets.py") in cmd
    assert "--exporter-render-samples" in cmd
    assert "--max-controller-tick-p95-ms" in cmd
    assert "--max-exporter-render-p95-ms" in cmd
    assert "--max-event-store-ingest-p95-ms" in cmd
    assert "--max-source-age-min" in cmd
    env = captured["env"]
    py_path = str(env.get("PYTHONPATH", ""))
    assert str(tmp_path) in py_path.split(os.pathsep)


def test_trading_validation_ladder_status_passes_when_prereqs_met(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    (reports / "ops").mkdir(parents=True, exist_ok=True)
    (reports / "strategy").mkdir(parents=True, exist_ok=True)

    (reports / "ops" / "go_live_checklist_evidence_latest.json").write_text(
        '{"overall_status":"pass","status_counts":{"in_progress":0,"fail":0,"unknown":0}}',
        encoding="utf-8",
    )
    (reports / "strategy" / "multi_day_summary_latest.json").write_text(
        """{
  "n_days": 20,
  "road1_gate": {
    "pass": true,
    "criteria": {
      "min_days_gte_20": true,
      "consecutive_days_complete": true,
      "mean_daily_net_pnl_bps_positive": true,
      "sharpe_gte_1_5": true,
      "max_drawdown_lt_2pct": true,
      "no_hard_stop_days": true,
      "spread_capture_dominant_source": true
    }
  }
}""",
        encoding="utf-8",
    )
    (reports / "ops" / "testnet_readiness_latest.json").write_text(
        '{"status":"pass"}',
        encoding="utf-8",
    )
    (reports / "strategy" / "testnet_daily_scorecard_latest.json").write_text(
        '{"status":"pass"}',
        encoding="utf-8",
    )
    (reports / "strategy" / "testnet_multi_day_summary_latest.json").write_text(
        """{
  "coverage_days": 28,
  "trading_days_count": 20,
  "road5_gate": {
    "pass": true,
    "criteria": {
      "calendar_coverage_days_gte_28": true,
      "trading_days_gte_20": true,
      "no_hard_stop_incidents": true,
      "slippage_delta_lt_2bps": true,
      "rejection_rate_lt_0_5pct": true,
      "testnet_sharpe_gte_0_8x_paper": true
    }
  }
}""",
        encoding="utf-8",
    )
    for day in range(1, 29):
        (reports / "strategy" / f"testnet_daily_scorecard_202601{day:02d}.json").write_text(
            '{"status":"pass"}',
            encoding="utf-8",
        )

    diag = _trading_validation_ladder_status(reports)
    assert diag["pass"] is True
    assert diag["blocking_reasons"] == []
    assert diag["road5_coverage_days"] == 28


def test_trading_validation_ladder_status_blocks_when_prereqs_missing(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    diag = _trading_validation_ladder_status(reports)
    assert diag["pass"] is False
    reasons = " ".join(diag["blocking_reasons"])
    assert "p0_4_go_live_checklist_incomplete" in reasons
    assert "road1_not_ready" in reasons
    assert "road5_not_ready" in reasons
    assert "no live promotion path allowed" in diag["reason"]


def test_trading_validation_ladder_status_blocks_when_road1_required_criteria_missing(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    (reports / "ops").mkdir(parents=True, exist_ok=True)
    (reports / "strategy").mkdir(parents=True, exist_ok=True)

    (reports / "ops" / "go_live_checklist_evidence_latest.json").write_text(
        '{"overall_status":"pass","status_counts":{"in_progress":0,"fail":0,"unknown":0}}',
        encoding="utf-8",
    )
    (reports / "strategy" / "multi_day_summary_latest.json").write_text(
        '{"n_days":20,"road1_gate":{"pass":true,"criteria":{"sharpe_gte_1_5":true}}}',
        encoding="utf-8",
    )
    (reports / "ops" / "testnet_readiness_latest.json").write_text(
        '{"status":"pass"}',
        encoding="utf-8",
    )
    (reports / "strategy" / "testnet_daily_scorecard_latest.json").write_text(
        '{"status":"pass"}',
        encoding="utf-8",
    )
    for day in range(1, 29):
        (reports / "strategy" / f"testnet_daily_scorecard_202601{day:02d}.json").write_text(
            '{"status":"pass"}',
            encoding="utf-8",
        )

    diag = _trading_validation_ladder_status(reports)
    assert diag["pass"] is False
    assert "road1_not_ready" in " ".join(diag["blocking_reasons"])
    assert diag["road1_criteria_ready"] is False
    assert "min_days_gte_20" in diag["road1_missing_criteria_keys"]


def test_trading_validation_ladder_status_blocks_when_road5_required_criteria_missing(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    (reports / "ops").mkdir(parents=True, exist_ok=True)
    (reports / "strategy").mkdir(parents=True, exist_ok=True)

    (reports / "ops" / "go_live_checklist_evidence_latest.json").write_text(
        '{"overall_status":"pass","status_counts":{"in_progress":0,"fail":0,"unknown":0}}',
        encoding="utf-8",
    )
    (reports / "strategy" / "multi_day_summary_latest.json").write_text(
        """{
  "n_days": 20,
  "road1_gate": {
    "pass": true,
    "criteria": {
      "min_days_gte_20": true,
      "consecutive_days_complete": true,
      "mean_daily_net_pnl_bps_positive": true,
      "sharpe_gte_1_5": true,
      "max_drawdown_lt_2pct": true,
      "no_hard_stop_days": true,
      "spread_capture_dominant_source": true
    }
  }
}""",
        encoding="utf-8",
    )
    (reports / "ops" / "testnet_readiness_latest.json").write_text(
        '{"status":"pass"}',
        encoding="utf-8",
    )
    (reports / "strategy" / "testnet_daily_scorecard_latest.json").write_text(
        '{"status":"pass"}',
        encoding="utf-8",
    )
    (reports / "strategy" / "testnet_multi_day_summary_latest.json").write_text(
        '{"coverage_days": 28, "trading_days_count": 20, "road5_gate": {"pass": true, "criteria": {"trading_days_gte_20": true}}}',
        encoding="utf-8",
    )
    for day in range(1, 29):
        (reports / "strategy" / f"testnet_daily_scorecard_202601{day:02d}.json").write_text(
            '{"status":"pass"}',
            encoding="utf-8",
        )

    diag = _trading_validation_ladder_status(reports)
    assert diag["pass"] is False
    assert "road5_not_ready" in " ".join(diag["blocking_reasons"])
    assert diag["road5_criteria_ready"] is False
    assert "calendar_coverage_days_gte_28" in diag["road5_missing_criteria_keys"]


def test_trading_validation_ladder_status_bypasses_when_not_enforced(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    diag = _trading_validation_ladder_status(reports, enforce_live_path=False)
    assert diag["pass"] is True
    assert diag["enforced"] is False
    assert "bypassed" in diag["reason"]


def test_run_event_store_once_falls_back_to_docker_when_host_client_disabled(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def _fake_run(cmd, cwd, capture_output, text, check, env=None):  # noqa: ARG001
        calls.append(cmd)
        if len(calls) == 1:
            return _Proc(
                1,
                "Redis stream client disabled (enabled=False redis=True)\n"
                "RuntimeError: Redis stream client is disabled. Set EXT_SIGNAL_RISK_ENABLED=true",
            )
        return _Proc(0, "")

    monkeypatch.setattr("scripts.release.run_promotion_gates.subprocess.run", _fake_run)
    rc, msg = _run_event_store_once(tmp_path)
    assert rc == 0
    assert len(calls) == 2
    assert calls[1][0:3] == ["docker", "exec", "kzay-capital-event-store-service"]
    assert "docker_rc=0" in msg

