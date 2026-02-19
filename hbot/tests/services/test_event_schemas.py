from services.contracts.event_schemas import (
    AuditEvent,
    ExecutionIntentEvent,
    MarketSnapshotEvent,
    MlSignalEvent,
    RiskDecisionEvent,
    StrategySignalEvent,
)


def test_market_snapshot_schema_roundtrip():
    event = MarketSnapshotEvent(
        producer="test",
        instance_name="bot1",
        controller_id="epp_v2_4",
        connector_name="bitget",
        trading_pair="BTC-USDT",
        mid_price=100.0,
        equity_quote=10_000.0,
        base_pct=0.5,
        target_base_pct=0.5,
        spread_pct=0.003,
        net_edge_pct=0.0005,
        turnover_x=1.2,
        state="running",
    )
    data = event.model_dump()
    restored = MarketSnapshotEvent(**data)
    assert restored.event_type == "market_snapshot"
    assert restored.trading_pair == "BTC-USDT"


def test_execution_intent_schema_validation():
    event = ExecutionIntentEvent(
        producer="coord",
        instance_name="bot1",
        controller_id="epp_v2_4",
        action="resume",
    )
    assert event.event_type == "execution_intent"
    assert event.action == "resume"


def test_signal_and_risk_schema_compatibility():
    signal = StrategySignalEvent(
        producer="signal",
        instance_name="bot1",
        signal_name="inventory_rebalance",
        signal_value=0.15,
        confidence=0.7,
    )
    decision = RiskDecisionEvent(
        producer="risk",
        instance_name=signal.instance_name,
        correlation_id=signal.event_id,
        approved=True,
        reason="approved",
    )
    assert decision.correlation_id == signal.event_id


def test_audit_schema_defaults():
    event = AuditEvent(
        producer="hb",
        instance_name="bot1",
        category="intent_rejected",
        message="rejected by local authority",
    )
    assert event.severity == "info"


def test_ml_signal_schema_roundtrip():
    event = MlSignalEvent(
        producer="signal_service",
        instance_name="bot1",
        controller_id="epp_v2_4",
        trading_pair="BTC-USDT",
        model_id="model_a",
        model_version="2026-02-19",
        runtime="sklearn_joblib",
        horizon_s=60,
        predicted_return=0.02,
        confidence=0.8,
        feature_hash="f" * 64,
        inference_latency_ms=18,
        signal_age_ms=80,
    )
    restored = MlSignalEvent(**event.model_dump())
    assert restored.event_type == "ml_signal"
    assert restored.model_version == "2026-02-19"

