from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

from services.contracts.event_schemas import PaperExchangeCommandEvent


@dataclass(frozen=True)
class ExecutionOrderState:
    instance_name: str
    connector_name: str
    trading_pair: str
    order_id: str
    state: str
    side: str = ""
    order_type: str = ""
    amount_base: Optional[float] = None
    price: Optional[float] = None
    created_ts_ms: Optional[int] = None
    updated_ts_ms: Optional[int] = None
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionPositionState:
    instance_name: str
    trading_pair: str
    quantity: float = 0.0
    avg_entry_price: Optional[float] = None
    unrealized_pnl_quote: Optional[float] = None
    side: str = "flat"
    metadata: Dict[str, str] = field(default_factory=dict)


def build_paper_execution_command(
    *,
    producer: str,
    instance_name: str,
    connector_name: str,
    trading_pair: str,
    command: str,
    metadata: Optional[Dict[str, str]] = None,
    order_id: Optional[str] = None,
    side: Optional[str] = None,
    order_type: Optional[str] = None,
    amount_base: Optional[float] = None,
    price: Optional[float] = None,
    reduce_only: bool = False,
    position_action: Optional[str] = None,
    position_mode: Optional[str] = None,
    ttl_ms: int = 30_000,
    event_id: Optional[str] = None,
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
