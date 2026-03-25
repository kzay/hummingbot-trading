from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal

from platform_lib.contracts.stream_names import (
    AUDIT_STREAM,
    MARKET_DATA_STREAM,
    PAPER_EXCHANGE_COMMAND_STREAM,
    PAPER_EXCHANGE_EVENT_STREAM,
    PAPER_EXCHANGE_HEARTBEAT_STREAM,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize(value: str) -> str:
    return str(value or "").strip().lower()


def _canonical_connector_name(value: str) -> str:
    raw = str(value or "").strip()
    if not raw.endswith("_paper_trade"):
        return raw
    try:
        from platform_lib.market_data.exchange_profiles import resolve_profile

        profile = resolve_profile(raw)
        if isinstance(profile, dict):
            required_exchange = str(profile.get("requires_paper_trade_exchange", "") or "").strip()
            if required_exchange:
                return required_exchange
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Failed to resolve canonical connector name for %s", raw)
    return raw[:-12]


def _normalize_connector_name(value: str) -> str:
    return _normalize(_canonical_connector_name(value))


def _csv_set(value: str) -> set[str]:
    return {_normalize(x) for x in str(value or "").split(",") if _normalize(x)}


def _namespace_base_key(instance_name: str, connector_name: str, trading_pair: str) -> str:
    return (
        f"{_normalize(instance_name)}::"
        f"{_normalize_connector_name(connector_name)}::"
        f"{str(trading_pair or '').strip().upper()}"
    )


def _namespace_order_key(instance_name: str, connector_name: str, trading_pair: str, order_id: str) -> str:
    return f"{_namespace_base_key(instance_name, connector_name, trading_pair)}::{str(order_id or '').strip()}"


def _pair_key(instance_name: str, connector_name: str, trading_pair: str) -> str:
    return _namespace_base_key(instance_name, connector_name, trading_pair)


def _get_pair_snapshot(
    state: PaperExchangeState,
    instance_name: str,
    connector_name: str,
    trading_pair: str,
) -> PairSnapshot | None:
    exact = state.pairs.get(_pair_key(instance_name, connector_name, trading_pair))
    shared = state.pairs.get(_pair_key("", connector_name, trading_pair))
    if exact is None:
        return shared
    if shared is None:
        return exact
    return shared if int(shared.freshness_ts_ms) >= int(exact.freshness_ts_ms) else exact


@dataclass
class PairSnapshot:
    connector_name: str
    trading_pair: str
    instance_name: str
    timestamp_ms: int
    freshness_ts_ms: int
    mid_price: float
    best_bid: float | None
    best_ask: float | None
    best_bid_size: float | None
    best_ask_size: float | None
    last_trade_price: float | None
    mark_price: float | None
    funding_rate: float | None
    exchange_ts_ms: int | None
    ingest_ts_ms: int | None
    market_sequence: int | None
    event_id: str
    source_event_type: str
    bid_levels: tuple[tuple[float, float], ...] = ()
    ask_levels: tuple[tuple[float, float], ...] = ()


@dataclass
class OrderRecord:
    order_id: str
    instance_name: str
    connector_name: str
    trading_pair: str
    side: str
    order_type: str
    amount_base: float
    price: float
    time_in_force: str
    reduce_only: bool
    post_only: bool
    state: str
    created_ts_ms: int
    updated_ts_ms: int
    last_command_event_id: str
    last_fill_snapshot_event_id: str = ""
    first_fill_ts_ms: int = 0
    last_fill_amount_base: float = 0.0
    filled_base: float = 0.0
    filled_quote: float = 0.0
    fill_count: int = 0
    filled_fee_quote: float = 0.0
    margin_reserve_quote: float = 0.0
    maker_fee_pct: float = 0.0
    taker_fee_pct: float = 0.0
    leverage: float = 1.0
    margin_mode: str = "leveraged"
    funding_rate: float = 0.0
    position_action: str = "auto"
    position_mode: str = "ONEWAY"


@dataclass
class PositionRecord:
    instance_name: str
    connector_name: str
    trading_pair: str
    position_mode: str = "ONEWAY"
    long_base: float = 0.0
    long_avg_entry_price: float = 0.0
    short_base: float = 0.0
    short_avg_entry_price: float = 0.0
    realized_pnl_quote: float = 0.0
    funding_paid_quote: float = 0.0
    last_fill_ts_ms: int = 0
    last_funding_ts_ms: int = 0
    last_funding_rate: float = 0.0
    funding_event_count: int = 0


@dataclass
class PaperExchangeState:
    pairs: dict[str, PairSnapshot] = field(default_factory=dict)
    orders_by_id: dict[str, OrderRecord] = field(default_factory=dict)
    positions_by_key: dict[str, PositionRecord] = field(default_factory=dict)
    accepted_snapshots: int = 0
    rejected_snapshots: int = 0
    processed_commands: int = 0
    rejected_commands: int = 0
    rejected_commands_stale_market: int = 0
    rejected_commands_missing_market: int = 0
    rejected_commands_disallowed_connector: int = 0
    rejected_commands_unauthorized_producer: int = 0
    rejected_commands_missing_privileged_metadata: int = 0
    rejected_commands_namespace_collision: int = 0
    privileged_commands_processed: int = 0
    privileged_command_audit_published: int = 0
    privileged_command_audit_publish_failures: int = 0
    duplicate_command_events: int = 0
    reclaimed_pending_entries: int = 0
    command_publish_failures: int = 0
    command_latency_samples: int = 0
    command_latency_ms_sum: int = 0
    command_latency_ms_max: int = 0
    orders_pruned_total: int = 0
    generated_fill_events: int = 0
    generated_partial_fill_events: int = 0
    market_fill_publish_failures: int = 0
    market_match_cycles: int = 0
    reclaimed_pending_market_entries: int = 0
    market_rows_not_acked: int = 0
    deduplicated_market_fill_events: int = 0
    market_fill_invalid_transition_drops: int = 0
    market_fill_journal_write_failures: int = 0
    market_fill_journal_next_seq: int = 0
    market_fill_events_by_id: dict[str, int] = field(default_factory=dict)
    market_row_fill_cap_hits: int = 0
    command_results_by_id: dict[str, dict[str, object]] = field(default_factory=dict)
    funding_events_generated: int = 0
    funding_debit_events: int = 0
    funding_credit_events: int = 0
    funding_paid_quote_total: float = 0.0


@dataclass
class ServiceSettings:
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""
    redis_enabled: bool = True
    service_instance_name: str = "paper_exchange"
    consumer_group: str = "hb_group_paper_exchange"
    consumer_name: str = "paper-exchange-consumer"
    market_data_stream: str = MARKET_DATA_STREAM
    command_stream: str = PAPER_EXCHANGE_COMMAND_STREAM
    event_stream: str = PAPER_EXCHANGE_EVENT_STREAM
    heartbeat_stream: str = PAPER_EXCHANGE_HEARTBEAT_STREAM
    audit_stream: str = AUDIT_STREAM
    allowed_connectors: set[str] = field(default_factory=set)
    allowed_command_producers: set[str] = field(default_factory=set)
    market_stale_after_ms: int = 15_000
    resting_fill_latency_ms: int = 0
    maker_queue_participation: float = 1.0
    market_sweep_depth_levels: int = 1
    funding_interval_ms: int = 28_800_000
    max_fill_events_per_market_row: int = 200
    heartbeat_interval_ms: int = 5_000
    read_count: int = 100
    read_block_ms: int = 1_000
    command_journal_path: str = "reports/verification/paper_exchange_command_journal_latest.json"
    state_snapshot_path: str = "reports/verification/paper_exchange_state_snapshot_latest.json"
    pair_snapshot_path: str = "reports/verification/paper_exchange_pair_snapshot_latest.json"
    market_fill_journal_path: str = "reports/verification/paper_exchange_market_fill_journal_latest.json"
    market_fill_journal_max_entries: int = 200_000
    pending_reclaim_enabled: bool = True
    pending_reclaim_idle_ms: int = 120_000
    pending_reclaim_interval_ms: int = 15_000
    pending_reclaim_count: int = 100
    market_pending_reclaim_enabled: bool = True
    market_pending_reclaim_idle_ms: int = 120_000
    market_pending_reclaim_interval_ms: int = 15_000
    market_pending_reclaim_count: int = 100
    terminal_order_ttl_ms: int = 86_400_000
    max_orders_tracked: int = 200_000
    persist_sync_state_results: bool = True
    persistence_flush_interval_ms: int = 250
    pair_snapshot_flush_interval_ms: int = 1_000
    latency_report_path: str = "reports/verification/paper_exchange_hot_path_latest.json"


from platform_lib.contracts.event_schemas import PaperExchangeEvent


@dataclass
class FillCandidate:
    event_id: str
    command_event_id: str
    order_id: str
    new_state: str
    fill_price: float
    fill_amount_base: float
    fill_notional_quote: float
    remaining_amount_base: float
    is_maker: bool
    snapshot_event_id: str
    snapshot_market_sequence: int
    fill_count: int
    fill_fee_quote: float = 0.0
    fill_fee_rate_pct: float = 0.0
    margin_reserve_quote: float = 0.0
    funding_rate: float = 0.0


@dataclass
class FundingSettlementCandidate:
    position_key: str
    leg_side: str
    funding_rate: float
    charge_quote: float
    reference_price: float
    position_base: float
    position_notional_quote: float
    last_funding_ts_ms: int
    current_funding_ts_ms: int
    event: PaperExchangeEvent
