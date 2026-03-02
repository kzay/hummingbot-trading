from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.release.check_reliability_slo import _dead_letter_stats, build_report


class _FakeRedis:
    def __init__(self, groups, dead_rows):
        self._groups = groups
        self._dead_rows = dead_rows

    def execute_command(self, *args, **kwargs):
        return self._groups

    def xrevrange(self, *args, **kwargs):
        return self._dead_rows


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_dead_letter_stats_marks_local_authority_reject_as_non_critical() -> None:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    rows = [
        (
            "1-0",
            {
                "payload": json.dumps(
                    {
                        "timestamp_ms": now_ms,
                        "reason": "local_authority_reject",
                    }
                )
            },
        ),
        (
            "2-0",
            {
                "payload": json.dumps(
                    {
                        "timestamp_ms": now_ms,
                        "reason": "controller_not_found",
                    }
                )
            },
        ),
    ]
    stats = _dead_letter_stats(
        rows,
        now_ms=now_ms,
        lookback_sec=300,
        non_critical_reasons=["local_authority_reject"],
    )
    assert stats["in_lookback_window"] == 2
    assert stats["critical_count"] == 1
    assert stats["reason_counts"] == {
        "local_authority_reject": 1,
        "controller_not_found": 1,
    }


def test_dead_letter_stats_marks_expired_intent_as_non_critical_when_configured() -> None:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    rows = [
        (
            "1-0",
            {
                "payload": json.dumps(
                    {
                        "timestamp_ms": now_ms,
                        "reason": "expired_intent",
                    }
                )
            },
        ),
        (
            "2-0",
            {
                "payload": json.dumps(
                    {
                        "timestamp_ms": now_ms,
                        "reason": "controller_not_found",
                    }
                )
            },
        ),
    ]
    stats = _dead_letter_stats(
        rows,
        now_ms=now_ms,
        lookback_sec=300,
        non_critical_reasons=["local_authority_reject", "expired_intent"],
    )
    assert stats["in_lookback_window"] == 2
    assert stats["critical_count"] == 1
    assert stats["reason_counts"] == {
        "expired_intent": 1,
        "controller_not_found": 1,
    }


def test_build_report_passes_when_all_slos_are_healthy(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()
    now_iso = now.isoformat()

    _write_json(
        tmp_path / "data" / "bot1" / "logs" / "heartbeat" / "strategy_heartbeat.json",
        {"ts_utc": now_iso, "reason": "tick_end"},
    )
    _write_json(
        tmp_path / "reports" / "exchange_snapshots" / "latest.json",
        {"ts_utc": now_iso, "bots": {"bot1": {"equity_quote": 100.0}}},
    )

    fake_redis = _FakeRedis(
        groups=[["name", "hb_group_bot1", "pending", 0, "lag", 0]],
        dead_rows=[],
    )
    report = build_report(
        tmp_path,
        now_ts=now_ts,
        redis_client=fake_redis,
        bots=["bot1"],
        required_groups=["hb_group_bot1"],
        lookback_sec=300,
        max_critical_dead_letters=0,
        max_group_lag=0,
        max_group_pending=0,
        heartbeat_max_age_s=120,
        snapshot_max_age_s=120,
    )

    assert report["status"] == "pass"
    checks = report["checks"]
    assert checks["heartbeat_bot1_present"] is True
    assert checks["heartbeat_bot1_fresh"] is True
    assert checks["exchange_snapshot_fresh"] is True
    assert checks["redis_groups_lag_within_slo"] is True
    assert checks["dead_letter_critical_within_slo"] is True


def test_build_report_defaults_expired_intent_to_non_critical(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()
    now_iso = now.isoformat()
    now_ms = int(now_ts * 1000)

    _write_json(
        tmp_path / "data" / "bot1" / "logs" / "heartbeat" / "strategy_heartbeat.json",
        {"ts_utc": now_iso, "reason": "tick_end"},
    )
    _write_json(
        tmp_path / "reports" / "exchange_snapshots" / "latest.json",
        {"ts_utc": now_iso, "bots": {"bot1": {"equity_quote": 100.0}}},
    )

    fake_redis = _FakeRedis(
        groups=[["name", "hb_group_bot1", "pending", 0, "lag", 0]],
        dead_rows=[
            (
                "1-0",
                {"payload": json.dumps({"timestamp_ms": now_ms, "reason": "expired_intent"})},
            )
        ],
    )
    report = build_report(
        tmp_path,
        now_ts=now_ts,
        redis_client=fake_redis,
        bots=["bot1"],
        required_groups=["hb_group_bot1"],
        lookback_sec=300,
        max_critical_dead_letters=0,
        max_group_lag=0,
        max_group_pending=0,
        heartbeat_max_age_s=120,
        snapshot_max_age_s=120,
    )

    assert report["status"] == "pass"
    checks = report["checks"]
    assert checks["dead_letter_critical_within_slo"] is True


def test_build_report_fails_when_heartbeat_stale(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    stale_iso = (now - timedelta(minutes=30)).isoformat()
    now_iso = now.isoformat()

    _write_json(
        tmp_path / "data" / "bot1" / "logs" / "heartbeat" / "strategy_heartbeat.json",
        {"ts_utc": stale_iso, "reason": "tick_end"},
    )
    _write_json(
        tmp_path / "reports" / "exchange_snapshots" / "latest.json",
        {"ts_utc": now_iso},
    )

    fake_redis = _FakeRedis(
        groups=[["name", "hb_group_bot1", "pending", 0, "lag", 0]],
        dead_rows=[],
    )
    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        redis_client=fake_redis,
        bots=["bot1"],
        required_groups=["hb_group_bot1"],
        heartbeat_max_age_s=120,
        snapshot_max_age_s=120,
    )

    assert report["status"] == "fail"
    assert "heartbeat_bot1_fresh" in report["failed_checks"]

