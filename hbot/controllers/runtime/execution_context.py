from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class RuntimeExecutionPlan:
    """Neutral pre-executor plan emitted by strategy lanes."""

    family: str
    buy_spreads: list[Decimal]
    sell_spreads: list[Decimal]
    projected_total_quote: Decimal
    size_mult: Decimal
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = ["RuntimeExecutionPlan"]
