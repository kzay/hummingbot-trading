from services.contracts.event_schemas import (
    ExecutionIntentEvent,
    MarketSnapshotEvent,
    RiskDecisionEvent,
    StrategySignalEvent,
)


def test_signal_risk_intent_logical_flow():
    market = MarketSnapshotEvent(
        producer="hb",
        instance_name="bot1",
        controller_id="epp_v2_4",
        connector_name="bitget",
        trading_pair="BTC-USDT",
        mid_price=100.0,
        equity_quote=10000.0,
        base_pct=0.30,
        target_base_pct=0.50,
        spread_pct=0.003,
        net_edge_pct=0.0004,
        turnover_x=1.0,
        state="running",
    )

    signal = StrategySignalEvent(
        producer="signal_service",
        instance_name=market.instance_name,
        correlation_id=market.event_id,
        signal_name="inventory_rebalance",
        signal_value=market.target_base_pct - market.base_pct,
        confidence=0.8,
    )

    decision = RiskDecisionEvent(
        producer="risk_service",
        instance_name=signal.instance_name,
        correlation_id=signal.event_id,
        approved=True,
        reason="approved",
        max_notional_quote=1000.0,
    )

    intent = ExecutionIntentEvent(
        producer="coordination_service",
        instance_name=decision.instance_name,
        correlation_id=decision.event_id,
        controller_id="epp_v2_4",
        action="resume",
    )

    assert signal.correlation_id == market.event_id
    assert decision.correlation_id == signal.event_id
    assert intent.correlation_id == decision.event_id
    assert decision.approved is True

