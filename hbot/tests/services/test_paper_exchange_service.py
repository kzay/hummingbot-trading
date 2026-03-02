from __future__ import annotations

import json
import time
from pathlib import Path

from services.paper_exchange_service.main import (
    _load_market_fill_journal,
    _load_state_snapshot,
    _prune_orders,
    OrderRecord,
    PaperExchangeState,
    ServiceSettings,
    build_heartbeat_event,
    handle_command_payload,
    ingest_market_snapshot_payload,
    process_command_rows,
    process_market_rows,
)


def _market_snapshot_payload(
    connector_name: str = "bitget_perpetual",
    timestamp_ms: int = 1000,
    *,
    best_bid: float | None = None,
    best_ask: float | None = None,
    best_bid_size: float | None = None,
    best_ask_size: float | None = None,
) -> dict:
    payload = {
        "schema_version": "1.0",
        "event_type": "market_snapshot",
        "event_id": "evt-market-1",
        "producer": "hb",
        "timestamp_ms": timestamp_ms,
        "instance_name": "bot1",
        "controller_id": "epp_v2_4",
        "connector_name": connector_name,
        "trading_pair": "BTC-USDT",
        "mid_price": 10_000.0,
        "equity_quote": 1_000.0,
        "base_pct": 0.5,
        "target_base_pct": 0.5,
        "spread_pct": 0.001,
        "net_edge_pct": 0.0004,
        "turnover_x": 0.8,
        "state": "running",
        "extra": {},
    }
    if best_bid is not None:
        payload["best_bid"] = best_bid
    if best_ask is not None:
        payload["best_ask"] = best_ask
    if best_bid_size is not None:
        payload["best_bid_size"] = best_bid_size
    if best_ask_size is not None:
        payload["best_ask_size"] = best_ask_size
    return payload


def _command_payload(command: str = "sync_state", *, event_id: str = "cmd-1") -> dict:
    payload = {
        "schema_version": "1.0",
        "event_type": "paper_exchange_command",
        "event_id": event_id,
        "producer": "hb",
        "timestamp_ms": 1_000,
        "instance_name": "bot1",
        "command": command,
        "connector_name": "bitget_perpetual",
        "trading_pair": "BTC-USDT",
    }
    if command == "submit_order":
        payload.update({
            "order_id": f"ord-{event_id}",
            "side": "buy",
            "order_type": "limit",
            "amount_base": 0.01,
            "price": 10_000.0,
            "metadata": {"time_in_force": "gtc"},
        })
    elif command == "cancel_order":
        payload.update({"order_id": "ord-cancel"})
    return payload


def _privileged_metadata() -> dict:
    return {
        "operator": "desk_ops",
        "reason": "manual_risk_intervention",
        "change_ticket": "CHG-1234",
        "trace_id": "trace-cancel-all",
    }


class _FakeRedisClient:
    def __init__(self, *, xadd_result: str | None = "1-0"):
        self._xadd_result = xadd_result
        self.xadd_calls = []
        self.acks = []

    def xadd(self, *, stream: str, payload: dict, maxlen=None):
        self.xadd_calls.append((stream, payload, maxlen))
        return self._xadd_result

    def ack(self, stream: str, group: str, entry_id: str) -> None:
        self.acks.append((stream, group, entry_id))

    def ack_many(self, stream: str, group: str, entry_ids: list[str]) -> None:
        for entry_id in entry_ids:
            self.acks.append((stream, group, entry_id))


class _SequencedFakeRedisClient(_FakeRedisClient):
    def __init__(self, results: list[str | None]):
        super().__init__(xadd_result=None)
        self._results = list(results)

    def xadd(self, *, stream: str, payload: dict, maxlen=None):
        self.xadd_calls.append((stream, payload, maxlen))
        if not self._results:
            return None
        return self._results.pop(0)


def test_ingest_market_snapshot_accepts_allowed_connector() -> None:
    state = PaperExchangeState()
    ok, reason = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    assert reason == "accepted"
    assert state.accepted_snapshots == 1
    assert state.rejected_snapshots == 0
    assert len(state.pairs) == 1


def test_ingest_market_snapshot_rejects_disallowed_connector() -> None:
    state = PaperExchangeState()
    ok, reason = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(connector_name="paper_trade"),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is False
    assert reason == "connector_not_allowed"
    assert state.accepted_snapshots == 0
    assert state.rejected_snapshots == 1
    assert len(state.pairs) == 0


def test_build_heartbeat_degraded_when_snapshot_stale() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    heartbeat = build_heartbeat_event(
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        stale_after_ms=100,
        now_ms=1_500,
    )
    assert heartbeat.status == "degraded"
    assert heartbeat.market_pairs_total == 1
    assert heartbeat.stale_pairs == 1
    assert heartbeat.oldest_snapshot_age_ms == 500


def test_build_heartbeat_includes_command_latency_metrics() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    first_command = _command_payload("sync_state", event_id="cmd-latency-1")
    first_command["timestamp_ms"] = 900
    second_command = _command_payload("sync_state", event_id="cmd-latency-2")
    second_command["timestamp_ms"] = 950
    handle_command_payload(
        payload=first_command,
        state=state,
        service_instance_name="paper_exchange",
        now_ms=1_000,
    )
    handle_command_payload(
        payload=second_command,
        state=state,
        service_instance_name="paper_exchange",
        now_ms=1_000,
    )
    heartbeat = build_heartbeat_event(
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        stale_after_ms=5_000,
        now_ms=1_100,
    )
    assert heartbeat.metadata["command_latency_samples"] == "2"
    assert heartbeat.metadata["command_latency_avg_ms"] == "75"
    assert heartbeat.metadata["command_latency_max_ms"] == "100"


def test_handle_command_sync_state_processed() -> None:
    state = PaperExchangeState()
    result = handle_command_payload(
        payload=_command_payload("sync_state", event_id="cmd-1"),
        state=state,
        service_instance_name="paper_exchange",
        now_ms=1_050,
    )
    assert result.status == "processed"
    assert result.reason == "sync_state_accepted"
    assert state.processed_commands == 1
    assert state.rejected_commands == 0


def test_handle_command_submit_order_processed() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    result = handle_command_payload(
        payload=_command_payload("submit_order", event_id="cmd-2"),
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=500,
        now_ms=1_050,
    )
    assert result.status == "processed"
    assert result.reason == "order_accepted"
    assert result.metadata["order_state"] == "working"
    assert state.processed_commands == 1
    assert state.rejected_commands == 0
    assert "ord-cmd-2" in state.orders_by_id


def test_handle_command_submit_order_rejects_duplicate_order_id() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    first = handle_command_payload(
        payload=_command_payload("submit_order", event_id="cmd-a"),
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=500,
        now_ms=1_050,
    )
    assert first.status == "processed"
    duplicate_payload = _command_payload("submit_order", event_id="cmd-b")
    duplicate_payload["order_id"] = "ord-cmd-a"
    second = handle_command_payload(
        payload=duplicate_payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=500,
        now_ms=1_060,
    )
    assert second.status == "rejected"
    assert second.reason == "duplicate_order_id"
    assert second.metadata["existing_state"] == "working"


def test_handle_command_cancel_order_processed() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    submit_result = handle_command_payload(
        payload=_command_payload("submit_order", event_id="cmd-submit"),
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=500,
        now_ms=1_050,
    )
    assert submit_result.status == "processed"

    cancel_payload = _command_payload("cancel_order", event_id="cmd-cancel")
    cancel_payload["order_id"] = "ord-cmd-submit"
    cancel_result = handle_command_payload(
        payload=cancel_payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=500,
        now_ms=1_060,
    )
    assert cancel_result.status == "processed"
    assert cancel_result.reason == "order_cancelled"
    assert cancel_result.metadata["order_state"] == "cancelled"
    assert state.orders_by_id["ord-cmd-submit"].state == "cancelled"


def test_handle_command_cancel_order_rejects_missing_order() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    cancel_payload = _command_payload("cancel_order", event_id="cmd-missing")
    cancel_payload["order_id"] = "ord-does-not-exist"
    result = handle_command_payload(
        payload=cancel_payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=500,
        now_ms=1_060,
    )
    assert result.status == "rejected"
    assert result.reason == "order_not_found"


def test_handle_command_submit_order_ioc_expires_without_fill() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    payload = _command_payload("submit_order", event_id="cmd-ioc")
    payload["metadata"] = {"time_in_force": "ioc"}
    result = handle_command_payload(
        payload=payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=500,
        now_ms=1_070,
    )
    assert result.status == "processed"
    assert result.reason == "time_in_force_expired_no_fill"
    assert result.metadata["order_state"] == "expired"


def test_handle_command_submit_market_order_fills_immediately() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    payload = _command_payload("submit_order", event_id="cmd-market")
    payload["order_type"] = "market"
    payload["price"] = None
    result = handle_command_payload(
        payload=payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=500,
        now_ms=1_080,
    )
    assert result.status == "processed"
    assert result.reason == "order_filled_market"
    assert result.metadata["order_state"] == "filled"
    assert result.metadata["fill_amount_base"] == "0.01"
    assert result.metadata["fill_price"] == "10000.0"


def test_handle_command_limit_buy_crossing_fills_at_best_ask() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000, best_bid=9_999.0, best_ask=10_001.0),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    payload = _command_payload("submit_order", event_id="cmd-cross")
    payload["price"] = 10_002.0
    result = handle_command_payload(
        payload=payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=500,
        now_ms=1_080,
    )
    assert result.status == "processed"
    assert result.reason == "order_filled_crossing"
    assert result.metadata["order_state"] == "filled"
    assert result.metadata["fill_price"] == "10001.0"
    assert result.metadata["is_maker"] == "0"


def test_handle_command_limit_buy_crossing_partial_when_top_of_book_size_small() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(
            timestamp_ms=1_000,
            best_bid=9_999.0,
            best_ask=10_001.0,
            best_ask_size=0.01,
        ),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    payload = _command_payload("submit_order", event_id="cmd-cross-partial")
    payload["amount_base"] = 0.03
    payload["price"] = 10_002.0
    result = handle_command_payload(
        payload=payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=500,
        now_ms=1_080,
    )
    assert result.status == "processed"
    assert result.reason == "order_partially_filled_crossing"
    assert result.metadata["order_state"] == "partially_filled"
    assert result.metadata["fill_amount_base"] == "0.01"
    assert abs(float(result.metadata["remaining_amount_base"]) - 0.02) < 1e-9
    order = state.orders_by_id["ord-cmd-cross-partial"]
    assert order.state == "partially_filled"
    assert abs(order.filled_base - 0.01) < 1e-9


def test_handle_command_post_only_crossing_rejected() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000, best_bid=9_999.0, best_ask=10_001.0),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    payload = _command_payload("submit_order", event_id="cmd-post-only")
    payload["order_type"] = "post_only"
    payload["price"] = 10_005.0
    result = handle_command_payload(
        payload=payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=500,
        now_ms=1_080,
    )
    assert result.status == "rejected"
    assert result.reason == "post_only_would_take"
    assert result.metadata["best_bid"] == "9999.0"
    assert result.metadata["best_ask"] == "10001.0"


def test_handle_command_market_sell_uses_best_bid() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000, best_bid=9_998.0, best_ask=10_002.0),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    payload = _command_payload("submit_order", event_id="cmd-market-sell")
    payload["order_type"] = "market"
    payload["price"] = None
    payload["side"] = "sell"
    result = handle_command_payload(
        payload=payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=500,
        now_ms=1_080,
    )
    assert result.status == "processed"
    assert result.reason == "order_filled_market"
    assert result.metadata["fill_price"] == "9998.0"


def test_ingest_market_snapshot_rejects_invalid_top_of_book() -> None:
    state = PaperExchangeState()
    ok, reason = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000, best_bid=10_001.0, best_ask=10_001.0),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is False
    assert reason == "invalid_top_of_book"


def test_ingest_market_snapshot_rejects_non_positive_top_of_book_size() -> None:
    state = PaperExchangeState()
    ok, reason = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000, best_bid=9_999.0, best_ask=10_001.0, best_ask_size=0.0),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is False
    assert reason == "non_positive_best_ask_size"


def test_handle_command_rejects_disallowed_connector() -> None:
    state = PaperExchangeState()
    payload = _command_payload("submit_order", event_id="cmd-3")
    payload["connector_name"] = "paper_trade"
    result = handle_command_payload(
        payload=payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        now_ms=1_050,
    )
    assert result.status == "rejected"
    assert result.reason == "connector_not_allowed"
    assert state.rejected_commands_disallowed_connector == 1


def test_handle_command_rejects_unauthorized_producer() -> None:
    state = PaperExchangeState()
    payload = _command_payload("submit_order", event_id="cmd-unauth-producer")
    payload["producer"] = "untrusted_sender"
    result = handle_command_payload(
        payload=payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        allowed_command_producers={"hb_bridge_active_adapter"},
        now_ms=1_050,
    )
    assert result.status == "rejected"
    assert result.reason == "unauthorized_producer"
    assert state.rejected_commands_unauthorized_producer == 1


def test_handle_command_cancel_all_rejects_missing_privileged_metadata() -> None:
    state = PaperExchangeState()
    payload = _command_payload("cancel_all", event_id="cmd-cancel-all-missing-meta")
    result = handle_command_payload(
        payload=payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        now_ms=1_050,
    )
    assert result.status == "rejected"
    assert result.reason == "missing_privileged_metadata"
    assert result.metadata["missing_fields"] == "operator,reason,change_ticket,trace_id"
    assert state.rejected_commands_missing_privileged_metadata == 1


def test_handle_command_cancel_all_processed_with_privileged_metadata() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    submit_result = handle_command_payload(
        payload=_command_payload("submit_order", event_id="cmd-cancel-all-seed"),
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=500,
        now_ms=1_010,
    )
    assert submit_result.status == "processed"
    payload = _command_payload("cancel_all", event_id="cmd-cancel-all-with-meta")
    payload["metadata"] = _privileged_metadata()
    result = handle_command_payload(
        payload=payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=500,
        now_ms=1_020,
    )
    assert result.status == "processed"
    assert result.reason == "cancel_all_processed"
    assert result.metadata["cancelled_count"] == "1"
    assert state.privileged_commands_processed == 1
    assert state.orders_by_id["ord-cmd-cancel-all-seed"].state == "cancelled"


def test_handle_command_rejects_when_market_snapshot_missing() -> None:
    state = PaperExchangeState()
    result = handle_command_payload(
        payload=_command_payload("submit_order", event_id="cmd-4"),
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=5_000,
        now_ms=1_050,
    )
    assert result.status == "rejected"
    assert result.reason == "no_market_snapshot"
    assert state.rejected_commands_missing_market == 1


def test_handle_command_rejects_when_market_snapshot_stale() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    result = handle_command_payload(
        payload=_command_payload("submit_order", event_id="cmd-5"),
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=100,
        now_ms=2_501,
    )
    assert result.status == "rejected"
    assert result.reason == "stale_market_snapshot"
    assert result.metadata["snapshot_age_ms"] == "1501"
    assert state.rejected_commands_stale_market == 1


def test_process_command_rows_deduplicates_command_event_id(tmp_path: Path) -> None:
    state = PaperExchangeState()
    state.command_results_by_id["cmd-dup"] = {"status": "processed", "reason": "sync_state_accepted"}
    settings = ServiceSettings(
        service_instance_name="paper_exchange",
        consumer_group="grp",
        command_stream="hb.paper_exchange.command.v1",
        event_stream="hb.paper_exchange.event.v1",
        allowed_connectors={"bitget_perpetual"},
    )
    fake_client = _FakeRedisClient(xadd_result="100-0")
    process_command_rows(
        rows=[("1-0", _command_payload("sync_state", event_id="cmd-dup"))],
        source="new",
        client=fake_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
        command_journal_path=tmp_path / "journal.json",
    )
    assert state.duplicate_command_events == 1
    assert fake_client.xadd_calls == []
    assert len(fake_client.acks) == 1


def test_process_command_rows_persists_result_and_acks(tmp_path: Path) -> None:
    state = PaperExchangeState()
    settings = ServiceSettings(
        service_instance_name="paper_exchange",
        consumer_group="grp",
        command_stream="hb.paper_exchange.command.v1",
        event_stream="hb.paper_exchange.event.v1",
        allowed_connectors={"bitget_perpetual"},
    )
    fake_client = _FakeRedisClient(xadd_result="101-0")
    journal_path = tmp_path / "journal.json"
    process_command_rows(
        rows=[("2-0", _command_payload("sync_state", event_id="cmd-new"))],
        source="reclaimed",
        client=fake_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
        command_journal_path=journal_path,
    )
    assert len(fake_client.xadd_calls) == 1
    assert len(fake_client.acks) == 1
    assert state.reclaimed_pending_entries == 1
    assert "cmd-new" in state.command_results_by_id
    payload = json.loads(journal_path.read_text(encoding="utf-8"))
    assert payload["commands"]["cmd-new"]["status"] == "processed"


def test_process_command_rows_can_skip_sync_state_journal_persist(tmp_path: Path) -> None:
    state = PaperExchangeState()
    settings = ServiceSettings(
        service_instance_name="paper_exchange",
        consumer_group="grp",
        command_stream="hb.paper_exchange.command.v1",
        event_stream="hb.paper_exchange.event.v1",
        allowed_connectors={"bitget_perpetual"},
        persist_sync_state_results=False,
    )
    fake_client = _FakeRedisClient(xadd_result="101-0")
    journal_path = tmp_path / "journal.json"
    process_command_rows(
        rows=[("2-0", _command_payload("sync_state", event_id="cmd-no-persist-sync"))],
        source="new",
        client=fake_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
        command_journal_path=journal_path,
    )
    assert len(fake_client.xadd_calls) == 1
    assert len(fake_client.acks) == 1
    assert "cmd-no-persist-sync" not in state.command_results_by_id
    assert len(state.command_results_by_id) == 0
    assert journal_path.exists() is False


def test_process_command_rows_skips_load_harness_sync_state_journal_even_when_enabled(tmp_path: Path) -> None:
    state = PaperExchangeState()
    settings = ServiceSettings(
        service_instance_name="paper_exchange",
        consumer_group="grp",
        command_stream="hb.paper_exchange.command.v1",
        event_stream="hb.paper_exchange.event.v1",
        allowed_connectors={"bitget_perpetual"},
        persist_sync_state_results=True,
    )
    fake_client = _FakeRedisClient(xadd_result="101-0")
    journal_path = tmp_path / "journal.json"
    payload = _command_payload("sync_state", event_id="cmd-harness-sync")
    payload["metadata"] = {"load_harness": "1"}
    process_command_rows(
        rows=[("2-0", payload)],
        source="new",
        client=fake_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
        command_journal_path=journal_path,
    )
    assert len(fake_client.xadd_calls) == 1
    assert len(fake_client.acks) == 1
    assert "cmd-harness-sync" not in state.command_results_by_id
    assert journal_path.exists() is False


def test_process_command_rows_populates_command_sequence_metadata(tmp_path: Path) -> None:
    state = PaperExchangeState()
    ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=int(time.time() * 1000)),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    settings = ServiceSettings(
        service_instance_name="paper_exchange",
        consumer_group="grp",
        command_stream="hb.paper_exchange.command.v1",
        event_stream="hb.paper_exchange.event.v1",
        allowed_connectors={"bitget_perpetual"},
    )
    fake_client = _FakeRedisClient(xadd_result="102-0")
    process_command_rows(
        rows=[("7-3", _command_payload("submit_order", event_id="cmd-seq"))],
        source="new",
        client=fake_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
        command_journal_path=tmp_path / "journal.json",
    )
    assert len(fake_client.xadd_calls) == 1
    published_payload = fake_client.xadd_calls[0][1]
    assert published_payload["metadata"]["command_sequence"] == str(7 * 1_000_000 + 3)


def test_process_command_rows_no_ack_when_publish_fails(tmp_path: Path) -> None:
    state = PaperExchangeState()
    settings = ServiceSettings(
        service_instance_name="paper_exchange",
        consumer_group="grp",
        command_stream="hb.paper_exchange.command.v1",
        event_stream="hb.paper_exchange.event.v1",
        allowed_connectors={"bitget_perpetual"},
    )
    fake_client = _FakeRedisClient(xadd_result=None)
    process_command_rows(
        rows=[("3-0", _command_payload("sync_state", event_id="cmd-fail"))],
        source="new",
        client=fake_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
        command_journal_path=tmp_path / "journal.json",
    )
    assert state.command_publish_failures == 1
    assert fake_client.acks == []
    assert "cmd-fail" not in state.command_results_by_id


def test_process_command_rows_persists_state_snapshot(tmp_path: Path) -> None:
    state = PaperExchangeState()
    now_ms = int(time.time() * 1000)
    ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=now_ms),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    settings = ServiceSettings(
        service_instance_name="paper_exchange",
        consumer_group="grp",
        command_stream="hb.paper_exchange.command.v1",
        event_stream="hb.paper_exchange.event.v1",
        allowed_connectors={"bitget_perpetual"},
    )
    fake_client = _FakeRedisClient(xadd_result="104-0")
    state_snapshot_path = tmp_path / "state_snapshot.json"
    process_command_rows(
        rows=[("4-0", _command_payload("submit_order", event_id="cmd-state"))],
        source="new",
        client=fake_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
        command_journal_path=tmp_path / "journal.json",
        state_snapshot_path=state_snapshot_path,
    )
    assert state_snapshot_path.exists()
    loaded = _load_state_snapshot(state_snapshot_path)
    assert "ord-cmd-state" in loaded
    assert loaded["ord-cmd-state"].state == "working"


def test_process_command_rows_replays_privileged_audit_publish_until_success(tmp_path: Path) -> None:
    state = PaperExchangeState()
    now_ms = int(time.time() * 1000)
    ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=now_ms),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    submit_result = handle_command_payload(
        payload=_command_payload("submit_order", event_id="cmd-priv-seed"),
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=5_000,
        now_ms=now_ms + 1,
    )
    assert submit_result.status == "processed"

    settings = ServiceSettings(
        service_instance_name="paper_exchange",
        consumer_group="grp",
        command_stream="hb.paper_exchange.command.v1",
        event_stream="hb.paper_exchange.event.v1",
        allowed_connectors={"bitget_perpetual"},
    )
    journal_path = tmp_path / "journal.json"
    privileged_payload = _command_payload("cancel_all", event_id="cmd-priv-audit")
    privileged_payload["timestamp_ms"] = now_ms + 2
    privileged_payload["metadata"] = _privileged_metadata()

    first_pass_client = _SequencedFakeRedisClient(results=["401-0", None])
    process_command_rows(
        rows=[("40-0", privileged_payload)],
        source="new",
        client=first_pass_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
        command_journal_path=journal_path,
    )
    assert len(first_pass_client.xadd_calls) == 2
    assert first_pass_client.xadd_calls[0][0] == settings.event_stream
    assert first_pass_client.xadd_calls[1][0] == settings.audit_stream
    assert first_pass_client.acks == []
    assert state.privileged_command_audit_publish_failures == 1
    assert state.command_results_by_id["cmd-priv-audit"]["audit_required"] is True
    assert state.command_results_by_id["cmd-priv-audit"]["audit_published"] is False

    replay_client = _SequencedFakeRedisClient(results=["402-0"])
    process_command_rows(
        rows=[("40-1", privileged_payload)],
        source="reclaimed",
        client=replay_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
        command_journal_path=journal_path,
    )
    assert len(replay_client.xadd_calls) == 1
    assert replay_client.xadd_calls[0][0] == settings.audit_stream
    assert len(replay_client.acks) == 1
    assert state.command_results_by_id["cmd-priv-audit"]["audit_published"] is True
    assert state.duplicate_command_events == 1
    assert state.reclaimed_pending_entries == 1
    assert state.privileged_command_audit_published == 1


def test_process_market_rows_generates_partial_then_full_fill_events(tmp_path: Path) -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000, best_bid=9_990.0, best_ask=10_010.0, best_ask_size=0.05),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True

    submit_payload = _command_payload("submit_order", event_id="cmd-resting-fill")
    submit_payload["amount_base"] = 0.03
    submit_payload["price"] = 10_005.0
    submit_result = handle_command_payload(
        payload=submit_payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=5_000,
        now_ms=1_010,
    )
    assert submit_result.status == "processed"
    assert submit_result.metadata["order_state"] == "working"

    settings = ServiceSettings(
        service_instance_name="paper_exchange",
        consumer_group="grp",
        market_data_stream="hb.market_data.v1",
        event_stream="hb.paper_exchange.event.v1",
        allowed_connectors={"bitget_perpetual"},
    )
    fake_client = _FakeRedisClient(xadd_result="201-0")
    state_snapshot_path = tmp_path / "state_snapshot_market_fill.json"
    first_market_payload = _market_snapshot_payload(
        timestamp_ms=1_100,
        best_bid=10_003.0,
        best_ask=10_004.0,
        best_ask_size=0.01,
    )
    first_market_payload["event_id"] = "evt-market-fill-1"

    process_market_rows(
        rows=[("11-0", first_market_payload)],
        source="new",
        client=fake_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
        state_snapshot_path=state_snapshot_path,
    )
    order = state.orders_by_id["ord-cmd-resting-fill"]
    assert order.state == "partially_filled"
    assert abs(order.filled_base - 0.01) < 1e-9
    assert len(fake_client.xadd_calls) == 1
    first_payload = fake_client.xadd_calls[0][1]
    assert first_payload["command"] == "order_fill"
    assert first_payload["metadata"]["order_state"] == "partially_filled"
    assert first_payload["metadata"]["fill_amount_base"] == "0.01"
    second_market_payload = _market_snapshot_payload(
        timestamp_ms=1_200,
        best_bid=10_003.0,
        best_ask=10_004.0,
        best_ask_size=0.05,
    )
    second_market_payload["event_id"] = "evt-market-fill-2"

    process_market_rows(
        rows=[("12-0", second_market_payload)],
        source="new",
        client=fake_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
        state_snapshot_path=state_snapshot_path,
    )
    order = state.orders_by_id["ord-cmd-resting-fill"]
    assert order.state == "filled"
    assert abs(order.filled_base - 0.03) < 1e-9
    assert len(fake_client.xadd_calls) == 2
    second_payload = fake_client.xadd_calls[1][1]
    assert second_payload["metadata"]["order_state"] == "filled"
    assert abs(float(second_payload["metadata"]["fill_amount_base"]) - 0.02) < 1e-9
    assert state.generated_fill_events == 2
    assert state.generated_partial_fill_events == 1
    assert state.market_match_cycles == 2
    assert state_snapshot_path.exists()
    loaded = _load_state_snapshot(state_snapshot_path)
    assert loaded["ord-cmd-resting-fill"].state == "filled"


def test_process_market_rows_replay_same_snapshot_does_not_duplicate_fill() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000, best_bid=9_990.0, best_ask=10_010.0, best_ask_size=0.05),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    submit_payload = _command_payload("submit_order", event_id="cmd-replay-guard")
    submit_payload["amount_base"] = 0.03
    submit_payload["price"] = 10_005.0
    submit_result = handle_command_payload(
        payload=submit_payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=5_000,
        now_ms=1_010,
    )
    assert submit_result.status == "processed"

    settings = ServiceSettings(
        service_instance_name="paper_exchange",
        consumer_group="grp",
        market_data_stream="hb.market_data.v1",
        event_stream="hb.paper_exchange.event.v1",
        allowed_connectors={"bitget_perpetual"},
    )
    fake_client = _FakeRedisClient(xadd_result="202-0")
    replay_payload = _market_snapshot_payload(
        timestamp_ms=1_100,
        best_bid=10_003.0,
        best_ask=10_004.0,
        best_ask_size=0.01,
    )
    replay_payload["event_id"] = "evt-replay-same"
    process_market_rows(
        rows=[("21-0", replay_payload)],
        source="new",
        client=fake_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
    )
    order = state.orders_by_id["ord-cmd-replay-guard"]
    assert order.state == "partially_filled"
    assert abs(order.filled_base - 0.01) < 1e-9
    assert len(fake_client.xadd_calls) == 1

    # Replay identical snapshot event_id: should not produce another fill.
    process_market_rows(
        rows=[("21-1", replay_payload)],
        source="reclaimed",
        client=fake_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
    )
    order = state.orders_by_id["ord-cmd-replay-guard"]
    assert order.state == "partially_filled"
    assert abs(order.filled_base - 0.01) < 1e-9
    assert len(fake_client.xadd_calls) == 1
    assert state.reclaimed_pending_market_entries == 1


def test_process_market_rows_skips_republish_when_fill_event_already_journaled() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000, best_bid=9_990.0, best_ask=10_010.0, best_ask_size=0.05),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    submit_payload = _command_payload("submit_order", event_id="cmd-journal-dedup")
    submit_payload["amount_base"] = 0.01
    submit_payload["price"] = 10_005.0
    submit_result = handle_command_payload(
        payload=submit_payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=5_000,
        now_ms=1_010,
    )
    assert submit_result.status == "processed"

    settings = ServiceSettings(
        service_instance_name="paper_exchange",
        consumer_group="grp",
        market_data_stream="hb.market_data.v1",
        event_stream="hb.paper_exchange.event.v1",
        allowed_connectors={"bitget_perpetual"},
    )
    fake_client = _FakeRedisClient(xadd_result="203-0")
    payload = _market_snapshot_payload(
        timestamp_ms=1_100,
        best_bid=10_003.0,
        best_ask=10_004.0,
        best_ask_size=0.05,
    )
    payload["event_id"] = "evt-journal-dedup"
    event_id = "pe-fill-evt-journal-dedup-ord-cmd-journal-dedup-1"
    state.market_fill_events_by_id[event_id] = 1
    state.market_fill_journal_next_seq = 1
    process_market_rows(
        rows=[("22-0", payload)],
        source="reclaimed",
        client=fake_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
    )
    # Fill state applied from replay, but event is not republished.
    assert len(fake_client.xadd_calls) == 0
    assert len(fake_client.acks) == 1
    assert state.deduplicated_market_fill_events == 1
    assert state.orders_by_id["ord-cmd-journal-dedup"].state == "filled"


def test_process_market_rows_replay_reserves_consumed_liquidity_from_terminal_orders() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000, best_bid=9_990.0, best_ask=10_010.0, best_ask_size=0.05),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True

    order_a = _command_payload("submit_order", event_id="cmd-replay-a")
    order_a["amount_base"] = 0.01
    order_a["price"] = 10_005.0
    result_a = handle_command_payload(
        payload=order_a,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=5_000,
        now_ms=1_010,
    )
    assert result_a.status == "processed"

    order_b = _command_payload("submit_order", event_id="cmd-replay-b")
    order_b["amount_base"] = 0.02
    order_b["price"] = 10_005.0
    result_b = handle_command_payload(
        payload=order_b,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=5_000,
        now_ms=1_011,
    )
    assert result_b.status == "processed"

    settings = ServiceSettings(
        service_instance_name="paper_exchange",
        consumer_group="grp",
        market_data_stream="hb.market_data.v1",
        event_stream="hb.paper_exchange.event.v1",
        allowed_connectors={"bitget_perpetual"},
    )
    first_pass_client = _SequencedFakeRedisClient(results=["301-0", None])
    replay_payload = _market_snapshot_payload(
        timestamp_ms=1_100,
        best_bid=10_003.0,
        best_ask=10_004.0,
        best_ask_size=0.02,
    )
    replay_payload["event_id"] = "evt-replay-liquidity"

    process_market_rows(
        rows=[("31-0", replay_payload)],
        source="new",
        client=first_pass_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
    )
    # First order gets published and filled, second publish fails -> row not acked.
    assert len(first_pass_client.xadd_calls) == 2
    assert len(first_pass_client.acks) == 0
    assert state.orders_by_id["ord-cmd-replay-a"].state == "filled"
    assert state.orders_by_id["ord-cmd-replay-b"].state == "working"

    replay_client = _FakeRedisClient(xadd_result="302-0")
    process_market_rows(
        rows=[("31-1", replay_payload)],
        source="reclaimed",
        client=replay_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
    )
    # Liquidity consumed by order A in same snapshot must remain reserved on replay.
    assert len(replay_client.xadd_calls) == 1
    replay_fill_payload = replay_client.xadd_calls[0][1]
    assert replay_fill_payload["metadata"]["fill_amount_base"] == "0.01"
    assert len(replay_client.acks) == 1
    assert state.orders_by_id["ord-cmd-replay-b"].state == "partially_filled"
    assert abs(state.orders_by_id["ord-cmd-replay-b"].filled_base - 0.01) < 1e-9


def test_process_market_rows_persists_market_fill_journal_bounded(tmp_path: Path) -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000, best_bid=9_990.0, best_ask=10_010.0, best_ask_size=0.05),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True

    payload_a = _command_payload("submit_order", event_id="cmd-journal-a")
    payload_a["amount_base"] = 0.01
    payload_a["price"] = 10_005.0
    payload_b = _command_payload("submit_order", event_id="cmd-journal-b")
    payload_b["amount_base"] = 0.01
    payload_b["price"] = 10_005.0
    handle_command_payload(
        payload=payload_a,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=5_000,
        now_ms=1_010,
    )
    handle_command_payload(
        payload=payload_b,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=5_000,
        now_ms=1_011,
    )

    settings = ServiceSettings(
        service_instance_name="paper_exchange",
        consumer_group="grp",
        market_data_stream="hb.market_data.v1",
        event_stream="hb.paper_exchange.event.v1",
        allowed_connectors={"bitget_perpetual"},
        market_fill_journal_max_entries=1,
    )
    fake_client = _FakeRedisClient(xadd_result="303-0")
    journal_path = tmp_path / "market_fill_journal.json"
    payload = _market_snapshot_payload(
        timestamp_ms=1_100,
        best_bid=10_003.0,
        best_ask=10_004.0,
        best_ask_size=0.05,
    )
    payload["event_id"] = "evt-journal-bounded"
    process_market_rows(
        rows=[("32-0", payload)],
        source="new",
        client=fake_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
        market_fill_journal_path=journal_path,
    )
    loaded = _load_market_fill_journal(journal_path)
    assert len(loaded) == 1
    assert "pe-fill-evt-journal-bounded-ord-cmd-journal-b-1" in loaded
    assert state.market_fill_journal_next_seq == 2


def test_process_market_rows_not_acked_when_fill_journal_persist_fails(tmp_path: Path) -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000, best_bid=9_990.0, best_ask=10_010.0),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    submit_payload = _command_payload("submit_order", event_id="cmd-journal-fail")
    submit_payload["amount_base"] = 0.01
    submit_payload["price"] = 10_005.0
    submit_result = handle_command_payload(
        payload=submit_payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=5_000,
        now_ms=1_010,
    )
    assert submit_result.status == "processed"

    settings = ServiceSettings(
        service_instance_name="paper_exchange",
        consumer_group="grp",
        market_data_stream="hb.market_data.v1",
        event_stream="hb.paper_exchange.event.v1",
        allowed_connectors={"bitget_perpetual"},
    )
    fake_client = _FakeRedisClient(xadd_result="304-0")
    # Directory target makes atomic replace fail and should keep row pending.
    process_market_rows(
        rows=[("33-0", _market_snapshot_payload(timestamp_ms=1_100, best_bid=10_003.0, best_ask=10_004.0))],
        source="new",
        client=fake_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
        market_fill_journal_path=tmp_path,
    )
    assert state.market_fill_journal_write_failures == 1
    assert state.market_rows_not_acked == 1
    assert len(fake_client.acks) == 0


def test_process_market_rows_enforces_fill_cap_and_requires_replay() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000, best_bid=9_990.0, best_ask=10_010.0, best_ask_size=0.05),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    for idx in (1, 2):
        payload = _command_payload("submit_order", event_id=f"cmd-cap-{idx}")
        payload["amount_base"] = 0.01
        payload["price"] = 10_005.0
        result = handle_command_payload(
            payload=payload,
            state=state,
            service_instance_name="paper_exchange",
            allowed_connectors={"bitget_perpetual"},
            market_stale_after_ms=5_000,
            now_ms=1_010 + idx,
        )
        assert result.status == "processed"

    settings = ServiceSettings(
        service_instance_name="paper_exchange",
        consumer_group="grp",
        market_data_stream="hb.market_data.v1",
        event_stream="hb.paper_exchange.event.v1",
        allowed_connectors={"bitget_perpetual"},
        max_fill_events_per_market_row=1,
    )
    fake_client = _FakeRedisClient(xadd_result="305-0")
    payload = _market_snapshot_payload(
        timestamp_ms=1_100,
        best_bid=10_003.0,
        best_ask=10_004.0,
        best_ask_size=0.05,
    )
    payload["event_id"] = "evt-cap"
    process_market_rows(
        rows=[("34-0", payload)],
        source="new",
        client=fake_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
    )
    # Only one fill processed this pass; row remains pending for replay.
    assert len(fake_client.xadd_calls) == 1
    assert len(fake_client.acks) == 0
    assert state.market_row_fill_cap_hits == 1
    assert state.market_rows_not_acked == 1
    assert state.orders_by_id["ord-cmd-cap-1"].state == "filled"
    assert state.orders_by_id["ord-cmd-cap-2"].state == "working"


def test_process_market_rows_does_not_mutate_order_when_fill_publish_fails() -> None:
    state = PaperExchangeState()
    ok, _ = ingest_market_snapshot_payload(
        payload=_market_snapshot_payload(timestamp_ms=1_000, best_bid=9_990.0, best_ask=10_010.0),
        state=state,
        allowed_connectors={"bitget_perpetual"},
    )
    assert ok is True
    submit_payload = _command_payload("submit_order", event_id="cmd-fill-fail")
    submit_payload["amount_base"] = 0.02
    submit_payload["price"] = 10_005.0
    submit_result = handle_command_payload(
        payload=submit_payload,
        state=state,
        service_instance_name="paper_exchange",
        allowed_connectors={"bitget_perpetual"},
        market_stale_after_ms=5_000,
        now_ms=1_010,
    )
    assert submit_result.status == "processed"

    settings = ServiceSettings(
        service_instance_name="paper_exchange",
        consumer_group="grp",
        market_data_stream="hb.market_data.v1",
        event_stream="hb.paper_exchange.event.v1",
        allowed_connectors={"bitget_perpetual"},
    )
    fake_client = _FakeRedisClient(xadd_result=None)
    process_market_rows(
        rows=[("13-0", _market_snapshot_payload(timestamp_ms=1_100, best_bid=10_003.0, best_ask=10_004.0))],
        source="new",
        client=fake_client,  # type: ignore[arg-type]
        state=state,
        settings=settings,
    )
    order = state.orders_by_id["ord-cmd-fill-fail"]
    assert order.state == "working"
    assert abs(order.filled_base - 0.0) < 1e-12
    assert state.market_fill_publish_failures == 1
    assert state.market_rows_not_acked == 1
    assert len(fake_client.acks) == 0


def test_prune_orders_removes_old_terminal_orders() -> None:
    state = PaperExchangeState()
    state.orders_by_id["ord-terminal"] = OrderRecord(
        order_id="ord-terminal",
        instance_name="bot1",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        side="buy",
        order_type="limit",
        amount_base=0.01,
        price=10_000.0,
        time_in_force="gtc",
        reduce_only=False,
        post_only=False,
        state="cancelled",
        created_ts_ms=0,
        updated_ts_ms=0,
        last_command_event_id="cmd-1",
    )
    state.orders_by_id["ord-active"] = OrderRecord(
        order_id="ord-active",
        instance_name="bot1",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        side="buy",
        order_type="limit",
        amount_base=0.01,
        price=10_000.0,
        time_in_force="gtc",
        reduce_only=False,
        post_only=False,
        state="working",
        created_ts_ms=0,
        updated_ts_ms=0,
        last_command_event_id="cmd-2",
    )
    removed = _prune_orders(
        state=state,
        now_ms=10_000,
        terminal_order_ttl_ms=1_000,
        max_orders_tracked=10,
    )
    assert removed == 1
    assert "ord-terminal" not in state.orders_by_id
    assert "ord-active" in state.orders_by_id
    assert state.orders_pruned_total == 1


def test_prune_orders_caps_max_orders_preferring_terminal() -> None:
    state = PaperExchangeState()
    state.orders_by_id["ord-terminal"] = OrderRecord(
        order_id="ord-terminal",
        instance_name="bot1",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        side="buy",
        order_type="limit",
        amount_base=0.01,
        price=10_000.0,
        time_in_force="gtc",
        reduce_only=False,
        post_only=False,
        state="cancelled",
        created_ts_ms=100,
        updated_ts_ms=100,
        last_command_event_id="cmd-t",
    )
    state.orders_by_id["ord-active-old"] = OrderRecord(
        order_id="ord-active-old",
        instance_name="bot1",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        side="buy",
        order_type="limit",
        amount_base=0.01,
        price=10_000.0,
        time_in_force="gtc",
        reduce_only=False,
        post_only=False,
        state="working",
        created_ts_ms=200,
        updated_ts_ms=200,
        last_command_event_id="cmd-a1",
    )
    state.orders_by_id["ord-active-new"] = OrderRecord(
        order_id="ord-active-new",
        instance_name="bot1",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        side="sell",
        order_type="limit",
        amount_base=0.01,
        price=10_001.0,
        time_in_force="gtc",
        reduce_only=False,
        post_only=False,
        state="working",
        created_ts_ms=300,
        updated_ts_ms=300,
        last_command_event_id="cmd-a2",
    )
    removed = _prune_orders(
        state=state,
        now_ms=400,
        terminal_order_ttl_ms=0,
        max_orders_tracked=2,
    )
    assert removed == 1
    assert "ord-terminal" not in state.orders_by_id
    assert "ord-active-old" in state.orders_by_id
    assert "ord-active-new" in state.orders_by_id

