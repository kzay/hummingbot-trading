from __future__ import annotations

import json
from pathlib import Path

from scripts.release.run_paper_exchange_load_harness import build_report


class _FakeRedis:
    def __init__(
        self,
        *,
        heartbeat_present: bool = True,
        result_latency_ms: int = 50,
        auto_result: bool = True,
    ) -> None:
        self._heartbeat_present = heartbeat_present
        self._result_latency_ms = int(result_latency_ms)
        self._auto_result = auto_result
        self._seq = 0
        self._event_rows: list[tuple[str, dict]] = []

    def xadd(self, *, name: str, fields: dict, **_kwargs):
        self._seq += 1
        payload_raw = fields.get("payload", "{}")
        payload = json.loads(payload_raw) if isinstance(payload_raw, str) else {}
        ts_ms = int(payload.get("timestamp_ms", 0))
        event_id = str(payload.get("event_id", ""))
        if self._auto_result and name == "hb.paper_exchange.command.v1" and event_id:
            result_payload = {
                "event_type": "paper_exchange_event",
                "command_event_id": event_id,
                "timestamp_ms": ts_ms + self._result_latency_ms,
            }
            stream_id = f"{ts_ms + self._result_latency_ms}-{self._seq}"
            self._event_rows.append((stream_id, {"payload": json.dumps(result_payload)}))
        return f"{ts_ms}-{self._seq}"

    def xrevrange(self, name: str, _max: str, _min: str, *, count: int = 1000):
        if name == "hb.paper_exchange.heartbeat.v1":
            if not self._heartbeat_present:
                return []
            payload = {"event_type": "paper_exchange_heartbeat", "timestamp_ms": 1_000_000}
            return [("1000000-0", {"payload": json.dumps(payload)})]
        if name == "hb.paper_exchange.event.v1":
            return list(reversed(self._event_rows[:count]))
        return []


def test_build_report_passes_with_fresh_heartbeat_and_matched_results(tmp_path: Path) -> None:
    fake_redis = _FakeRedis(heartbeat_present=True, result_latency_ms=40, auto_result=True)
    report = build_report(
        tmp_path,
        redis_client=fake_redis,
        command_stream="hb.paper_exchange.command.v1",
        event_stream="hb.paper_exchange.event.v1",
        heartbeat_stream="hb.paper_exchange.heartbeat.v1",
        command_maxlen=1000,
        duration_sec=0.2,
        target_cmd_rate=40.0,
        producer="hb_bridge_active_adapter",
        instance_name="bot1",
        instance_names="bot1,bot3,bot4",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        result_timeout_sec=0.2,
        poll_interval_ms=10,
        scan_count=1000,
        require_heartbeat_fresh=False,
        heartbeat_max_age_s=30.0,
        min_commands=1,
        min_instance_coverage=1,
        min_publish_success_rate_pct=90.0,
        min_result_match_rate_pct=90.0,
    )
    assert report["status"] == "pass"
    metrics = report["metrics"]
    assert int(metrics["published_commands"]) > 0
    assert int(metrics["matched_results"]) == int(metrics["published_commands"])
    assert float(metrics["publish_success_rate_pct"]) == 100.0
    assert float(metrics["result_match_rate_pct"]) == 100.0
    assert float(metrics["latency_p95_ms"]) == 40.0
    assert float(metrics["latency_p99_ms"]) == 40.0


def test_build_report_fails_when_heartbeat_required_but_missing(tmp_path: Path) -> None:
    fake_redis = _FakeRedis(heartbeat_present=False, result_latency_ms=40, auto_result=True)
    report = build_report(
        tmp_path,
        redis_client=fake_redis,
        command_stream="hb.paper_exchange.command.v1",
        event_stream="hb.paper_exchange.event.v1",
        heartbeat_stream="hb.paper_exchange.heartbeat.v1",
        command_maxlen=1000,
        duration_sec=0.1,
        target_cmd_rate=20.0,
        producer="hb_bridge_active_adapter",
        instance_name="bot1",
        instance_names="bot1",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        result_timeout_sec=0.1,
        poll_interval_ms=10,
        scan_count=1000,
        require_heartbeat_fresh=True,
        heartbeat_max_age_s=30.0,
        min_commands=1,
        min_instance_coverage=1,
        min_publish_success_rate_pct=90.0,
        min_result_match_rate_pct=90.0,
    )
    assert report["status"] == "fail"
    assert "heartbeat_recent" in report["failed_checks"]


def test_build_report_enforces_minimum_instance_coverage(tmp_path: Path) -> None:
    fake_redis = _FakeRedis(heartbeat_present=True, result_latency_ms=20, auto_result=True)
    report = build_report(
        tmp_path,
        redis_client=fake_redis,
        command_stream="hb.paper_exchange.command.v1",
        event_stream="hb.paper_exchange.event.v1",
        heartbeat_stream="hb.paper_exchange.heartbeat.v1",
        command_maxlen=1000,
        duration_sec=0.2,
        target_cmd_rate=20.0,
        producer="hb_bridge_active_adapter",
        instance_name="bot1",
        instance_names="bot1",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        result_timeout_sec=0.2,
        poll_interval_ms=10,
        scan_count=1000,
        require_heartbeat_fresh=False,
        heartbeat_max_age_s=30.0,
        min_commands=1,
        min_instance_coverage=2,
        min_publish_success_rate_pct=90.0,
        min_result_match_rate_pct=90.0,
    )
    assert report["status"] == "fail"
    assert "minimum_instance_coverage" in report["failed_checks"]
