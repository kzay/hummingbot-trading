from __future__ import annotations

import json
from pathlib import Path

from scripts.release.check_paper_exchange_load import build_report


class _FakeRedis:
    def __init__(
        self,
        *,
        command_rows: list[tuple[str, dict]],
        result_rows: list[tuple[str, dict]],
        heartbeat_rows: list[tuple[str, dict]],
        groups: list[list[object]],
    ) -> None:
        self._command_rows = command_rows
        self._result_rows = result_rows
        self._heartbeat_rows = heartbeat_rows
        self._groups = groups

    def xrevrange(self, stream: str, _start: str, _end: str, *, count: int = 1000):
        if stream == "hb.paper_exchange.command.v1":
            return self._command_rows[:count]
        if stream == "hb.paper_exchange.event.v1":
            return self._result_rows[:count]
        if stream == "hb.paper_exchange.heartbeat.v1":
            return self._heartbeat_rows[:count]
        return []

    def execute_command(self, *args):
        if len(args) >= 3 and args[0] == "XINFO" and args[1] == "GROUPS":
            return self._groups
        return []


def _payload(data: dict) -> dict:
    return {"payload": json.dumps(data)}


def test_build_report_computes_load_metrics_from_stream_samples(tmp_path: Path) -> None:
    fake_redis = _FakeRedis(
        command_rows=[
            (
                "1000-0",
                _payload(
                    {
                        "event_type": "paper_exchange_command",
                        "event_id": "cmd-1",
                        "timestamp_ms": 1_000,
                    }
                ),
            ),
            (
                "2000-0",
                _payload(
                    {
                        "event_type": "paper_exchange_command",
                        "event_id": "cmd-2",
                        "timestamp_ms": 2_000,
                    }
                ),
            ),
            (
                "3000-0",
                _payload(
                    {
                        "event_type": "paper_exchange_command",
                        "event_id": "cmd-3",
                        "timestamp_ms": 3_000,
                    }
                ),
            ),
        ],
        result_rows=[
            (
                "1100-0",
                _payload(
                    {
                        "event_type": "paper_exchange_event",
                        "command_event_id": "cmd-1",
                        "timestamp_ms": 1_100,
                    }
                ),
            ),
            (
                "2300-0",
                _payload(
                    {
                        "event_type": "paper_exchange_event",
                        "command_event_id": "cmd-2",
                        "timestamp_ms": 2_300,
                    }
                ),
            ),
            (
                "3900-0",
                _payload(
                    {
                        "event_type": "paper_exchange_event",
                        "command_event_id": "cmd-3",
                        "timestamp_ms": 3_900,
                    }
                ),
            ),
        ],
        heartbeat_rows=[
            (
                "1000-1",
                _payload(
                    {
                        "event_type": "paper_exchange_heartbeat",
                        "timestamp_ms": 1_000,
                        "metadata": {"processed_commands": "10"},
                    }
                ),
            ),
            (
                "2000-1",
                _payload(
                    {
                        "event_type": "paper_exchange_heartbeat",
                        "timestamp_ms": 2_000,
                        "metadata": {"processed_commands": "20"},
                    }
                ),
            ),
            (
                "3000-1",
                _payload(
                    {
                        "event_type": "paper_exchange_heartbeat",
                        "timestamp_ms": 3_000,
                        "metadata": {"processed_commands": "5"},
                    }
                ),
            ),
        ],
        groups=[["name", "hb_group_paper_exchange", "pending", 0, "lag", 0]],
    )

    report = build_report(
        tmp_path,
        now_ts=5.0,
        redis_client=fake_redis,
        lookback_sec=3600,
        sample_count=100,
        min_latency_samples=3,
        min_window_sec=1,
    )
    metrics = report["metrics"]
    assert report["status"] == "pass"
    assert abs(float(metrics["p1_19_sustained_command_throughput_cmds_per_sec"]) - 1.5) < 1e-9
    assert float(metrics["p1_19_command_latency_under_load_p95_ms"]) == 300.0
    assert float(metrics["p1_19_command_latency_under_load_p99_ms"]) == 300.0
    assert float(metrics["p1_19_stream_backlog_growth_rate_pct_per_10min"]) == 0.0
    assert float(metrics["p1_19_stress_window_oom_restart_count"]) == 1.0


def test_build_report_uses_fail_closed_sentinels_without_redis(tmp_path: Path) -> None:
    report = build_report(
        tmp_path,
        now_ts=5.0,
        redis_client=None,
        lookback_sec=3600,
        sample_count=100,
        min_latency_samples=1,
        min_window_sec=1,
    )
    metrics = report["metrics"]
    assert report["status"] == "warning"
    assert report["checks"]["redis_connected"] is False
    assert float(metrics["p1_19_sustained_command_throughput_cmds_per_sec"]) == 0.0
    assert float(metrics["p1_19_command_latency_under_load_p95_ms"]) >= 1_000_000.0
    assert float(metrics["p1_19_command_latency_under_load_p99_ms"]) >= 1_000_000.0
    assert float(metrics["p1_19_stream_backlog_growth_rate_pct_per_10min"]) >= 100.0
    assert float(metrics["p1_19_stress_window_oom_restart_count"]) >= 999.0


def test_build_report_filters_commands_by_load_run_id(tmp_path: Path) -> None:
    fake_redis = _FakeRedis(
        command_rows=[
            (
                "1000-0",
                _payload(
                    {
                        "event_type": "paper_exchange_command",
                        "event_id": "cmd-a",
                        "timestamp_ms": 1_000,
                        "metadata": {"load_run_id": "run-a"},
                    }
                ),
            ),
            (
                "2000-0",
                _payload(
                    {
                        "event_type": "paper_exchange_command",
                        "event_id": "cmd-b",
                        "timestamp_ms": 2_000,
                        "metadata": {"load_run_id": "run-b"},
                    }
                ),
            ),
        ],
        result_rows=[
            ("1100-0", _payload({"event_type": "paper_exchange_event", "command_event_id": "cmd-a", "timestamp_ms": 1_100})),
            ("7000-0", _payload({"event_type": "paper_exchange_event", "command_event_id": "cmd-b", "timestamp_ms": 7_000})),
        ],
        heartbeat_rows=[
            (
                "1000-1",
                _payload(
                    {
                        "event_type": "paper_exchange_heartbeat",
                        "timestamp_ms": 1_000,
                        "metadata": {"processed_commands": "1"},
                    }
                ),
            )
        ],
        groups=[["name", "hb_group_paper_exchange", "pending", 0, "lag", 0]],
    )

    report = build_report(
        tmp_path,
        now_ts=10.0,
        redis_client=fake_redis,
        lookback_sec=3600,
        sample_count=100,
        min_latency_samples=1,
        min_window_sec=1,
        load_run_id="run-a",
    )
    metrics = report["metrics"]
    diagnostics = report["diagnostics"]
    assert report["status"] == "pass"
    assert diagnostics["load_run_id"] == "run-a"
    assert diagnostics["command_count"] == 1
    assert diagnostics["processed_count"] == 1
    assert float(metrics["p1_19_command_latency_under_load_p95_ms"]) == 100.0


def test_build_report_scopes_restart_counter_to_command_window(tmp_path: Path) -> None:
    fake_redis = _FakeRedis(
        command_rows=[
            (
                "5000-0",
                _payload(
                    {
                        "event_type": "paper_exchange_command",
                        "event_id": "cmd-a",
                        "timestamp_ms": 5_000,
                        "metadata": {"load_run_id": "run-a"},
                    }
                ),
            ),
            (
                "6000-0",
                _payload(
                    {
                        "event_type": "paper_exchange_command",
                        "event_id": "cmd-b",
                        "timestamp_ms": 6_000,
                        "metadata": {"load_run_id": "run-a"},
                    }
                ),
            ),
        ],
        result_rows=[
            ("5100-0", _payload({"event_type": "paper_exchange_event", "command_event_id": "cmd-a", "timestamp_ms": 5_100})),
            ("6200-0", _payload({"event_type": "paper_exchange_event", "command_event_id": "cmd-b", "timestamp_ms": 6_200})),
        ],
        heartbeat_rows=[
            (
                "1000-1",
                _payload(
                    {
                        "event_type": "paper_exchange_heartbeat",
                        "timestamp_ms": 1_000,
                        "metadata": {"processed_commands": "100"},
                    }
                ),
            ),
            (
                "2000-1",
                _payload(
                    {
                        "event_type": "paper_exchange_heartbeat",
                        "timestamp_ms": 2_000,
                        "metadata": {"processed_commands": "1"},
                    }
                ),
            ),
            (
                "5500-1",
                _payload(
                    {
                        "event_type": "paper_exchange_heartbeat",
                        "timestamp_ms": 5_500,
                        "metadata": {"processed_commands": "10"},
                    }
                ),
            ),
            (
                "6500-1",
                _payload(
                    {
                        "event_type": "paper_exchange_heartbeat",
                        "timestamp_ms": 6_500,
                        "metadata": {"processed_commands": "11"},
                    }
                ),
            ),
        ],
        groups=[["name", "hb_group_paper_exchange", "pending", 0, "lag", 0]],
    )

    report = build_report(
        tmp_path,
        now_ts=10.0,
        redis_client=fake_redis,
        lookback_sec=3600,
        sample_count=100,
        min_latency_samples=1,
        min_window_sec=1,
        load_run_id="run-a",
    )
    metrics = report["metrics"]
    diagnostics = report["diagnostics"]
    assert report["status"] == "pass"
    assert diagnostics["heartbeat_sample_count"] == 2
    assert float(metrics["p1_19_stress_window_oom_restart_count"]) == 0.0
