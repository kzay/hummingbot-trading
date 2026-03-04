from __future__ import annotations

import os
from pathlib import Path

from tests.services.conftest import _Proc
from scripts.release.run_promotion_gates import (
    _run_event_store_once,
    _day2_freshness,
    _day2_lag_within_tolerance,
    _live_account_mode_bots,
    _paper_exchange_threshold_inputs_readiness,
    _parity_core_insufficient_active_bots,
    _portfolio_diversification_gate,
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
)


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


def test_trading_validation_ladder_status_passes_when_prereqs_met(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    (reports / "ops").mkdir(parents=True, exist_ok=True)
    (reports / "strategy").mkdir(parents=True, exist_ok=True)

    (reports / "ops" / "go_live_checklist_evidence_latest.json").write_text(
        '{"overall_status":"pass","status_counts":{"in_progress":0,"fail":0,"unknown":0}}',
        encoding="utf-8",
    )
    (reports / "strategy" / "multi_day_summary_latest.json").write_text(
        '{"n_days":20,"road1_gate":{"pass":true}}',
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
    assert calls[1][0:3] == ["docker", "exec", "hbot-event-store-service"]
    assert "docker_rc=0" in msg

