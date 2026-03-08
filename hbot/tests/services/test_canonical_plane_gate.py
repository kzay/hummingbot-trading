from __future__ import annotations

import json
from pathlib import Path

from scripts.release.check_canonical_plane_gate import (
    _count_event_jsonl,
    _duplicate_suppression_metrics,
    _max_replay_lag_from_day2,
    _parity_delta_ratio,
    run,
)


def test_duplicate_suppression_metrics_reports_full_suppression_without_duplicates() -> None:
    metrics = _duplicate_suppression_metrics(total_source=100, unique_source=100, db_event_count=100)
    assert metrics["source_duplicate_events"] == 0.0
    assert metrics["db_retained_duplicates"] == 0.0
    assert metrics["duplicate_suppression_rate"] == 1.0


def test_duplicate_suppression_metrics_detects_unsuppressed_duplicates() -> None:
    metrics = _duplicate_suppression_metrics(total_source=120, unique_source=100, db_event_count=105)
    assert metrics["source_duplicate_events"] == 20.0
    assert metrics["db_retained_duplicates"] == 5.0
    assert metrics["duplicate_suppression_rate"] == 0.75


def test_parity_delta_ratio_uses_safe_denominator() -> None:
    assert _parity_delta_ratio(db_count=5, csv_count=0) == 5.0


def test_count_event_jsonl_counts_unique_keys(tmp_path: Path) -> None:
    events = tmp_path / "events_20260302.jsonl"
    events.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "stream": "hb.market_data.v1",
                        "stream_entry_id": "1-0",
                        "ts_utc": "2026-03-02T00:00:00+00:00",
                    }
                ),
                json.dumps(
                    {
                        "stream": "hb.market_data.v1",
                        "stream_entry_id": "1-0",
                        "ts_utc": "2026-03-02T00:00:00+00:00",
                    }
                ),
                json.dumps(
                    {
                        "stream": "hb.market_data.v1",
                        "stream_entry_id": "2-0",
                        "ts_utc": "2026-03-02T00:00:01+00:00",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    total, unique = _count_event_jsonl([events])
    assert total == 3
    assert unique == 2


def test_max_replay_lag_prefers_day2_lag_diagnostics(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    value = _max_replay_lag_from_day2({"lag_diagnostics": {"max_delta_observed": 7}}, reports)
    assert value == 7


def test_max_replay_lag_falls_back_to_source_compare(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    event_store = reports / "event_store"
    event_store.mkdir(parents=True, exist_ok=True)
    source_compare = event_store / "source_compare_20260302T000000Z.json"
    source_compare.write_text(
        json.dumps(
            {
                "delta_produced_minus_ingested_since_baseline": {
                    "hb.market_data.v1": 2,
                    "hb.signal.v1": -9,
                }
            }
        ),
        encoding="utf-8",
    )
    value = _max_replay_lag_from_day2({"source_compare_file": str(source_compare)}, reports)
    assert value == 2


def test_canonical_plane_gate_fails_without_nonzero_evidence(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    reports = root / "reports"
    (reports / "ops_db_writer").mkdir(parents=True, exist_ok=True)
    (reports / "event_store").mkdir(parents=True, exist_ok=True)
    (reports / "ops_db_writer" / "latest.json").write_text(
        json.dumps({"ts_utc": "2026-03-05T00:00:00Z", "status": "pass"}),
        encoding="utf-8",
    )
    (reports / "event_store" / "day2_gate_eval_latest.json").write_text(
        json.dumps({"lag_diagnostics": {"max_delta_observed": 0}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.release.check_canonical_plane_gate._fetch_db_counts",
        lambda: {"minute": 0, "fills": 0, "events": 0},
    )
    payload = run(
        root=root,
        data_root=root / "data",
        reports_root=reports,
        max_db_ingest_age_min=10.0,
        max_parity_delta_ratio=0.1,
        min_duplicate_suppression_rate=0.99,
        max_replay_lag_delta=5,
    )
    checks = {item["name"]: item for item in payload["checks"]}
    assert payload["status"] == "FAIL"
    assert checks["nonzero_ingestion_evidence"]["pass"] is False
