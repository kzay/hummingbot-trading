from __future__ import annotations

from scripts.release.run_paper_exchange_sustained_qualification import (
    _expected_command_count,
    _resolve_command_maxlen,
    _resolve_lookback_sec,
    _resolve_min_commands,
    _resolve_sample_count,
    _resolve_sustained_window_sec,
    build_report,
)


def test_profile_derivations_cover_two_hour_sustained_defaults() -> None:
    duration_sec = 7200.0
    target_cmd_rate = 60.0
    expected = _expected_command_count(duration_sec, target_cmd_rate)
    assert expected == 432000
    assert _resolve_min_commands(0, duration_sec, target_cmd_rate) == 345600
    assert _resolve_command_maxlen(0, duration_sec, target_cmd_rate) == 648000
    assert _resolve_sample_count(0, duration_sec, target_cmd_rate) == 518400
    assert _resolve_lookback_sec(0, duration_sec) == 7800
    assert _resolve_sustained_window_sec(0, duration_sec) == 7200


def test_build_report_passes_when_harness_and_load_are_qualified() -> None:
    profile = {"min_instance_coverage": 3}
    harness_report = {
        "status": "pass",
        "failed_checks": [],
        "diagnostics": {"run_id": "run-1"},
        "metrics": {
            "published_commands": 500_000,
            "result_match_rate_pct": 99.9,
            "instance_coverage_count": 3,
            "publish_success_rate_pct": 100.0,
        },
    }
    load_report = {
        "status": "pass",
        "failed_checks": [],
        "metrics": {
            "p1_19_sustained_command_throughput_cmds_per_sec": 61.0,
            "p1_19_command_latency_under_load_p95_ms": 220.0,
            "p1_19_command_latency_under_load_p99_ms": 410.0,
            "p1_19_stream_backlog_growth_rate_pct_per_10min": 0.2,
            "p1_19_stress_window_oom_restart_count": 0.0,
            "p1_19_command_instance_coverage_count": 3.0,
            "p1_19_sustained_window_observed_sec": 7210.0,
            "p1_19_sustained_window_required_sec": 7200.0,
            "p1_19_sustained_window_qualification_rate_pct": 100.0,
        },
        "diagnostics": {
            "load_run_id": "run-1",
            "budget_checks_enforced": True,
            "budget_failed_checks": [],
        },
    }
    report = build_report(
        profile=profile,
        harness_rc=0,
        load_rc=0,
        harness_report=harness_report,
        load_report=load_report,
    )
    assert report["status"] == "pass"
    assert report["failed_checks"] == []
    checks = report["checks"]
    assert checks["run_id_propagation"] is True
    assert checks["sustained_window_qualified"] is True
    assert checks["minimum_instance_coverage"] is True


def test_build_report_fails_closed_when_sustained_window_not_qualified() -> None:
    profile = {"min_instance_coverage": 3}
    harness_report = {"status": "pass", "diagnostics": {"run_id": "run-1"}, "failed_checks": []}
    load_report = {
        "status": "warning",
        "failed_checks": ["minimum_sustained_window_seconds"],
        "metrics": {
            "p1_19_command_instance_coverage_count": 1.0,
            "p1_19_sustained_window_qualification_rate_pct": 0.0,
        },
        "diagnostics": {
            "load_run_id": "run-x",
            "budget_checks_enforced": False,
            "budget_failed_checks": ["minimum_sustained_window_seconds"],
        },
    }
    report = build_report(
        profile=profile,
        harness_rc=0,
        load_rc=2,
        harness_report=harness_report,
        load_report=load_report,
    )
    assert report["status"] == "fail"
    assert "load_validation_pass" in report["failed_checks"]
    assert "run_id_propagation" in report["failed_checks"]
    assert "budget_checks_enforced" in report["failed_checks"]
    assert "sustained_window_qualified" in report["failed_checks"]
    assert "minimum_instance_coverage" in report["failed_checks"]


def test_build_report_accepts_harness_when_only_result_match_fails() -> None:
    profile = {
        "min_instance_coverage": 3,
        "min_commands": 100,
        "min_publish_success_rate_pct": 99.0,
    }
    harness_report = {
        "status": "fail",
        "failed_checks": ["result_match_rate"],
        "diagnostics": {"run_id": "run-1"},
        "metrics": {
            "published_commands": 120,
            "instance_coverage_count": 3,
            "publish_success_rate_pct": 100.0,
            "result_match_rate_pct": 20.0,
        },
    }
    load_report = {
        "status": "pass",
        "failed_checks": [],
        "metrics": {
            "p1_19_command_instance_coverage_count": 3.0,
            "p1_19_sustained_window_qualification_rate_pct": 100.0,
        },
        "diagnostics": {
            "load_run_id": "run-1",
            "budget_checks_enforced": True,
            "budget_failed_checks": [],
        },
    }
    report = build_report(
        profile=profile,
        harness_rc=2,
        load_rc=0,
        harness_report=harness_report,
        load_report=load_report,
    )
    assert report["status"] == "pass"
    assert report["checks"]["harness_pass"] is True
    assert report["diagnostics"]["harness_only_result_match_failure"] is True
