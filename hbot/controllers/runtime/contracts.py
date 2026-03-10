from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Protocol, Tuple, runtime_checkable

from controllers.runtime.data_context import RuntimeDataContext
from controllers.runtime.execution_context import RuntimeExecutionPlan
from controllers.runtime.risk_context import RuntimeRiskDecision
from controllers.types import ProcessedState


@dataclass(frozen=True)
class RuntimeCompatibilitySurface:
    """Frozen external compatibility settings for a runtime instance."""

    artifact_namespace: str
    daily_state_prefix: str
    telemetry_producer_prefix: str
    controller_contract_version: str = "runtime_v24"
    runtime_impl: str = "shared_mm_v24"


@dataclass(frozen=True)
class RuntimeSnapshotExtension:
    """Additive telemetry metadata that must not break v1 consumers."""

    metadata: Dict[str, str]


@runtime_checkable
class StrategyRuntimeHooks(Protocol):
    """Lane hook contract for the neutral runtime kernel."""

    def build_runtime_execution_plan(self, data_context: RuntimeDataContext) -> RuntimeExecutionPlan:
        ...

    def extend_runtime_processed_data(
        self,
        *,
        processed_data: ProcessedState,
        data_context: RuntimeDataContext,
        risk_decision: RuntimeRiskDecision,
        execution_plan: RuntimeExecutionPlan,
        snapshot: Dict[str, Any],
    ) -> None:
        ...


@runtime_checkable
class RuntimeFamilyAdapter(Protocol):
    """Execution-family adapter contract used by the neutral runtime kernel."""

    def build_execution_plan(self, data_context: RuntimeDataContext) -> RuntimeExecutionPlan:
        ...

    def apply_execution_plan(
        self,
        plan: RuntimeExecutionPlan,
        *,
        equity_quote: Decimal,
        mid: Decimal,
        quote_size_pct: Decimal,
    ) -> None:
        ...

    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal) -> Any:
        ...

    def executors_to_refresh(self) -> List[Any]:
        ...

    def get_price_and_amount(self, level_id: str) -> Tuple[Decimal, Decimal]:
        ...

    def _runtime_spreads_and_amounts_in_quote(self, trade_type: Any) -> Tuple[List[Decimal], List[Decimal]]:
        ...

    def runtime_required_base_amount(self, reference_price: Decimal) -> Decimal:
        ...

    def position_rebalance_floor(self, reference_price: Decimal) -> Decimal:
        ...


__all__ = [
    "RuntimeFamilyAdapter",
    "RuntimeCompatibilitySurface",
    "RuntimeSnapshotExtension",
    "StrategyRuntimeHooks",
]
