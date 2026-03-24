from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from platform_lib.contracts.event_schemas import PaperExchangeCommandEvent


@dataclass(frozen=True)
class ExecutionOrderState:
    instance_name: str
    connector_name: str
    trading_pair: str
    order_id: str
    state: str
    side: str = ""
    order_type: str = ""
    amount_base: float | None = None
    price: float | None = None
    created_ts_ms: int | None = None
    updated_ts_ms: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionPositionState:
    instance_name: str
    trading_pair: str
    quantity: float = 0.0
    avg_entry_price: float | None = None
    unrealized_pnl_quote: float | None = None
    side: str = "flat"
    metadata: dict[str, str] = field(default_factory=dict)


def build_paper_execution_command(
    *,
    producer: str,
    instance_name: str,
    connector_name: str,
    trading_pair: str,
    command: str,
    metadata: dict[str, str] | None = None,
    order_id: str | None = None,
    side: str | None = None,
    order_type: str | None = None,
    amount_base: float | None = None,
    price: float | None = None,
    reduce_only: bool = False,
    position_action: str | None = None,
    position_mode: str | None = None,
    ttl_ms: int = 30_000,
    event_id: str | None = None,
) -> PaperExchangeCommandEvent:
    now_ms = int(time.time() * 1000)
    return PaperExchangeCommandEvent(
        event_id=str(event_id or uuid.uuid4()),
        producer=str(producer),
        instance_name=str(instance_name),
        command=command,  # type: ignore[arg-type]
        connector_name=str(connector_name),
        trading_pair=str(trading_pair),
        order_id=str(order_id) if order_id else None,
        side=side.lower() if isinstance(side, str) else None,  # type: ignore[arg-type]
        order_type=str(order_type).strip().lower() if order_type else None,
        amount_base=float(amount_base) if amount_base is not None else None,
        price=float(price) if price is not None else None,
        expires_at_ms=now_ms + max(1_000, int(ttl_ms)),
        reduce_only=bool(reduce_only),
        position_action=str(position_action).strip().lower() if position_action else None,
        position_mode=str(position_mode).strip().upper() if position_mode else None,
        metadata=dict(metadata or {}),
    )
