from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.release.check_paper_exchange_thresholds import (
    build_report,
    default_pass_metrics,
)


def test_build_report_passes_with_complete_metric_payload(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
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
    now = datetime.now(timezone.utc)
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


def test_build_report_fails_when_input_is_stale(tmp_path: Path) -> None:
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    payload = {
        "ts_utc": stale.isoformat(),
        "metrics": default_pass_metrics(),
    }
    report = build_report(
        tmp_path,
        now_ts=datetime.now(timezone.utc).timestamp(),
        max_input_age_min=20.0,
        require_input_fresh=True,
        inputs_payload=payload,
    )
    assert report["status"] == "fail"
    assert "input_artifact_fresh" in report["failed_checks"]

