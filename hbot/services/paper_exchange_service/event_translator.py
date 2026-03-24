"""Translate PaperDesk EngineEvents into Redis-contract PaperExchangeEvents.

The service emits ``PaperExchangeEvent`` / ``PaperExchangeHeartbeatEvent`` /
``AuditEvent`` on their respective Redis streams.  This module owns the
mapping from the internal ``EngineEvent`` hierarchy to those contract schemas.
"""
from __future__ import annotations

import os
import time
from typing import Any

from platform_lib.contracts.event_schemas import (
    AuditEvent,
    PaperExchangeEvent,
    PaperExchangeHeartbeatEvent,
)

_PRODUCER = os.getenv("PAPER_EXCHANGE_SERVICE_INSTANCE_NAME", "paper_exchange_service")


def _now_ms() -> int:
    return int(time.time() * 1000)


def engine_event_to_pe_event(
    engine_event: Any,
    *,
    command_event_id: str,
    command: str,
    instance_name: str,
    connector_name: str,
    trading_pair: str,
    position_action: str | None = None,
    position_mode: str | None = None,
    extra_metadata: dict[str, str] | None = None,
) -> PaperExchangeEvent:
    """Convert a single EngineEvent into the external contract event."""
    from simulation.types import (
        CancelRejected,
        OrderAccepted,
        OrderFilled,
        OrderRejected,
    )

    event_type_name = type(engine_event).__name__
    status = "processed"
    reason = ""
    order_id: str | None = getattr(engine_event, "order_id", None)

    if isinstance(engine_event, OrderRejected) or isinstance(engine_event, CancelRejected):
        status = "rejected"
        reason = engine_event.reason

    md = dict(extra_metadata or {})
    md["engine_event_type"] = event_type_name

    if isinstance(engine_event, OrderFilled):
        md["fill_price"] = str(engine_event.fill_price)
        md["fill_quantity"] = str(engine_event.fill_quantity)
        md["fee"] = str(engine_event.fee)
        md["is_maker"] = str(engine_event.is_maker).lower()
        md["remaining_quantity"] = str(engine_event.remaining_quantity)
        md["slippage_bps"] = str(engine_event.slippage_bps)
        position_action = getattr(engine_event, "position_action", position_action)

    if isinstance(engine_event, OrderAccepted):
        position_action = getattr(engine_event, "position_action", position_action)

    return PaperExchangeEvent(
        producer=_PRODUCER,
        instance_name=instance_name,
        command_event_id=command_event_id,
        command=command,
        status=status,
        reason=reason,
        connector_name=connector_name,
        trading_pair=trading_pair,
        order_id=order_id,
        position_action=position_action,
        position_mode=position_mode,
        metadata=md,
    )


def build_market_fill_event(
    engine_event: Any,
    *,
    instance_name: str,
    connector_name: str,
    trading_pair: str,
    position_action: str | None = None,
    position_mode: str | None = None,
) -> PaperExchangeEvent:
    """Build a PE event for a market-driven fill (no originating command)."""
    from simulation.types import OrderFilled

    md: dict[str, str] = {"engine_event_type": type(engine_event).__name__, "source": "market_tick"}
    order_id: str | None = getattr(engine_event, "order_id", None)

    if isinstance(engine_event, OrderFilled):
        md["fill_price"] = str(engine_event.fill_price)
        md["fill_quantity"] = str(engine_event.fill_quantity)
        md["fee"] = str(engine_event.fee)
        md["is_maker"] = str(engine_event.is_maker).lower()
        md["remaining_quantity"] = str(engine_event.remaining_quantity)
        md["side"] = str(getattr(engine_event, "side", "buy"))
        position_action = getattr(engine_event, "position_action", position_action)

    return PaperExchangeEvent(
        producer=_PRODUCER,
        instance_name=instance_name,
        command_event_id="",
        command="market_fill",
        status="processed",
        connector_name=connector_name,
        trading_pair=trading_pair,
        order_id=order_id,
        position_action=position_action,
        position_mode=position_mode,
        metadata=md,
    )


def build_heartbeat(
    *,
    service_instance_name: str,
    tenant_count: int,
    total_pairs: int,
    stale_pairs: int,
    newest_age_ms: int,
    oldest_age_ms: int,
    status: str = "ok",
) -> PaperExchangeHeartbeatEvent:
    return PaperExchangeHeartbeatEvent(
        producer=_PRODUCER,
        instance_name=service_instance_name,
        service_name=_PRODUCER,
        status=status,
        market_pairs_total=total_pairs,
        stale_pairs=stale_pairs,
        newest_snapshot_age_ms=newest_age_ms,
        oldest_snapshot_age_ms=oldest_age_ms,
        metadata={"tenant_count": str(tenant_count)},
    )


def build_audit_event(
    *,
    command: str,
    instance_name: str,
    connector_name: str,
    trading_pair: str,
    result_status: str,
    result_reason: str,
    command_metadata: dict[str, str] | None = None,
) -> AuditEvent:
    md = dict(command_metadata or {})
    md["connector_name"] = connector_name
    md["trading_pair"] = trading_pair
    md["result_status"] = result_status
    md["result_reason"] = result_reason
    return AuditEvent(
        producer=_PRODUCER,
        instance_name=instance_name,
        severity="info",
        category=f"paper_exchange.{command}",
        message=f"command={command} status={result_status} reason={result_reason}",
        metadata=md,
    )
