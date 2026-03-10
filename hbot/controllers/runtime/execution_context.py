from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List


@dataclass(frozen=True)
class RuntimeExecutionPlan:
    """Neutral pre-executor plan emitted by strategy lanes."""

    family: str
    buy_spreads: List[Decimal]
    sell_spreads: List[Decimal]
    projected_total_quote: Decimal
    size_mult: Decimal
    metadata: Dict[str, Any] = field(default_factory=dict)


__all__ = ["RuntimeExecutionPlan"]
