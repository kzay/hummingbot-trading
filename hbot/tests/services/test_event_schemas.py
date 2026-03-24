from platform_lib.contracts.event_schemas import (
    AuditEvent,
    ExecutionIntentEvent,
    MarketDepthSnapshotEvent,
    MarketQuoteEvent,
    MarketSnapshotEvent,
    MarketTradeEvent,
    MlSignalEvent,
    PaperExchangeCommandEvent,
    PaperExchangeEvent,
    PaperExchangeHeartbeatEvent,
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
        best_bid=99.9,
        best_ask=100.1,
        best_bid_size=2.5,
        best_ask_size=1.7,
        mark_price=100.05,
        exchange_ts_ms=1_234_567,
        ingest_ts_ms=1_234_568,
        market_sequence=42,
    )
    data = event.model_dump()
    restored = MarketSnapshotEvent(**data)
    assert restored.event_type == "market_snapshot"
    assert restored.trading_pair == "BTC-USDT"
    assert restored.best_bid == 99.9
    assert restored.best_ask == 100.1
    assert restored.best_bid_size == 2.5
    assert restored.best_ask_size == 1.7
    assert restored.market_sequence == 42


def test_market_depth_snapshot_schema_roundtrip():
    event = MarketDepthSnapshotEvent(
        producer="test",
        instance_name="bot1",
        controller_id="epp_v2_4",
        connector_name="bitget",
        trading_pair="BTC-USDT",
        depth_levels=3,
        bids=[
            {"price": 99.9, "size": 1.1},
            {"price": 99.8, "size": 2.2},
        ],
        asks=[
            {"price": 100.1, "size": 1.3},
            {"price": 100.2, "size": 2.4},
        ],
        best_bid=99.9,
        best_ask=100.1,
        exchange_ts_ms=1_234_567,
        ingest_ts_ms=1_234_568,
        market_sequence=77,
    )
    restored = MarketDepthSnapshotEvent(**event.model_dump())
    assert restored.event_type == "market_depth_snapshot"
    assert restored.depth_levels == 3
    assert len(restored.bids) == 2
    assert len(restored.asks) == 2
    assert restored.bids[0].price == 99.9
    assert restored.asks[0].size == 1.3
    assert restored.market_sequence == 77


def test_market_quote_schema_roundtrip():
    event = MarketQuoteEvent(
        producer="market_data_service",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        best_bid=99.9,
        best_ask=100.1,
        best_bid_size=1.2,
        best_ask_size=1.5,
        mid_price=100.0,
        last_trade_price=100.05,
        exchange_ts_ms=1_234_567,
        ingest_ts_ms=1_234_568,
        market_sequence=7,
        venue_symbol="BTCUSDT",
    )
    restored = MarketQuoteEvent(**event.model_dump())
    assert restored.event_type == "market_quote"
    assert restored.connector_name == "bitget_perpetual"
    assert restored.mid_price == 100.0
    assert restored.market_sequence == 7


def test_market_trade_schema_roundtrip():
    event = MarketTradeEvent(
        producer="market_data_service",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        trade_id="t-1",
        side="buy",
        price=100.25,
        size=0.4,
        exchange_ts_ms=1_234_569,
        ingest_ts_ms=1_234_570,
        market_sequence=8,
        venue_symbol="BTCUSDT",
    )
    restored = MarketTradeEvent(**event.model_dump())
    assert restored.event_type == "market_trade"
    assert restored.trade_id == "t-1"
    assert restored.price == 100.25


def test_execution_intent_schema_validation():
    event = ExecutionIntentEvent(
        producer="coord",
        instance_name="bot1",
        controller_id="epp_v2_4",
        action="resume",
    )
    assert event.event_type == "execution_intent"
    assert event.action == "resume"


def test_execution_intent_daily_target_action_validation():
    event = ExecutionIntentEvent(
        producer="portfolio_allocator_service",
        instance_name="bot1",
        controller_id="epp_v2_4",
        action="set_daily_pnl_target_pct",
        metadata={"daily_pnl_target_pct": "0.6"},
    )
    assert event.action == "set_daily_pnl_target_pct"
    assert event.metadata.get("daily_pnl_target_pct") == "0.6"


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


def test_paper_exchange_command_schema_roundtrip() -> None:
    event = PaperExchangeCommandEvent(
        producer="hb",
        instance_name="bot1",
        command="submit_order",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        side="buy",
        amount_base=0.01,
        price=10_000.0,
    )
    restored = PaperExchangeCommandEvent(**event.model_dump())
    assert restored.event_type == "paper_exchange_command"
    assert restored.command == "submit_order"


def test_paper_exchange_event_and_heartbeat_defaults() -> None:
    result = PaperExchangeEvent(
        producer="paper_exchange_service",
        instance_name="bot1",
        command_event_id="cmd-1",
        command="sync_state",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
    )
    heartbeat = PaperExchangeHeartbeatEvent(
        producer="paper_exchange_service",
        instance_name="paper_exchange",
    )
    assert result.status == "processed"
    assert heartbeat.service_name == "paper_exchange_service"

