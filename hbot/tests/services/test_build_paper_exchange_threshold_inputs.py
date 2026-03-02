from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.release.build_paper_exchange_threshold_inputs import build_report


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_build_report_merges_computed_and_manual_metrics(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    _write_json(
        tmp_path / "reports" / "parity" / "latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "bots": [
                {
                    "bot": "bot1",
                    "summary": {"equity_first": 100.0, "equity_last": 101.0},
                    "metrics": [
                        {"metric": "fill_ratio_delta", "delta": 0.5},
                        {"metric": "reject_rate_delta", "delta": 0.1},
                        {"metric": "slippage_delta_bps", "delta": 1.2},
                    ],
                }
            ],
        },
    )
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {
                "heartbeat_bot1_fresh": True,
                "redis_connected": True,
                "dead_letter_critical_within_slo": True,
            },
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(
        tmp_path / "reports" / "tests" / "latest.json",
        {"ts_utc": now_iso, "status": "pass"},
    )
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {
            "ts_utc": now_iso,
            "status": "PASS",
            "checks": [
                {"name": "paper_exchange_preflight", "pass": True},
                {"name": "paper_exchange_thresholds", "pass": True},
            ],
        },
    )
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json",
        {"ts_utc": now_iso, "strict_gate_rc": 0},
    )
    manual_path = tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json"
    _write_json(
        manual_path,
        {
            "metrics": {
                "p1_8_command_latency_p95_ms": 111.0,
                "p1_8_command_latency_p99_ms": 222.0,
            }
        },
    )

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=manual_path,
    )

    assert report["status"] == "warning"  # expected: unresolved metrics still exist.
    metrics = report["metrics"]
    assert float(metrics["p0_1_contract_tests_pass_rate_pct"]) == 100.0
    assert float(metrics["p1_17_strict_cycle_checks_enforced_rate_pct"]) == 100.0
    assert float(metrics["p1_8_command_latency_p95_ms"]) == 111.0
    assert float(metrics["p1_8_command_latency_p99_ms"]) == 222.0


def test_build_report_marks_stale_sources(tmp_path: Path) -> None:
    stale_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _write_json(
        tmp_path / "reports" / "parity" / "latest.json",
        {"ts_utc": stale_iso, "status": "pass", "bots": []},
    )
    report = build_report(
        tmp_path,
        now_ts=datetime.now(timezone.utc).timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json",
    )
    stale_sources = report["diagnostics"]["stale_sources"]
    assert "parity_latest" in stale_sources


def test_build_report_derives_privileged_command_metrics_from_journal(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"ts_utc": now_iso, "status": "pass", "bots": []})
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json",
        {
            "ts_utc": now_iso,
            "commands": {
                "cmd-1": {
                    "command": "cancel_all",
                    "audit_required": True,
                    "audit_published": True,
                    "command_metadata": {
                        "operator": "desk_ops",
                        "reason": "risk_pause",
                        "change_ticket": "CHG-1",
                        "trace_id": "trace-1",
                    },
                },
                "cmd-2": {
                    "command": "cancel_all",
                    "audit_required": True,
                    "audit_published": False,
                    "command_metadata": {
                        "operator": "desk_ops",
                        "reason": "risk_pause",
                        "change_ticket": "CHG-2",
                        "trace_id": "",
                    },
                },
            },
        },
    )

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json",
    )
    metrics = report["metrics"]
    assert float(metrics["p1_20_privileged_command_attribution_complete_rate_pct"]) == 50.0
    assert float(metrics["p1_20_privileged_command_missing_audit_event_rate_pct"]) == 50.0
    assert float(metrics["p1_20_security_policy_test_suite_pass_rate_pct"]) == 100.0


def test_build_report_ingests_load_backpressure_metrics(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"ts_utc": now_iso, "status": "pass", "bots": []})
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {
            "ts_utc": now_iso,
            "status": "PASS",
            "checks": [
                {"name": "paper_exchange_preflight", "pass": True},
                {"name": "paper_exchange_thresholds", "pass": True},
            ],
        },
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_load_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "metrics": {
                "p1_19_sustained_command_throughput_cmds_per_sec": 63.2,
                "p1_19_command_latency_under_load_p95_ms": 112.0,
                "p1_19_command_latency_under_load_p99_ms": 229.0,
                "p1_19_stream_backlog_growth_rate_pct_per_10min": 0.2,
                "p1_19_stress_window_oom_restart_count": 0.0,
            },
        },
    )
    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json",
    )
    metrics = report["metrics"]
    assert float(metrics["p1_19_sustained_command_throughput_cmds_per_sec"]) == 63.2
    assert float(metrics["p1_19_command_latency_under_load_p95_ms"]) == 112.0
    assert float(metrics["p1_19_command_latency_under_load_p99_ms"]) == 229.0
    assert float(metrics["p1_19_stream_backlog_growth_rate_pct_per_10min"]) == 0.2
    assert float(metrics["p1_19_stress_window_oom_restart_count"]) == 0.0

