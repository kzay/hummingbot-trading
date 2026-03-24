from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from controllers.runtime.data_context import RuntimeDataContext
from controllers.runtime.execution_context import RuntimeExecutionPlan
from controllers.runtime.risk_context import RuntimeRiskDecision
from controllers.tick_types import TickSnapshot
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

    metadata: dict[str, str]


TelemetryField = tuple[str, str, Any]
"""(csv_column_name, processed_data_key, default_value)"""


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
        snapshot: TickSnapshot,
    ) -> None:
        ...

    def telemetry_fields(self) -> tuple[TelemetryField, ...]:
        """Declare strategy-specific telemetry fields for CSV/dashboard.

        Returns a tuple of (csv_column_name, processed_data_key, default_value).
        The runtime will automatically forward these from processed_data to the
        minute CSV and dashboard snapshot.  Strategies no longer need to be
        hardcoded in tick_emitter.py or epp_logging.py.
        """
        return ()


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

    def executors_to_refresh(self) -> list[Any]:
        ...

    def get_price_and_amount(self, level_id: str) -> tuple[Decimal, Decimal]:
        ...

    def _runtime_spreads_and_amounts_in_quote(self, trade_type: Any) -> tuple[list[Decimal], list[Decimal]]:
        ...

    def runtime_required_base_amount(self, reference_price: Decimal) -> Decimal:
        ...

    def position_rebalance_floor(self, reference_price: Decimal) -> Decimal:
        ...


__all__ = [
    "RuntimeCompatibilitySurface",
    "RuntimeFamilyAdapter",
    "RuntimeSnapshotExtension",
    "StrategyRuntimeHooks",
    "TelemetryField",
]
