from __future__ import annotations

from controllers.runtime.execution_context import RuntimeExecutionPlan
from controllers.runtime.market_making_core import MarketMakingRuntimeAdapter


class DirectionalRuntimeAdapter(MarketMakingRuntimeAdapter):
    """Directional execution-family adapter over the shared HB executor plumbing."""

    def apply_execution_plan(self, plan: RuntimeExecutionPlan, *, equity_quote, mid, quote_size_pct) -> None:
        # Directional lanes may still emit two-sided warmup or defensive fallback plans.
        super().apply_execution_plan(
            plan,
            equity_quote=equity_quote,
            mid=mid,
            quote_size_pct=quote_size_pct,
        )


__all__ = ["DirectionalRuntimeAdapter"]
