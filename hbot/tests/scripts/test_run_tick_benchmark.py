from __future__ import annotations

from pathlib import Path

from scripts.release.run_tick_benchmark import run


def test_benchmark_produces_artifact(tmp_path: Path) -> None:
    report = run(tmp_path, iterations=50)
    assert report["status"] == "pass"
    assert report["iterations"] == 50
    assert report["total"]["samples"] == 50
    assert report["total"]["p99_ms"] > 0
    artifact = tmp_path / "reports" / "verification" / "tick_benchmark_latest.json"
    assert artifact.exists()
    for key in ("snapshot_build", "spread_compute", "json_serialize", "csv_format", "total"):
        assert key in report
        assert report[key]["samples"] == 50


def test_benchmark_fail_threshold(tmp_path: Path) -> None:
    report = run(tmp_path, iterations=10, fail_total_p99_ms=0.00001)
    assert report["status"] == "fail"


def test_benchmark_warn_threshold(tmp_path: Path) -> None:
    report = run(tmp_path, iterations=10, warn_total_p99_ms=0.00001, fail_total_p99_ms=999.0)
    assert report["status"] == "warn"
