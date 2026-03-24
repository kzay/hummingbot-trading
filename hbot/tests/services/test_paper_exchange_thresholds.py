from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.release.check_paper_exchange_thresholds import (
    build_report,
    default_pass_metrics,
)


def test_build_report_passes_with_complete_metric_payload(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    payload = {
        "ts_utc": now.isoformat(),
        "metrics": default_pass_metrics(),
    }
    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_input_age_min=20.0,
        require_input_fresh=True,
        inputs_payload=payload,
    )
    assert report["status"] == "pass"
    assert report["failed_checks"] == []
    failed_items = report["evaluation"]["failed_items"]
    assert failed_items == []


def test_build_report_fails_on_threshold_breach(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    metrics = default_pass_metrics()
    metrics["p1_8_command_latency_p95_ms"] = 999.0  # breach: must be <= 250
    payload = {
        "ts_utc": now.isoformat(),
        "metrics": metrics,
    }
    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_input_age_min=20.0,
        require_input_fresh=True,
        inputs_payload=payload,
    )
    assert report["status"] == "fail"
    assert "all_item_thresholds_passed" in report["failed_checks"]
    failed_items = report["evaluation"]["failed_items"]
    assert "P1-PAPER-SVC-20260301-8" in failed_items
    clause_rows = report["evaluation"]["clause_results"]
    clause_by_metric = {str(row.get("metric", "")): row for row in clause_rows if isinstance(row, dict)}
    assert clause_by_metric["p1_8_command_latency_p95_ms"]["source_artifacts"] == ["reliability_slo_latest"]
    failed_sources = report["evaluation"]["summary"]["failed_clause_sources"]
    assert failed_sources["p1_8_command_latency_p95_ms"] == ["reliability_slo_latest"]


def test_build_report_fails_when_input_is_stale(tmp_path: Path) -> None:
    stale = datetime.now(UTC) - timedelta(hours=2)
    payload = {
        "ts_utc": stale.isoformat(),
        "metrics": default_pass_metrics(),
    }
    report = build_report(
        tmp_path,
        now_ts=datetime.now(UTC).timestamp(),
        max_input_age_min=20.0,
        require_input_fresh=True,
        inputs_payload=payload,
    )
    assert report["status"] == "fail"
    assert "input_artifact_fresh" in report["failed_checks"]


def test_build_report_fails_when_missing_metric_clause(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    metrics = default_pass_metrics()
    metrics.pop("p1_8_command_latency_p95_ms", None)
    payload = {
        "ts_utc": now.isoformat(),
        "metrics": metrics,
    }
    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_input_age_min=20.0,
        require_input_fresh=True,
        inputs_payload=payload,
    )
    assert report["status"] == "fail"
    assert "no_missing_metric_clauses" in report["failed_checks"]
    assert "input_metrics_resolved" in report["failed_checks"]


def test_build_report_fails_when_input_diagnostics_sources_not_ready(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    payload = {
        "ts_utc": now.isoformat(),
        "metrics": default_pass_metrics(),
        "diagnostics": {
            "unresolved_metric_count": 0,
            "stale_sources": ["parity_latest"],
            "missing_sources": [],
        },
    }
    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_input_age_min=20.0,
        require_input_fresh=True,
        inputs_payload=payload,
    )
    assert report["status"] == "fail"
    assert "input_source_artifacts_ready" in report["failed_checks"]


def test_build_report_fails_when_blocking_metrics_are_manual(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    payload = {
        "ts_utc": now.isoformat(),
        "metrics": default_pass_metrics(),
        "diagnostics": {
            "unresolved_metric_count": 0,
            "stale_sources": [],
            "missing_sources": [],
            "manual_metrics_blocking_count": 2,
        },
    }
    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_input_age_min=20.0,
        require_input_fresh=True,
        inputs_payload=payload,
    )
    assert report["status"] == "fail"
    assert "blocking_metrics_computed" in report["failed_checks"]

