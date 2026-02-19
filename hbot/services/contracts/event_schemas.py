from __future__ import annotations

import time
import uuid
from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field


SCHEMA_VERSION = "1.0"


def now_ms() -> int:
    return int(time.time() * 1000)


class EventEnvelope(BaseModel):
    schema_version: str = Field(default=SCHEMA_VERSION)
    event_type: str
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    producer: str
    timestamp_ms: int = Field(default_factory=now_ms)


class MarketSnapshotEvent(EventEnvelope):
    event_type: Literal["market_snapshot"] = "market_snapshot"
    instance_name: str
    controller_id: str
    connector_name: str
    trading_pair: str
    mid_price: float
    equity_quote: float
    base_pct: float
    target_base_pct: float
    spread_pct: float
    net_edge_pct: float
    turnover_x: float
    state: str
    extra: Dict[str, str] = Field(default_factory=dict)


class StrategySignalEvent(EventEnvelope):
    event_type: Literal["strategy_signal"] = "strategy_signal"
    instance_name: str
    signal_name: str
    signal_value: float
    confidence: float = 0.0
    metadata: Dict[str, str] = Field(default_factory=dict)


class MlSignalEvent(EventEnvelope):
    event_type: Literal["ml_signal"] = "ml_signal"
    instance_name: str
    controller_id: str
    trading_pair: str
    model_id: str
    model_version: str
    runtime: Literal["sklearn_joblib", "custom_python", "onnx"]
    horizon_s: int
    predicted_return: float
    confidence: float
    feature_hash: str
    inference_latency_ms: int
    signal_age_ms: int = 0
    inference_ts_ms: int = Field(default_factory=now_ms)
    metadata: Dict[str, str] = Field(default_factory=dict)


class RiskDecisionEvent(EventEnvelope):
    event_type: Literal["risk_decision"] = "risk_decision"
    instance_name: str
    approved: bool
    reason: str
    max_notional_quote: Optional[float] = None
    min_spread_pct: Optional[float] = None
    metadata: Dict[str, str] = Field(default_factory=dict)


class ExecutionIntentEvent(EventEnvelope):
    event_type: Literal["execution_intent"] = "execution_intent"
    instance_name: str
    controller_id: str
    action: Literal["set_target_base_pct", "soft_pause", "resume", "kill_switch"]
    target_base_pct: Optional[float] = None
    expires_at_ms: Optional[int] = None
    metadata: Dict[str, str] = Field(default_factory=dict)


class AuditEvent(EventEnvelope):
    event_type: Literal["audit"] = "audit"
    instance_name: str
    severity: Literal["info", "warning", "error"] = "info"
    category: str
    message: str
    metadata: Dict[str, str] = Field(default_factory=dict)

