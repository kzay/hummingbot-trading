from __future__ import annotations

import json
import time
from pathlib import Path

from scripts.release.check_realtime_l2_data_quality import run


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row) + "\n")


def test_realtime_l2_data_quality_passes_with_clean_stream(tmp_path: Path) -> None:
    root = tmp_path
    reports = root / "reports"
    _write_json(
        reports / "event_store" / "integrity_20260305.json",
        {
            "total_events": 10,
            "events_by_stream": {"hb.market_depth.v1": 4, "hb.market_data.v1": 6},
        },
    )
    now_ms = int(time.time() * 1000)
    _write_jsonl(
        reports / "event_store" / "events_20260305.jsonl",
        [
            {
                "stream": "hb.market_depth.v1",
                "stream_entry_id": f"{now_ms}-0",
                "instance_name": "bot1",
                "controller_id": "ctrl",
                "trading_pair": "BTC-USDT",
                "payload": {"market_sequence": 10, "bids": [{"price": 100, "size": 1}], "asks": [{"price": 101, "size": 1}]},
            },
            {
                "stream": "hb.market_depth.v1",
                "stream_entry_id": f"{now_ms + 100}-0",
                "instance_name": "bot1",
                "controller_id": "ctrl",
                "trading_pair": "BTC-USDT",
                "payload": {"market_sequence": 11, "bids": [{"price": 100, "size": 1}], "asks": [{"price": 101, "size": 1}]},
            },
        ],
    )
    _write_json(
        reports / "ops_db_writer" / "latest.json",
        {"counts": {"market_depth": {"raw_inserted": 20, "sampled_inserted": 5}}},
    )

    rc, report = run(
        root=root,
        max_age_sec=3600,
        max_sequence_gap=50,
        min_sampled_events=1,
        max_raw_to_sampled_ratio=100.0,
        max_depth_stream_share=0.95,
        max_depth_event_bytes=4000,
        lookback_depth_events=1000,
    )
    assert rc == 0
    assert report["status"] == "pass"


def test_realtime_l2_data_quality_fails_on_sequence_regression(tmp_path: Path) -> None:
    root = tmp_path
    reports = root / "reports"
    _write_json(
        reports / "event_store" / "integrity_20260305.json",
        {
            "total_events": 4,
            "events_by_stream": {"hb.market_depth.v1": 2, "hb.market_data.v1": 2},
        },
    )
    now_ms = int(time.time() * 1000)
    _write_jsonl(
        reports / "event_store" / "events_20260305.jsonl",
        [
            {
                "stream": "hb.market_depth.v1",
                "stream_entry_id": f"{now_ms}-0",
                "instance_name": "bot1",
                "controller_id": "ctrl",
                "trading_pair": "BTC-USDT",
                "payload": {"market_sequence": 20, "bids": [{"price": 100, "size": 1}], "asks": [{"price": 101, "size": 1}]},
            },
            {
                "stream": "hb.market_depth.v1",
                "stream_entry_id": f"{now_ms + 100}-0",
                "instance_name": "bot1",
                "controller_id": "ctrl",
                "trading_pair": "BTC-USDT",
                "payload": {"market_sequence": 19, "bids": [{"price": 100, "size": 1}], "asks": [{"price": 101, "size": 1}]},
            },
        ],
    )
    _write_json(
        reports / "ops_db_writer" / "latest.json",
        {"counts": {"market_depth": {"raw_inserted": 2, "sampled_inserted": 1}}},
    )

    rc, report = run(
        root=root,
        max_age_sec=3600,
        max_sequence_gap=50,
        min_sampled_events=1,
        max_raw_to_sampled_ratio=100.0,
        max_depth_stream_share=0.95,
        max_depth_event_bytes=4000,
        lookback_depth_events=1000,
    )
    assert rc == 1
    assert report["status"] == "fail"
    sequence_checks = [c for c in report["checks"] if c["name"] == "sequence_integrity"]
    assert sequence_checks and sequence_checks[0]["pass"] is False


def test_realtime_l2_data_quality_fails_on_duplicate_sequence_values(tmp_path: Path) -> None:
    root = tmp_path
    reports = root / "reports"
    _write_json(
        reports / "event_store" / "integrity_20260305.json",
        {
            "total_events": 4,
            "events_by_stream": {"hb.market_depth.v1": 2, "hb.market_data.v1": 2},
        },
    )
    now_ms = int(time.time() * 1000)
    _write_jsonl(
        reports / "event_store" / "events_20260305.jsonl",
        [
            {
                "stream": "hb.market_depth.v1",
                "stream_entry_id": f"{now_ms}-0",
                "instance_name": "bot1",
                "controller_id": "ctrl",
                "trading_pair": "BTC-USDT",
                "payload": {"market_sequence": 20, "bids": [{"price": 100, "size": 1}], "asks": [{"price": 101, "size": 1}]},
            },
            {
                "stream": "hb.market_depth.v1",
                "stream_entry_id": f"{now_ms + 100}-0",
                "instance_name": "bot1",
                "controller_id": "ctrl",
                "trading_pair": "BTC-USDT",
                "payload": {"market_sequence": 20, "bids": [{"price": 100, "size": 1}], "asks": [{"price": 101, "size": 1}]},
            },
        ],
    )
    _write_json(
        reports / "ops_db_writer" / "latest.json",
        {"counts": {"market_depth": {"raw_inserted": 2, "sampled_inserted": 1}}},
    )

    rc, report = run(
        root=root,
        max_age_sec=3600,
        max_sequence_gap=50,
        min_sampled_events=1,
        max_raw_to_sampled_ratio=100.0,
        max_depth_stream_share=0.95,
        max_depth_event_bytes=4000,
        lookback_depth_events=1000,
    )
    assert rc == 1
    assert report["status"] == "fail"
    sequence_checks = [c for c in report["checks"] if c["name"] == "sequence_integrity"]
    assert sequence_checks and sequence_checks[0]["pass"] is False


def test_realtime_l2_data_quality_fails_without_depth_db_evidence(tmp_path: Path) -> None:
    root = tmp_path
    reports = root / "reports"
    _write_json(
        reports / "event_store" / "integrity_20260305.json",
        {
            "total_events": 0,
            "events_by_stream": {"hb.market_depth.v1": 0, "hb.market_data.v1": 0},
        },
    )
    _write_json(
        reports / "ops_db_writer" / "latest.json",
        {"counts": {"market_depth": {"raw_inserted": 0, "sampled_inserted": 0}}},
    )

    rc, report = run(
        root=root,
        max_age_sec=3600,
        max_sequence_gap=50,
        min_sampled_events=1,
        max_raw_to_sampled_ratio=100.0,
        max_depth_stream_share=0.95,
        max_depth_event_bytes=4000,
        lookback_depth_events=1000,
    )
    assert rc == 1
    assert report["status"] == "fail"
    sampling_checks = [c for c in report["checks"] if c["name"] == "sampling_coverage"]
    assert sampling_checks and sampling_checks[0]["pass"] is False
