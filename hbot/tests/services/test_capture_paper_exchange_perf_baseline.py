from __future__ import annotations

import json
from pathlib import Path

from scripts.release.capture_paper_exchange_perf_baseline import build_report


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_build_report_passes_with_complete_source_metrics(tmp_path: Path) -> None:
    source_path = tmp_path / "reports" / "verification" / "paper_exchange_load_latest.json"
    _write_json(
        source_path,
        {
            "ts_utc": "2026-03-04T00:00:00+00:00",
            "status": "pass",
            "metrics": {
                "p1_19_sustained_command_throughput_cmds_per_sec": 60.0,
                "p1_19_command_latency_under_load_p95_ms": 200.0,
                "p1_19_command_latency_under_load_p99_ms": 400.0,
                "p1_19_stream_backlog_growth_rate_pct_per_10min": 0.2,
                "p1_19_stress_window_oom_restart_count": 0.0,
            },
        },
    )

    report = build_report(tmp_path, source_report_path=source_path, profile_label="sustained_2h")
    assert report["status"] == "pass"
    assert report["failed_checks"] == []
    metrics = report["metrics"]
    assert float(metrics["p1_19_sustained_command_throughput_cmds_per_sec"]) == 60.0
    assert report["diagnostics"]["profile_label"] == "sustained_2h"


def test_build_report_fails_when_required_metric_missing(tmp_path: Path) -> None:
    source_path = tmp_path / "reports" / "verification" / "paper_exchange_load_latest.json"
    _write_json(
        source_path,
        {
            "ts_utc": "2026-03-04T00:00:00+00:00",
            "status": "pass",
            "metrics": {
                "p1_19_sustained_command_throughput_cmds_per_sec": 60.0,
                "p1_19_command_latency_under_load_p95_ms": 200.0,
                # p99 metric missing on purpose
                "p1_19_stream_backlog_growth_rate_pct_per_10min": 0.2,
                "p1_19_stress_window_oom_restart_count": 0.0,
            },
        },
    )

    report = build_report(tmp_path, source_report_path=source_path)
    assert report["status"] == "fail"
    assert "required_metrics_present" in report["failed_checks"]
    missing = report["diagnostics"]["missing_metrics"]
    assert "p1_19_command_latency_under_load_p99_ms" in missing


def test_build_report_can_skip_source_pass_requirement(tmp_path: Path) -> None:
    source_path = tmp_path / "reports" / "verification" / "paper_exchange_load_latest.json"
    _write_json(
        source_path,
        {
            "ts_utc": "2026-03-04T00:00:00+00:00",
            "status": "warning",
            "metrics": {
                "p1_19_sustained_command_throughput_cmds_per_sec": 60.0,
                "p1_19_command_latency_under_load_p95_ms": 200.0,
                "p1_19_command_latency_under_load_p99_ms": 400.0,
                "p1_19_stream_backlog_growth_rate_pct_per_10min": 0.2,
                "p1_19_stress_window_oom_restart_count": 0.0,
            },
        },
    )

    report = build_report(tmp_path, source_report_path=source_path, require_source_pass=False)
    assert report["status"] == "pass"
    assert "source_report_pass" not in report["failed_checks"]
