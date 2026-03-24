from __future__ import annotations

import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


def now_ms() -> int:
    return int(time.time() * 1000)


class EventEnvelope(BaseModel):
    schema_version: str = Field(default=SCHEMA_VERSION)
    event_type: str
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str | None = None
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
    # Exchange-like L1 extensions (backward compatible as optional fields).
    best_bid: float | None = None
    best_ask: float | None = None
    best_bid_size: float | None = None
    best_ask_size: float | None = None
    last_trade_price: float | None = None
    mark_price: float | None = None
    funding_rate: float | None = None
    exchange_ts_ms: int | None = None
    ingest_ts_ms: int | None = None
    market_sequence: int | None = None
    extra: dict[str, str] = Field(default_factory=dict)


class MarketQuoteEvent(EventEnvelope):
    event_type: Literal["market_quote"] = "market_quote"
    connector_name: str
    trading_pair: str
    best_bid: float
    best_ask: float
    best_bid_size: float | None = None
    best_ask_size: float | None = None
    mid_price: float | None = None
    last_trade_price: float | None = None
    mark_price: float | None = None
    funding_rate: float | None = None
    exchange_ts_ms: int | None = None
    ingest_ts_ms: int | None = None
    market_sequence: int | None = None
    venue_symbol: str | None = None
    extra: dict[str, str] = Field(default_factory=dict)


class MarketTradeEvent(EventEnvelope):
    event_type: Literal["market_trade"] = "market_trade"
    connector_name: str
    trading_pair: str
    trade_id: str | None = None
    side: Literal["buy", "sell"] | None = None
    price: float
    size: float
    exchange_ts_ms: int | None = None
    ingest_ts_ms: int | None = None
    market_sequence: int | None = None
    venue_symbol: str | None = None
    extra: dict[str, str] = Field(default_factory=dict)


class MarketDepthLevel(BaseModel):
    price: float
    size: float


class MarketDepthSnapshotEvent(EventEnvelope):
    event_type: Literal["market_depth_snapshot"] = "market_depth_snapshot"
    instance_name: str
    controller_id: str
    connector_name: str
    trading_pair: str
    depth_levels: int = 20
    bids: list[MarketDepthLevel] = Field(default_factory=list)
    asks: list[MarketDepthLevel] = Field(default_factory=list)
    best_bid: float | None = None
    best_ask: float | None = None
    last_trade_price: float | None = None
    mark_price: float | None = None
    funding_rate: float | None = None
    exchange_ts_ms: int | None = None
    ingest_ts_ms: int | None = None
    market_sequence: int | None = None
    extra: dict[str, str] = Field(default_factory=dict)


class MarketDepthDeltaEvent(EventEnvelope):
    event_type: Literal["market_depth_delta"] = "market_depth_delta"
    instance_name: str
    controller_id: str
    connector_name: str
    trading_pair: str
    depth_levels: int = 20
    sequence_start: int | None = None
    sequence_end: int | None = None
    bids: list[MarketDepthLevel] = Field(default_factory=list)
    asks: list[MarketDepthLevel] = Field(default_factory=list)
    exchange_ts_ms: int | None = None
    ingest_ts_ms: int | None = None
    extra: dict[str, str] = Field(default_factory=dict)


class StrategySignalEvent(EventEnvelope):
    event_type: Literal["strategy_signal"] = "strategy_signal"
    instance_name: str
    signal_name: str
    signal_value: float
    confidence: float = 0.0
    metadata: dict[str, str] = Field(default_factory=dict)


class MlFeatureEvent(EventEnvelope):
    """ML features and predictions published per pair per bar by ml-feature-service."""
    event_type: Literal["ml_features"] = "ml_features"
    exchange: str
    trading_pair: str
    features: dict[str, float] = Field(default_factory=dict)
    predictions: dict[str, dict] = Field(default_factory=dict)
    model_versions: dict[str, str] = Field(default_factory=dict)


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
    metadata: dict[str, str] = Field(default_factory=dict)


class RiskDecisionEvent(EventEnvelope):
    event_type: Literal["risk_decision"] = "risk_decision"
    instance_name: str
    approved: bool
    reason: str
    max_notional_quote: float | None = None
    min_spread_pct: float | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class ExecutionIntentEvent(EventEnvelope):
    event_type: Literal["execution_intent"] = "execution_intent"
    instance_name: str
    controller_id: str
    action: Literal["set_target_base_pct", "set_daily_pnl_target_pct", "soft_pause", "resume", "kill_switch"]
    target_base_pct: float | None = None
    expires_at_ms: int | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class AuditEvent(EventEnvelope):
    event_type: Literal["audit"] = "audit"
    instance_name: str
    severity: Literal["info", "warning", "error"] = "info"
    category: str
    message: str
    metadata: dict[str, str] = Field(default_factory=dict)


class BotMinuteSnapshotEvent(EventEnvelope):
    """Per-minute controller telemetry snapshot, published to Redis alongside CSV."""
    event_type: Literal["bot_minute_snapshot"] = "bot_minute_snapshot"
    instance_name: str
    controller_id: str
    connector_name: str
    trading_pair: str
    state: str
    regime: str
    mid_price: float
    equity_quote: float
    base_pct: float
    target_base_pct: float
    spread_pct: float
    net_edge_pct: float
    turnover_x: float
    daily_loss_pct: float
    drawdown_pct: float
    fills_count_today: int
    fees_paid_today_quote: float
    fee_source: str
    maker_fee_pct: float
    taker_fee_pct: float
    risk_reasons: str
    metadata: dict[str, str] = Field(default_factory=dict)


class BotFillEvent(EventEnvelope):
    """Individual fill event published to BOT_TELEMETRY_STREAM.

    Emitted by both paper (accounting_source='paper_desk_v2') and live
    (accounting_source='live_connector') paths so the event_store ingests
    fills symmetrically regardless of mode.  Consumers can filter by
    accounting_source to separate simulated from real fills.
    """
    event_type: Literal["bot_fill"] = "bot_fill"
    instance_name: str
    controller_id: str
    connector_name: str
    trading_pair: str
    side: str
    price: float
    amount_base: float
    notional_quote: float
    fee_quote: float
    order_id: str
    accounting_source: str = "live_connector"   # "paper_desk_v2" | "live_connector"
    is_maker: bool = False
    realized_pnl_quote: float = 0.0
    bot_state: str = ""                          # ops guard state at fill time
    metadata: dict[str, str] = Field(default_factory=dict)


class PaperExchangeCommandEvent(EventEnvelope):
    """Command emitted toward paper-exchange service."""

    event_type: Literal["paper_exchange_command"] = "paper_exchange_command"
    instance_name: str
    command: Literal["submit_order", "cancel_order", "cancel_all", "sync_state"]
    connector_name: str
    trading_pair: str
    order_id: str | None = None
    side: Literal["buy", "sell"] | None = None
    order_type: str | None = None
    amount_base: float | None = None
    price: float | None = None
    expires_at_ms: int | None = None
    reduce_only: bool = False
    position_action: str | None = None
    position_mode: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class PaperExchangeEvent(EventEnvelope):
    """Result emitted by paper-exchange service for command lifecycle."""

    event_type: Literal["paper_exchange_event"] = "paper_exchange_event"
    instance_name: str
    command_event_id: str
    command: str
    status: Literal["processed", "rejected"] = "processed"
    reason: str = ""
    connector_name: str
    trading_pair: str
    order_id: str | None = None
    position_action: str | None = None
    position_mode: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class PaperExchangeHeartbeatEvent(EventEnvelope):
    """Health heartbeat for exchange-mirroring readiness and data freshness."""

    event_type: Literal["paper_exchange_heartbeat"] = "paper_exchange_heartbeat"
    instance_name: str
    service_name: str = "paper_exchange_service"
    status: Literal["ok", "degraded"] = "ok"
    market_pairs_total: int = 0
    stale_pairs: int = 0
    newest_snapshot_age_ms: int = 0
    oldest_snapshot_age_ms: int = 0
    metadata: dict[str, str] = Field(default_factory=dict)

