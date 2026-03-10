from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.release.check_runtime_performance_budgets import run


def test_runtime_performance_budgets_report_passes_with_fresh_samples(tmp_path: Path, monkeypatch) -> None:
    minute_dir = tmp_path / "data" / "bot1" / "logs" / "epp_v24" / "bot1_a"
    minute_dir.mkdir(parents=True, exist_ok=True)
    minute_dir.joinpath("minute.csv").write_text(
        "\n".join(
            [
                "ts,_tick_duration_ms,_indicator_duration_ms,_connector_io_duration_ms,equity_quote,bot_variant,bot_mode,accounting_source,exchange,trading_pair,state,regime",
                "2026-03-09T12:00:00+00:00,100,20,10,1000,a,paper,paper_desk_v2,bitget_perpetual,BTC-USDT,running,neutral",
                "2026-03-09T12:01:00+00:00,120,25,15,1000,a,paper,paper_desk_v2,bitget_perpetual,BTC-USDT,running,neutral",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    reports_event_store = tmp_path / "reports" / "event_store"
    reports_event_store.mkdir(parents=True, exist_ok=True)
    reports_event_store.joinpath("integrity_20260309.json").write_text(
        json.dumps({"ingest_duration_ms_recent": [20.0, 30.0, 40.0]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.release.check_runtime_performance_budgets._measure_exporter_render",
        lambda data_root, samples: {"samples": 5.0, "p50_ms": 50.0, "p95_ms": 60.0, "p99_ms": 70.0, "max_ms": 75.0},
    )

    report = run(
        tmp_path,
        exporter_render_samples=5,
        max_controller_tick_p95_ms=250.0,
        max_exporter_render_p95_ms=500.0,
        max_event_store_ingest_p95_ms=250.0,
    )

    assert report["status"] == "pass"
    assert report["controller_tick_ms"]["samples"] == 2.0
    assert report["exporter_render_ms"]["p95_ms"] == 60.0
    assert report["event_store_ingest_ms"]["p95_ms"] > 0.0
    assert (tmp_path / "reports" / "verification" / "runtime_performance_budgets_latest.json").exists()


def test_runtime_performance_budgets_report_fails_when_controller_source_is_stale(tmp_path: Path, monkeypatch) -> None:
    minute_dir = tmp_path / "data" / "bot1" / "logs" / "epp_v24" / "bot1_a"
    minute_dir.mkdir(parents=True, exist_ok=True)
    minute_file = minute_dir / "minute.csv"
    minute_file.write_text(
        "\n".join(
            [
                "ts,_tick_duration_ms,_indicator_duration_ms,_connector_io_duration_ms,equity_quote",
                "2026-03-09T12:00:00+00:00,100,20,10,1000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    stale_epoch = 1_700_000_000
    os.utime(minute_file, (stale_epoch, stale_epoch))
    reports_event_store = tmp_path / "reports" / "event_store"
    reports_event_store.mkdir(parents=True, exist_ok=True)
    reports_event_store.joinpath("integrity_20260309.json").write_text(
        json.dumps({"ingest_duration_ms_recent": [20.0, 30.0, 40.0]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.release.check_runtime_performance_budgets._measure_exporter_render",
        lambda data_root, samples: {"samples": 5.0, "p50_ms": 50.0, "p95_ms": 60.0, "p99_ms": 70.0, "max_ms": 75.0},
    )
    monkeypatch.setattr(
        "scripts.release.check_runtime_performance_budgets._minutes_since_file_mtime",
        lambda path: 999.0 if path == minute_file else 0.0,
    )

    report = run(
        tmp_path,
        exporter_render_samples=5,
        max_controller_tick_p95_ms=250.0,
        max_exporter_render_p95_ms=500.0,
        max_event_store_ingest_p95_ms=250.0,
        max_source_age_min=20.0,
    )

    assert report["status"] == "fail"
    failed = {check["name"] for check in report["checks"] if not check["pass"]}
    assert "controller_source_fresh" in failed
    assert "controller_source" in report["diagnostics"]["stale_sources"]


def test_runtime_performance_budgets_report_fails_when_tick_budget_exceeded(tmp_path: Path, monkeypatch) -> None:
    minute_dir = tmp_path / "data" / "bot1" / "logs" / "epp_v24" / "bot1_a"
    minute_dir.mkdir(parents=True, exist_ok=True)
    minute_dir.joinpath("minute.csv").write_text(
        "\n".join(
            [
                "ts,_tick_duration_ms,_indicator_duration_ms,_connector_io_duration_ms,equity_quote,bot_variant,bot_mode,accounting_source,exchange,trading_pair,state,regime",
                "2026-03-09T12:00:00+00:00,900,20,10,1000,a,paper,paper_desk_v2,bitget_perpetual,BTC-USDT,running,neutral",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    reports_event_store = tmp_path / "reports" / "event_store"
    reports_event_store.mkdir(parents=True, exist_ok=True)
    reports_event_store.joinpath("integrity_20260309.json").write_text(
        json.dumps({"ingest_duration_ms_recent": [20.0, 30.0, 40.0]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.release.check_runtime_performance_budgets._measure_exporter_render",
        lambda data_root, samples: {"samples": 5.0, "p50_ms": 50.0, "p95_ms": 60.0, "p99_ms": 70.0, "max_ms": 75.0},
    )

    report = run(
        tmp_path,
        exporter_render_samples=5,
        max_controller_tick_p95_ms=250.0,
        max_exporter_render_p95_ms=500.0,
        max_event_store_ingest_p95_ms=250.0,
    )

    assert report["status"] == "fail"
    failed = {check["name"] for check in report["checks"] if not check["pass"]}
    assert "controller_tick_p95_budget" in failed
