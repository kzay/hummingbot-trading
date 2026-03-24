from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.release.check_reliability_slo import _dead_letter_stats, build_report


class _FakeRedis:
    def __init__(self, groups, dead_rows, paper_heartbeat_rows=None):
        self._groups = groups
        self._dead_rows = dead_rows
        self._paper_heartbeat_rows = paper_heartbeat_rows or []

    def execute_command(self, *args, **kwargs):
        return self._groups

    def xrevrange(self, stream, *args, **kwargs):
        if str(stream) == "hb.dead_letter.v1":
            return self._dead_rows
        if str(stream) == "hb.paper_exchange.heartbeat.v1":
            return self._paper_heartbeat_rows
        return []


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_dead_letter_stats_marks_local_authority_reject_as_non_critical() -> None:
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
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
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
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
    now = datetime.now(UTC)
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
    now = datetime.now(UTC)
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
    now = datetime.now(UTC)
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


def test_build_report_passes_with_paper_exchange_checks_enabled(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_ts = now.timestamp()
    now_iso = now.isoformat()
    now_ms = int(now_ts * 1000)

    _write_json(
        tmp_path / "data" / "bot1" / "logs" / "heartbeat" / "strategy_heartbeat.json",
        {"ts_utc": now_iso, "reason": "tick_end"},
    )
    _write_json(
        tmp_path / "reports" / "exchange_snapshots" / "latest.json",
        {"ts_utc": now_iso},
    )
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_load_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "metrics": {
                "p1_19_stream_backlog_growth_rate_pct_per_10min": 0.2,
                "p1_19_command_latency_under_load_p95_ms": 120.0,
                "p1_19_command_latency_under_load_p99_ms": 240.0,
            },
        },
    )

    fake_redis = _FakeRedis(
        groups=[["name", "hb_group_bot1", "pending", 0, "lag", 0]],
        dead_rows=[],
        paper_heartbeat_rows=[
            (
                f"{now_ms}-0",
                {
                    "payload": json.dumps(
                        {
                            "event_type": "paper_exchange_heartbeat",
                            "timestamp_ms": now_ms,
                            "metadata": {
                                "processed_commands": "100",
                                "rejected_commands": "1",
                                "stale_pairs": "0",
                            },
                        }
                    )
                },
            )
        ],
    )
    report = build_report(
        tmp_path,
        now_ts=now_ts,
        redis_client=fake_redis,
        bots=["bot1"],
        required_groups=["hb_group_bot1"],
        heartbeat_max_age_s=120,
        snapshot_max_age_s=120,
        check_paper_exchange=True,
        paper_exchange_heartbeat_max_age_s=30,
        max_paper_exchange_reject_rate_pct=5.0,
        max_paper_exchange_stale_pairs=0,
        paper_exchange_load_report_max_age_s=300,
        max_paper_exchange_backlog_growth_pct_per_10min=1.0,
        max_paper_exchange_latency_p95_ms=500.0,
        max_paper_exchange_latency_p99_ms=1000.0,
    )

    assert report["status"] == "pass"
    checks = report["checks"]
    assert checks["paper_exchange_heartbeat_present"] is True
    assert checks["paper_exchange_heartbeat_fresh"] is True
    assert checks["paper_exchange_reject_rate_within_slo"] is True
    assert checks["paper_exchange_stale_pairs_within_slo"] is True
    assert checks["paper_exchange_load_report_pass"] is True
    assert checks["paper_exchange_backlog_growth_within_slo"] is True
    assert checks["paper_exchange_latency_p95_within_slo"] is True
    assert checks["paper_exchange_latency_p99_within_slo"] is True


def test_build_report_fails_with_paper_exchange_slo_breaches(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_ts = now.timestamp()
    stale_iso = (now - timedelta(hours=2)).isoformat()
    now_ms = int(now_ts * 1000)
    stale_ms = now_ms - 10 * 60 * 1000

    _write_json(
        tmp_path / "data" / "bot1" / "logs" / "heartbeat" / "strategy_heartbeat.json",
        {"ts_utc": now.isoformat(), "reason": "tick_end"},
    )
    _write_json(
        tmp_path / "reports" / "exchange_snapshots" / "latest.json",
        {"ts_utc": now.isoformat()},
    )
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_load_latest.json",
        {
            "ts_utc": stale_iso,
            "status": "warning",
            "metrics": {
                "p1_19_stream_backlog_growth_rate_pct_per_10min": 12.0,
                "p1_19_command_latency_under_load_p95_ms": 900.0,
                "p1_19_command_latency_under_load_p99_ms": 1400.0,
            },
        },
    )
    fake_redis = _FakeRedis(
        groups=[["name", "hb_group_bot1", "pending", 0, "lag", 0]],
        dead_rows=[],
        paper_heartbeat_rows=[
            (
                f"{stale_ms}-0",
                {
                    "payload": json.dumps(
                        {
                            "event_type": "paper_exchange_heartbeat",
                            "timestamp_ms": stale_ms,
                            "metadata": {
                                "processed_commands": "100",
                                "rejected_commands": "60",
                                "stale_pairs": "2",
                            },
                        }
                    )
                },
            )
        ],
    )
    report = build_report(
        tmp_path,
        now_ts=now_ts,
        redis_client=fake_redis,
        bots=["bot1"],
        required_groups=["hb_group_bot1"],
        check_paper_exchange=True,
        paper_exchange_heartbeat_max_age_s=30,
        max_paper_exchange_reject_rate_pct=5.0,
        max_paper_exchange_stale_pairs=0,
        paper_exchange_load_report_max_age_s=300,
        max_paper_exchange_backlog_growth_pct_per_10min=1.0,
        max_paper_exchange_latency_p95_ms=500.0,
        max_paper_exchange_latency_p99_ms=1000.0,
    )

    assert report["status"] == "fail"
    failed = set(report["failed_checks"])
    assert "paper_exchange_heartbeat_fresh" in failed
    assert "paper_exchange_reject_rate_within_slo" in failed
    assert "paper_exchange_stale_pairs_within_slo" in failed
    assert "paper_exchange_load_report_fresh" in failed
    assert "paper_exchange_load_report_pass" in failed
    assert "paper_exchange_backlog_growth_within_slo" in failed
    assert "paper_exchange_latency_p95_within_slo" in failed
    assert "paper_exchange_latency_p99_within_slo" in failed

