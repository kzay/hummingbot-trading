from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.release.check_paper_exchange_perf_regression import build_report


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_payload(*, status: str, throughput: float, p95: float, p99: float, backlog: float, restart: float) -> dict:
    return {
        "ts_utc": datetime.now(UTC).isoformat(),
        "status": status,
        "metrics": {
            "p1_19_sustained_command_throughput_cmds_per_sec": throughput,
            "p1_19_command_latency_under_load_p95_ms": p95,
            "p1_19_command_latency_under_load_p99_ms": p99,
            "p1_19_stream_backlog_growth_rate_pct_per_10min": backlog,
            "p1_19_stress_window_oom_restart_count": restart,
        },
    }


def test_build_report_passes_when_regression_within_budget(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_load_latest.json",
        _load_payload(status="pass", throughput=54.0, p95=110.0, p99=220.0, backlog=0.55, restart=0.0),
    )
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_load_baseline_latest.json",
        _load_payload(status="pass", throughput=60.0, p95=100.0, p99=200.0, backlog=0.50, restart=0.0),
    )

    report = build_report(tmp_path)
    assert report["status"] == "pass"
    assert report["failed_checks"] == []
    assert report["waiver"]["applied"] is False


def test_build_report_fails_without_valid_waiver(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_load_latest.json",
        _load_payload(status="pass", throughput=40.0, p95=180.0, p99=320.0, backlog=1.20, restart=1.0),
    )
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_load_baseline_latest.json",
        _load_payload(status="pass", throughput=60.0, p95=100.0, p99=200.0, backlog=0.50, restart=0.0),
    )

    report = build_report(tmp_path)
    assert report["status"] == "fail"
    failed_checks = set(report["failed_checks"])
    assert "throughput_within_budget" in failed_checks
    assert "latency_p95_within_budget" in failed_checks
    assert "latency_p99_within_budget" in failed_checks
    assert "backlog_within_budget" in failed_checks
    assert "restart_within_budget" in failed_checks
    assert report["waiver"]["applied"] is False


def test_build_report_applies_valid_time_bounded_waiver(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_load_latest.json",
        _load_payload(status="pass", throughput=40.0, p95=180.0, p99=320.0, backlog=1.20, restart=1.0),
    )
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_load_baseline_latest.json",
        _load_payload(status="pass", throughput=60.0, p95=100.0, p99=200.0, backlog=0.50, restart=0.0),
    )
    now = datetime.now(UTC)
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_perf_regression_waiver_latest.json",
        {
            "status": "approved",
            "reason": "temporary infra maintenance window",
            "approved_by": "ops_lead",
            "change_ticket": "CHG-9090",
            "created_ts_utc": now.isoformat(),
            "expires_at_utc": (now + timedelta(hours=2)).isoformat(),
        },
    )

    report = build_report(tmp_path, max_waiver_hours=24.0)
    assert report["status"] == "waived"
    assert report["waiver"]["valid"] is True
    assert report["waiver"]["applied"] is True

