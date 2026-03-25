"""Unified Paper Exchange Service backed by PaperDesk.

Replaces the legacy monolith ``main.py`` with a thin service wrapper that:
- Owns one ``PaperDesk`` per ``instance_name`` (tenant isolation)
- Consumes ``hb.paper_exchange.command.v1`` and ``hb.market_data.v1``
- Produces ``hb.paper_exchange.event.v1`` and ``hb.paper_exchange.heartbeat.v1``
- Projects state into compatibility snapshot JSON files

The PaperDesk library handles all accounting, matching, and risk.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from simulation.desk import DeskConfig, PaperDesk
from simulation.portfolio import PortfolioConfig
from simulation.types import (
    _ZERO,
    InstrumentId,
    OrderFilled,
    OrderSide,
    PaperOrderType,
    PositionAction,
)
from platform_lib.market_data.canonical_market_state import (
    parse_canonical_market_state,
)
from platform_lib.core.latency_tracker import JsonLatencyTracker
from platform_lib.contracts.event_identity import validate_event_identity
from platform_lib.contracts.event_schemas import (
    PaperExchangeEvent,
)
from platform_lib.contracts.stream_names import (
    AUDIT_STREAM,
    MARKET_DATA_STREAM,
    PAPER_EXCHANGE_COMMAND_STREAM,
    PAPER_EXCHANGE_EVENT_STREAM,
    PAPER_EXCHANGE_HEARTBEAT_STREAM,
    STREAM_RETENTION_MAXLEN,
)
from services.hb_bridge.redis_client import RedisStreamClient
from services.paper_exchange_service.compat_projection import (
    TenantProjectionInput,
    project_pair_snapshot,
    project_state_snapshot,
)
from services.paper_exchange_service.event_translator import (
    build_audit_event,
    build_heartbeat,
    build_market_fill_event,
    engine_event_to_pe_event,
)
from services.paper_exchange_service.instrument_registry import (
    InstrumentRegistry,
    make_instrument_id,
)
from services.paper_exchange_service.redis_feed import RedisMarketFeed

logger = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize(value: str) -> str:
    return str(value or "").strip().lower()


def _canonical_connector_name(value: str) -> str:
    raw = str(value or "").strip()
    if raw.endswith("_paper_trade"):
        return raw[:-12]
    return raw


def _csv_set(value: str) -> set[str]:
    return {_normalize(x) for x in str(value or "").split(",") if _normalize(x)}


# ---------------------------------------------------------------------------
# Service settings
# ---------------------------------------------------------------------------

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
    market_stale_after_ms: int = 15_000
    heartbeat_interval_ms: int = 5_000
    read_count: int = 100
    read_block_ms: int = 1_000
    state_snapshot_path: str = "reports/verification/paper_exchange_state_snapshot_latest.json"
    pair_snapshot_path: str = "reports/verification/paper_exchange_pair_snapshot_latest.json"
    persistence_flush_interval_ms: int = 250
    pair_snapshot_flush_interval_ms: int = 1_000
    latency_report_path: str = "reports/verification/paper_exchange_hot_path_latest.json"
    pending_reclaim_enabled: bool = True
    pending_reclaim_idle_ms: int = 120_000
    pending_reclaim_interval_ms: int = 15_000
    pending_reclaim_count: int = 100
    market_pending_reclaim_enabled: bool = True
    market_pending_reclaim_idle_ms: int = 120_000
    market_pending_reclaim_interval_ms: int = 15_000
    market_pending_reclaim_count: int = 100
    # -- Desk engine defaults (per-tenant PaperDesk) --
    initial_equity_quote: Decimal = Decimal("500")
    quote_currency: str = "USDT"
    default_fill_model: str = "queue_position"
    default_fee_source: str = "instrument_spec"
    default_latency_model: str = "none"
    state_file_dir: str = "/workspace/hbot/data"
    redis_key_prefix: str = "paper_desk:svc"
    reset_state_on_startup: bool = False


# ---------------------------------------------------------------------------
# Tenant runtime
# ---------------------------------------------------------------------------

@dataclass
class TenantRuntime:
    """Isolated per-instance_name runtime wrapping a PaperDesk."""

    instance_name: str
    desk: PaperDesk
    feed: RedisMarketFeed
    instrument_registry: InstrumentRegistry
    connector_name: str = ""
    last_tick_ms: int = 0
    processed_commands: int = 0
    generated_fills: int = 0

    def ensure_instrument(
        self,
        connector_name: str,
        trading_pair: str,
        metadata: dict[str, str] | None = None,
    ) -> InstrumentId:
        """Lazily register an instrument into the desk if not yet registered."""
        spec = self.instrument_registry.resolve(connector_name, trading_pair, metadata)
        iid = spec.instrument_id
        key = iid.key
        if key not in self.desk._engines:
            self.desk.register_instrument(spec, self.feed)
        return iid


class TenantRouter:
    """Manages tenant desk lifecycles. One PaperDesk per instance_name."""

    def __init__(self, settings: ServiceSettings):
        self._tenants: dict[str, TenantRuntime] = {}
        self._settings = settings

    def get_or_create(self, instance_name: str) -> TenantRuntime:
        iname = _normalize(instance_name)
        t = self._tenants.get(iname)
        if t is not None:
            return t

        s = self._settings
        desk = PaperDesk(DeskConfig(
            initial_balances={s.quote_currency: s.initial_equity_quote},
            portfolio_config=PortfolioConfig(),
            default_fill_model=s.default_fill_model,
            default_fee_source=s.default_fee_source,
            default_latency_model=s.default_latency_model,
            state_file_path=f"{s.state_file_dir}/{iname}/paper_desk_svc.json",
            redis_key=f"{s.redis_key_prefix}:{iname}",
            redis_url=os.getenv("REDIS_URL"),
            reset_state_on_startup=s.reset_state_on_startup,
        ))
        feed = RedisMarketFeed()
        t = TenantRuntime(
            instance_name=iname,
            desk=desk,
            feed=feed,
            instrument_registry=InstrumentRegistry(),
        )
        self._tenants[iname] = t
        logger.info("TenantRouter: created tenant desk for %s", iname)
        return t

    def get(self, instance_name: str) -> TenantRuntime | None:
        return self._tenants.get(_normalize(instance_name))

    def all_tenants(self) -> list[TenantRuntime]:
        return list(self._tenants.values())

    def close_all(self) -> None:
        for t in self._tenants.values():
            try:
                t.desk.close()
            except Exception as exc:
                logger.warning("TenantRouter: close failed for %s: %s", t.instance_name, exc)


# ---------------------------------------------------------------------------
# Market data processing
# ---------------------------------------------------------------------------

def _process_market_row(
    payload: dict[str, Any],
    router: TenantRouter,
    pairs_data: dict[str, dict[str, Any]],
    settings: ServiceSettings,
) -> None:
    """Parse a market_snapshot row, update feeds for all relevant tenants."""
    cms = parse_canonical_market_state(payload)
    if cms is None:
        return

    connector_name = _canonical_connector_name(
        str(getattr(cms, "connector_name", "") or payload.get("connector_name", ""))
    )
    trading_pair = str(getattr(cms, "trading_pair", "") or payload.get("trading_pair", "")).strip().upper()
    instance_name = str(getattr(cms, "instance_name", "") or payload.get("instance_name", "")).strip().lower()

    if not connector_name or not trading_pair:
        return

    if settings.allowed_connectors and _normalize(connector_name) not in settings.allowed_connectors:
        return

    iid = make_instrument_id(connector_name, trading_pair)
    best_bid = Decimal(str(getattr(cms, "best_bid", 0) or 0))
    best_ask = Decimal(str(getattr(cms, "best_ask", 0) or 0))
    best_bid_size = Decimal(str(getattr(cms, "best_bid_size", 1) or 1))
    best_ask_size = Decimal(str(getattr(cms, "best_ask_size", 1) or 1))
    funding_rate = Decimal(str(getattr(cms, "funding_rate", 0) or 0))
    ts_ms = int(getattr(cms, "timestamp_ms", 0) or 0) or _now_ms()

    bids: list[tuple[Decimal, Decimal]] = []
    asks: list[tuple[Decimal, Decimal]] = []

    bid_levels = getattr(cms, "bid_levels", None) or payload.get("bid_levels")
    ask_levels = getattr(cms, "ask_levels", None) or payload.get("ask_levels")

    if isinstance(bid_levels, list) and bid_levels:
        for lvl in bid_levels:
            if isinstance(lvl, (list, tuple)) and len(lvl) >= 2:
                p, s = Decimal(str(lvl[0])), Decimal(str(lvl[1]))
                if p > _ZERO and s > _ZERO:
                    bids.append((p, s))
    if not bids and best_bid > _ZERO:
        bids.append((best_bid, best_bid_size))

    if isinstance(ask_levels, list) and ask_levels:
        for lvl in ask_levels:
            if isinstance(lvl, (list, tuple)) and len(lvl) >= 2:
                p, s = Decimal(str(lvl[0])), Decimal(str(lvl[1]))
                if p > _ZERO and s > _ZERO:
                    asks.append((p, s))
    if not asks and best_ask > _ZERO:
        asks.append((best_ask, best_ask_size))

    if not bids and not asks:
        return

    target_tenants: list[TenantRuntime] = []
    if instance_name:
        t = router.get(instance_name)
        if t is not None:
            target_tenants.append(t)
    if not target_tenants:
        target_tenants = router.all_tenants()

    for t in target_tenants:
        t.feed.update_book(iid, bids, asks, ts_ms, funding_rate)

    ns_key = f"{instance_name or '*'}::{connector_name}::{trading_pair}"
    pairs_data[ns_key] = {
        "connector_name": connector_name,
        "trading_pair": trading_pair,
        "instance_name": instance_name,
        "timestamp_ms": ts_ms,
        "freshness_ts_ms": ts_ms,
        "mid_price": float((bids[0][0] + asks[0][0]) / 2) if bids and asks else 0.0,
        "best_bid": float(bids[0][0]) if bids else None,
        "best_ask": float(asks[0][0]) if asks else None,
        "best_bid_size": float(bids[0][1]) if bids else None,
        "best_ask_size": float(asks[0][1]) if asks else None,
        "last_trade_price": None,
        "mark_price": None,
        "funding_rate": float(funding_rate),
        "exchange_ts_ms": None,
        "ingest_ts_ms": ts_ms,
        "market_sequence": 0,
        "event_id": "",
        "source_event_type": "market_snapshot",
        "bid_levels": [[float(p), float(s)] for p, s in bids],
        "ask_levels": [[float(p), float(s)] for p, s in asks],
        "namespace_key": ns_key,
    }


# ---------------------------------------------------------------------------
# Command processing
# ---------------------------------------------------------------------------

_PRIVILEGED_COMMANDS = {"sync_state", "cancel_all"}


def _handle_command(
    payload: dict[str, Any],
    router: TenantRouter,
    client: RedisStreamClient,
    settings: ServiceSettings,
) -> PaperExchangeEvent | None:
    """Parse and execute a single command, return the result event."""
    instance_name = str(payload.get("instance_name", "")).strip()
    command = str(payload.get("command", "")).strip().lower()
    connector_name = _canonical_connector_name(str(payload.get("connector_name", "")))
    trading_pair = str(payload.get("trading_pair", "")).strip().upper()
    command_event_id = str(payload.get("event_id", ""))
    position_action = str(payload.get("position_action", "auto") or "auto")
    position_mode = str(payload.get("position_mode", "ONEWAY") or "ONEWAY").upper()
    metadata = payload.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}

    if not instance_name or not connector_name or not trading_pair:
        return PaperExchangeEvent(
            producer="paper_exchange_service",
            instance_name=instance_name,
            command_event_id=command_event_id,
            command=command,
            status="rejected",
            reason="missing_required_fields",
            connector_name=connector_name,
            trading_pair=trading_pair,
        )

    if settings.allowed_connectors and _normalize(connector_name) not in settings.allowed_connectors:
        return PaperExchangeEvent(
            producer="paper_exchange_service",
            instance_name=instance_name,
            command_event_id=command_event_id,
            command=command,
            status="rejected",
            reason=f"connector_not_allowed:{connector_name}",
            connector_name=connector_name,
            trading_pair=trading_pair,
        )

    tenant = router.get_or_create(instance_name)
    tenant.connector_name = connector_name

    if command == "submit_order":
        return _handle_submit(tenant, payload, command_event_id, connector_name, trading_pair, position_action, position_mode, metadata)
    elif command == "cancel_order":
        return _handle_cancel(tenant, payload, command_event_id, connector_name, trading_pair, metadata)
    elif command == "cancel_all":
        return _handle_cancel_all(tenant, command_event_id, connector_name, trading_pair, metadata)
    elif command == "sync_state":
        return _handle_sync_state(tenant, command_event_id, connector_name, trading_pair, metadata)
    else:
        return PaperExchangeEvent(
            producer="paper_exchange_service",
            instance_name=instance_name,
            command_event_id=command_event_id,
            command=command,
            status="rejected",
            reason=f"unknown_command:{command}",
            connector_name=connector_name,
            trading_pair=trading_pair,
        )


def _handle_submit(
    tenant: TenantRuntime,
    payload: dict[str, Any],
    command_event_id: str,
    connector_name: str,
    trading_pair: str,
    position_action: str,
    position_mode: str,
    metadata: dict[str, str],
) -> PaperExchangeEvent:
    side_raw = str(payload.get("side", "")).strip().lower()
    order_type_raw = str(payload.get("order_type", "limit")).strip().lower()
    amount_base = float(payload.get("amount_base", 0) or 0)
    price = float(payload.get("price", 0) or 0)

    try:
        side = OrderSide(side_raw)
    except ValueError:
        return PaperExchangeEvent(
            producer="paper_exchange_service",
            instance_name=tenant.instance_name,
            command_event_id=command_event_id,
            command="submit_order",
            status="rejected",
            reason=f"invalid_side:{side_raw}",
            connector_name=connector_name,
            trading_pair=trading_pair,
        )

    ot_map = {"limit": PaperOrderType.LIMIT, "limit_maker": PaperOrderType.LIMIT_MAKER, "market": PaperOrderType.MARKET}
    order_type = ot_map.get(order_type_raw, PaperOrderType.LIMIT)

    try:
        pa = PositionAction(position_action.lower())
    except ValueError:
        pa = PositionAction.AUTO

    iid = tenant.ensure_instrument(connector_name, trading_pair, metadata)

    engine_event = tenant.desk.submit_order(
        instrument_id=iid,
        side=side,
        order_type=order_type,
        price=Decimal(str(price)),
        quantity=Decimal(str(amount_base)),
        source_bot=tenant.instance_name,
        position_action=pa,
        position_mode=position_mode,
    )
    tenant.processed_commands += 1

    return engine_event_to_pe_event(
        engine_event,
        command_event_id=command_event_id,
        command="submit_order",
        instance_name=tenant.instance_name,
        connector_name=connector_name,
        trading_pair=trading_pair,
        position_action=position_action,
        position_mode=position_mode,
        extra_metadata=metadata,
    )


def _handle_cancel(
    tenant: TenantRuntime,
    payload: dict[str, Any],
    command_event_id: str,
    connector_name: str,
    trading_pair: str,
    metadata: dict[str, str],
) -> PaperExchangeEvent:
    order_id = str(payload.get("order_id", "")).strip()
    if not order_id:
        return PaperExchangeEvent(
            producer="paper_exchange_service",
            instance_name=tenant.instance_name,
            command_event_id=command_event_id,
            command="cancel_order",
            status="rejected",
            reason="missing_order_id",
            connector_name=connector_name,
            trading_pair=trading_pair,
        )

    iid = tenant.ensure_instrument(connector_name, trading_pair, metadata)
    engine_event = tenant.desk.cancel_order(iid, order_id)
    tenant.processed_commands += 1

    return engine_event_to_pe_event(
        engine_event,
        command_event_id=command_event_id,
        command="cancel_order",
        instance_name=tenant.instance_name,
        connector_name=connector_name,
        trading_pair=trading_pair,
        extra_metadata=metadata,
    )


def _handle_cancel_all(
    tenant: TenantRuntime,
    command_event_id: str,
    connector_name: str,
    trading_pair: str,
    metadata: dict[str, str],
) -> PaperExchangeEvent:
    iid = tenant.ensure_instrument(connector_name, trading_pair, metadata)
    events = tenant.desk.cancel_all(iid)
    tenant.processed_commands += 1

    return PaperExchangeEvent(
        producer="paper_exchange_service",
        instance_name=tenant.instance_name,
        command_event_id=command_event_id,
        command="cancel_all",
        status="processed",
        connector_name=connector_name,
        trading_pair=trading_pair,
        metadata={**metadata, "cancelled_count": str(len(events))},
    )


def _handle_sync_state(
    tenant: TenantRuntime,
    command_event_id: str,
    connector_name: str,
    trading_pair: str,
    metadata: dict[str, str],
) -> PaperExchangeEvent:
    tenant.processed_commands += 1
    snap = tenant.desk.snapshot()

    return PaperExchangeEvent(
        producer="paper_exchange_service",
        instance_name=tenant.instance_name,
        command_event_id=command_event_id,
        command="sync_state",
        status="processed",
        connector_name=connector_name,
        trading_pair=trading_pair,
        metadata={**metadata, "snapshot_keys": str(list(snap.keys()))},
    )


# ---------------------------------------------------------------------------
# Main service loop
# ---------------------------------------------------------------------------

def run(settings: ServiceSettings) -> None:
    """Main event loop: consume market data and commands, produce events."""
    root = Path(os.getenv("HB_ROOT", os.getcwd()))
    state_snapshot_path = Path(settings.state_snapshot_path)
    pair_snapshot_path = Path(settings.pair_snapshot_path)
    if not state_snapshot_path.is_absolute():
        state_snapshot_path = root / state_snapshot_path
    if not pair_snapshot_path.is_absolute():
        pair_snapshot_path = root / pair_snapshot_path

    client = RedisStreamClient(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password or None,
        enabled=settings.redis_enabled,
    )

    client.create_group(settings.market_data_stream, settings.consumer_group)
    client.create_group(settings.command_stream, settings.consumer_group)

    latency_tracker = JsonLatencyTracker(settings.latency_report_path)
    router = TenantRouter(settings=settings)
    pairs_data: dict[str, dict[str, Any]] = {}

    last_heartbeat_ms = 0
    last_state_flush_ms = 0
    last_pair_flush_ms = 0
    last_pending_reclaim_ms = 0
    last_market_pending_reclaim_ms = 0
    loop_count = 0

    logger.info(
        "paper_exchange_service (desk_service) starting: streams=%s/%s, group=%s",
        settings.market_data_stream,
        settings.command_stream,
        settings.consumer_group,
    )

    try:
        while True:
            loop_started = time.perf_counter()
            loop_count += 1
            now = _now_ms()

            # -- Reclaim pending market entries --
            reclaimed_market_rows: list[tuple[str, dict[str, object]]] = []
            if (
                settings.market_pending_reclaim_enabled
                and (now - last_market_pending_reclaim_ms) >= settings.market_pending_reclaim_interval_ms
            ):
                reclaimed_market_rows = client.claim_pending(
                    stream=settings.market_data_stream,
                    group=settings.consumer_group,
                    consumer=settings.consumer_name,
                    min_idle_ms=settings.market_pending_reclaim_idle_ms,
                    count=settings.market_pending_reclaim_count,
                    start_id="0-0",
                )
                last_market_pending_reclaim_ms = now
                if reclaimed_market_rows:
                    logger.info("desk_service reclaimed pending market rows=%d", len(reclaimed_market_rows))

            if reclaimed_market_rows:
                for entry_id, row_payload in reclaimed_market_rows:
                    _process_market_row(row_payload, router, pairs_data, settings)
                client.ack_many(settings.market_data_stream, settings.consumer_group,
                                [eid for eid, _ in reclaimed_market_rows])

            # -- Read market data --
            market_rows = client.read_group(
                stream=settings.market_data_stream,
                group=settings.consumer_group,
                consumer=settings.consumer_name,
                count=settings.read_count,
                block_ms=min(max(1, settings.read_block_ms), 10),
            )
            if market_rows:
                started = time.perf_counter()
                ack_ids = []
                for entry_id, row_payload in market_rows:
                    _process_market_row(row_payload, router, pairs_data, settings)
                    ack_ids.append(str(entry_id))
                client.ack_many(settings.market_data_stream, settings.consumer_group, ack_ids)
                latency_tracker.observe("desk_svc_process_market_rows_ms", (time.perf_counter() - started) * 1000.0)

            # -- Tick all desks (market-driven fills) --
            now_ns = int(time.time() * 1_000_000_000)
            for tenant in router.all_tenants():
                tick_events = tenant.desk.tick(now_ns)
                for ev in tick_events:
                    if isinstance(ev, OrderFilled):
                        tenant.generated_fills += 1
                        fill_event = build_market_fill_event(
                            ev,
                            instance_name=tenant.instance_name,
                            connector_name=tenant.connector_name,
                            trading_pair=ev.instrument_id.trading_pair,
                        )
                        result_payload = fill_event.model_dump()
                        identity_ok, _ = validate_event_identity(result_payload)
                        if identity_ok:
                            client.xadd(
                                stream=settings.event_stream,
                                payload=result_payload,
                                maxlen=STREAM_RETENTION_MAXLEN.get(settings.event_stream),
                            )
                tenant.last_tick_ms = _now_ms()

            # -- Reclaim pending command entries --
            reclaimed_rows: list[tuple[str, dict[str, object]]] = []
            now = _now_ms()
            if (
                settings.pending_reclaim_enabled
                and (now - last_pending_reclaim_ms) >= settings.pending_reclaim_interval_ms
            ):
                reclaimed_rows = client.claim_pending(
                    stream=settings.command_stream,
                    group=settings.consumer_group,
                    consumer=settings.consumer_name,
                    min_idle_ms=settings.pending_reclaim_idle_ms,
                    count=settings.pending_reclaim_count,
                    start_id="0-0",
                )
                last_pending_reclaim_ms = now
                if reclaimed_rows:
                    logger.info("desk_service reclaimed pending commands=%d", len(reclaimed_rows))

            if reclaimed_rows:
                _process_command_batch(reclaimed_rows, router, client, settings, latency_tracker)

            # -- Read commands --
            command_rows = client.read_group(
                stream=settings.command_stream,
                group=settings.consumer_group,
                consumer=settings.consumer_name,
                count=settings.read_count,
                block_ms=1,
            )
            if command_rows:
                _process_command_batch(command_rows, router, client, settings, latency_tracker)

            # -- Periodic persistence --
            now = _now_ms()
            if (now - last_state_flush_ms) >= settings.persistence_flush_interval_ms:
                try:
                    inputs = [
                        TenantProjectionInput(
                            instance_name=t.instance_name,
                            connector_name=t.connector_name,
                            desk=t.desk,
                        )
                        for t in router.all_tenants()
                    ]
                    if inputs:
                        project_state_snapshot(inputs, state_snapshot_path)
                except Exception as exc:
                    logger.warning("desk_service state snapshot failed: %s", exc)
                last_state_flush_ms = now

            if (now - last_pair_flush_ms) >= settings.pair_snapshot_flush_interval_ms:
                try:
                    if pairs_data:
                        project_pair_snapshot(pairs_data, pair_snapshot_path)
                except Exception as exc:
                    logger.warning("desk_service pair snapshot failed: %s", exc)
                last_pair_flush_ms = now

            # -- Heartbeat --
            now = _now_ms()
            if now - last_heartbeat_ms >= settings.heartbeat_interval_ms:
                all_tenants = router.all_tenants()
                total_pairs = len(pairs_data)
                stale_count = 0
                ages: list[int] = []
                for t in all_tenants:
                    for key, engine in t.desk._engines.items():
                        age = t.feed.book_age_ms(engine._iid)
                        ages.append(age)
                        if age > settings.market_stale_after_ms:
                            stale_count += 1

                hb = build_heartbeat(
                    service_instance_name=settings.service_instance_name,
                    tenant_count=len(all_tenants),
                    total_pairs=total_pairs,
                    stale_pairs=stale_count,
                    newest_age_ms=min(ages) if ages else 0,
                    oldest_age_ms=max(ages) if ages else 0,
                    status="ok" if stale_count == 0 else "degraded",
                )
                client.xadd(
                    stream=settings.heartbeat_stream,
                    payload=hb.model_dump(),
                    maxlen=STREAM_RETENTION_MAXLEN.get(settings.heartbeat_stream),
                )
                latency_tracker.observe("desk_svc_loop_ms", (time.perf_counter() - loop_started) * 1000.0)
                latency_tracker.flush(
                    extra={
                        "tenant_count": len(all_tenants),
                        "total_pairs": total_pairs,
                    }
                )
                last_heartbeat_ms = now

    except KeyboardInterrupt:
        logger.info("desk_service interrupted")
    finally:
        router.close_all()


def _process_command_batch(
    rows: list[tuple[str, dict[str, object]]],
    router: TenantRouter,
    client: RedisStreamClient,
    settings: ServiceSettings,
    latency_tracker: JsonLatencyTracker,
) -> None:
    started = time.perf_counter()
    ack_ids = []

    for entry_id, payload in rows:
        result_event = _handle_command(payload, router, client, settings)
        if result_event is None:
            ack_ids.append(str(entry_id))
            continue

        result_payload = result_event.model_dump()
        identity_ok, identity_reason = validate_event_identity(result_payload)
        if not identity_ok:
            logger.warning(
                "desk_service command result dropped due to identity contract entry=%s reason=%s",
                entry_id, identity_reason,
            )
            ack_ids.append(str(entry_id))
            continue

        client.xadd(
            stream=settings.event_stream,
            payload=result_payload,
            maxlen=STREAM_RETENTION_MAXLEN.get(settings.event_stream),
        )

        command = str(payload.get("command", "")).strip().lower()
        if command in _PRIVILEGED_COMMANDS:
            audit = build_audit_event(
                command=command,
                instance_name=str(payload.get("instance_name", "")),
                connector_name=str(payload.get("connector_name", "")),
                trading_pair=str(payload.get("trading_pair", "")),
                result_status=result_event.status,
                result_reason=result_event.reason,
                command_metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
            )
            client.xadd(
                stream=settings.audit_stream,
                payload=audit.model_dump(),
                maxlen=STREAM_RETENTION_MAXLEN.get(settings.audit_stream),
            )

        ack_ids.append(str(entry_id))

    if ack_ids:
        client.ack_many(settings.command_stream, settings.consumer_group, ack_ids)

    latency_tracker.observe("desk_svc_process_command_rows_ms", (time.perf_counter() - started) * 1000.0)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> ServiceSettings:
    parser = argparse.ArgumentParser(description="Paper Exchange Service (PaperDesk-backed).")
    parser.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "127.0.0.1"))
    parser.add_argument("--redis-port", type=int, default=int(os.getenv("REDIS_PORT", "6379")))
    parser.add_argument("--redis-db", type=int, default=int(os.getenv("REDIS_DB", "0")))
    parser.add_argument("--redis-password", default=os.getenv("REDIS_PASSWORD", ""))
    parser.add_argument(
        "--redis-enabled",
        default=os.getenv("REDIS_STREAMS_ENABLED", "true"),
    )
    parser.add_argument(
        "--service-instance-name",
        default=os.getenv("PAPER_EXCHANGE_SERVICE_INSTANCE_NAME", "paper_exchange"),
    )
    parser.add_argument(
        "--consumer-group",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_GROUP", "hb_group_paper_exchange"),
    )
    parser.add_argument(
        "--consumer-name",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_NAME", f"paper-exchange-{os.getpid()}"),
    )
    parser.add_argument(
        "--market-stream",
        default=os.getenv("PAPER_EXCHANGE_MARKET_STREAM", MARKET_DATA_STREAM),
    )
    parser.add_argument(
        "--command-stream",
        default=os.getenv("PAPER_EXCHANGE_COMMAND_STREAM", PAPER_EXCHANGE_COMMAND_STREAM),
    )
    parser.add_argument(
        "--event-stream",
        default=os.getenv("PAPER_EXCHANGE_EVENT_STREAM", PAPER_EXCHANGE_EVENT_STREAM),
    )
    parser.add_argument(
        "--heartbeat-stream",
        default=os.getenv("PAPER_EXCHANGE_HEARTBEAT_STREAM", PAPER_EXCHANGE_HEARTBEAT_STREAM),
    )
    parser.add_argument(
        "--audit-stream",
        default=os.getenv("PAPER_EXCHANGE_AUDIT_STREAM", AUDIT_STREAM),
    )
    parser.add_argument(
        "--allowed-connectors",
        default=os.getenv("PAPER_EXCHANGE_ALLOWED_CONNECTORS", "bitget_perpetual"),
    )
    parser.add_argument(
        "--market-stale-after-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_MARKET_STALE_AFTER_MS", "15000")),
    )
    parser.add_argument(
        "--heartbeat-interval-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_HEARTBEAT_INTERVAL_MS", "5000")),
    )
    parser.add_argument(
        "--read-count",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_READ_COUNT", "100")),
    )
    parser.add_argument(
        "--read-block-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_READ_BLOCK_MS", "1000")),
    )
    parser.add_argument(
        "--state-snapshot-path",
        default=os.getenv(
            "PAPER_EXCHANGE_STATE_SNAPSHOT_PATH",
            "reports/verification/paper_exchange_state_snapshot_latest.json",
        ),
    )
    parser.add_argument(
        "--pair-snapshot-path",
        default=os.getenv(
            "PAPER_EXCHANGE_PAIR_SNAPSHOT_PATH",
            "reports/verification/paper_exchange_pair_snapshot_latest.json",
        ),
    )
    parser.add_argument(
        "--persistence-flush-interval-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_PERSISTENCE_FLUSH_INTERVAL_MS", "250")),
    )
    parser.add_argument(
        "--pair-snapshot-flush-interval-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_PAIR_SNAPSHOT_FLUSH_INTERVAL_MS", "1000")),
    )
    parser.add_argument(
        "--latency-report-path",
        default=os.getenv(
            "PAPER_EXCHANGE_LATENCY_REPORT_PATH",
            "reports/verification/paper_exchange_hot_path_latest.json",
        ),
    )
    parser.add_argument(
        "--initial-equity-quote",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_INITIAL_EQUITY_QUOTE", "500")),
    )
    parser.add_argument(
        "--pending-reclaim-enabled",
        default=os.getenv("PAPER_EXCHANGE_PENDING_RECLAIM_ENABLED", "true"),
    )
    parser.add_argument(
        "--pending-reclaim-idle-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_PENDING_RECLAIM_IDLE_MS", "30000")),
    )
    parser.add_argument(
        "--pending-reclaim-interval-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_PENDING_RECLAIM_INTERVAL_MS", "5000")),
    )
    parser.add_argument(
        "--pending-reclaim-count",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_PENDING_RECLAIM_COUNT", "100")),
    )
    parser.add_argument(
        "--market-pending-reclaim-enabled",
        default=os.getenv("PAPER_EXCHANGE_MARKET_PENDING_RECLAIM_ENABLED", "true"),
    )
    parser.add_argument(
        "--market-pending-reclaim-idle-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_MARKET_PENDING_RECLAIM_IDLE_MS", "30000")),
    )
    parser.add_argument(
        "--market-pending-reclaim-interval-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_MARKET_PENDING_RECLAIM_INTERVAL_MS", "5000")),
    )
    parser.add_argument(
        "--market-pending-reclaim-count",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_MARKET_PENDING_RECLAIM_COUNT", "100")),
    )
    # -- Desk engine defaults --
    parser.add_argument(
        "--quote-currency",
        default=os.getenv("PAPER_EXCHANGE_QUOTE_CURRENCY", "USDT"),
    )
    parser.add_argument(
        "--default-fill-model",
        default=os.getenv("PAPER_EXCHANGE_DEFAULT_FILL_MODEL", "queue_position"),
    )
    parser.add_argument(
        "--default-fee-source",
        default=os.getenv("PAPER_EXCHANGE_DEFAULT_FEE_SOURCE", "instrument_spec"),
    )
    parser.add_argument(
        "--default-latency-model",
        default=os.getenv("PAPER_EXCHANGE_DEFAULT_LATENCY_MODEL", "none"),
    )
    parser.add_argument(
        "--state-file-dir",
        default=os.getenv("PAPER_EXCHANGE_STATE_FILE_DIR", "/workspace/hbot/data"),
    )
    parser.add_argument(
        "--redis-key-prefix",
        default=os.getenv("PAPER_EXCHANGE_REDIS_KEY_PREFIX", "paper_desk:svc"),
    )
    parser.add_argument(
        "--reset-state-on-startup",
        default=os.getenv("PAPER_EXCHANGE_RESET_STATE_ON_STARTUP", "false"),
    )

    args = parser.parse_args()
    redis_enabled = str(args.redis_enabled).strip().lower() in {"1", "true", "yes", "on"}
    pending_reclaim_enabled = str(args.pending_reclaim_enabled).strip().lower() in {"1", "true", "yes", "on"}
    market_pending_reclaim_enabled = str(args.market_pending_reclaim_enabled).strip().lower() in {
        "1", "true", "yes", "on",
    }
    reset_state_on_startup = str(args.reset_state_on_startup).strip().lower() in {"1", "true", "yes", "on"}

    return ServiceSettings(
        redis_host=str(args.redis_host),
        redis_port=int(args.redis_port),
        redis_db=int(args.redis_db),
        redis_password=str(args.redis_password or ""),
        redis_enabled=redis_enabled,
        service_instance_name=str(args.service_instance_name),
        consumer_group=str(args.consumer_group),
        consumer_name=str(args.consumer_name),
        market_data_stream=str(args.market_stream),
        command_stream=str(args.command_stream),
        event_stream=str(args.event_stream),
        heartbeat_stream=str(args.heartbeat_stream),
        audit_stream=str(args.audit_stream),
        allowed_connectors=_csv_set(str(args.allowed_connectors)),
        market_stale_after_ms=max(1_000, int(args.market_stale_after_ms)),
        heartbeat_interval_ms=max(1_000, int(args.heartbeat_interval_ms)),
        read_count=max(1, int(args.read_count)),
        read_block_ms=max(1, int(args.read_block_ms)),
        state_snapshot_path=str(args.state_snapshot_path),
        pair_snapshot_path=str(args.pair_snapshot_path),
        persistence_flush_interval_ms=max(1, int(args.persistence_flush_interval_ms)),
        pair_snapshot_flush_interval_ms=max(1, int(args.pair_snapshot_flush_interval_ms)),
        latency_report_path=str(args.latency_report_path),
        initial_equity_quote=Decimal(str(args.initial_equity_quote)),
        pending_reclaim_enabled=pending_reclaim_enabled,
        pending_reclaim_idle_ms=max(1_000, int(args.pending_reclaim_idle_ms)),
        pending_reclaim_interval_ms=max(1_000, int(args.pending_reclaim_interval_ms)),
        pending_reclaim_count=max(1, int(args.pending_reclaim_count)),
        market_pending_reclaim_enabled=market_pending_reclaim_enabled,
        market_pending_reclaim_idle_ms=max(1_000, int(args.market_pending_reclaim_idle_ms)),
        market_pending_reclaim_interval_ms=max(1_000, int(args.market_pending_reclaim_interval_ms)),
        market_pending_reclaim_count=max(1, int(args.market_pending_reclaim_count)),
        quote_currency=str(args.quote_currency).strip().upper() or "USDT",
        default_fill_model=str(args.default_fill_model).strip(),
        default_fee_source=str(args.default_fee_source).strip(),
        default_latency_model=str(args.default_latency_model).strip(),
        state_file_dir=str(args.state_file_dir).strip(),
        redis_key_prefix=str(args.redis_key_prefix).strip(),
        reset_state_on_startup=reset_state_on_startup,
    )


def main() -> int:
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = _parse_args()
    try:
        run(settings)
    except KeyboardInterrupt:
        logger.info("paper_exchange_service (desk_service) interrupted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
