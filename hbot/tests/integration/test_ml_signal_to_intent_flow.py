from services.contracts.event_schemas import ExecutionIntentEvent, MlSignalEvent, RiskDecisionEvent


def test_ml_signal_to_intent_chain_metadata():
    ml = MlSignalEvent(
        producer="signal_service",
        instance_name="bot1",
        controller_id="epp_v2_4",
        trading_pair="BTC-USDT",
        model_id="model-a",
        model_version="2026-02-19",
        runtime="sklearn_joblib",
        horizon_s=60,
        predicted_return=0.02,
        confidence=0.75,
        feature_hash="b" * 64,
        inference_latency_ms=35,
        signal_age_ms=100,
    )
    decision = RiskDecisionEvent(
        producer="risk_service",
        correlation_id=ml.event_id,
        instance_name=ml.instance_name,
        approved=True,
        reason="approved_ml",
        metadata={
            "signal_name": "ml_signal",
            "model_id": ml.model_id,
            "model_version": ml.model_version,
            "confidence": str(ml.confidence),
            "predicted_return": str(ml.predicted_return),
        },
    )
    intent = ExecutionIntentEvent(
        producer="coord_service",
        correlation_id=decision.event_id,
        instance_name=decision.instance_name,
        controller_id="epp_v2_4",
        action="set_target_base_pct",
        target_base_pct=0.65,
        metadata={"model_version": ml.model_version, "reason": decision.reason},
    )
    assert decision.correlation_id == ml.event_id
    assert intent.metadata["model_version"] == ml.model_version
    assert intent.action == "set_target_base_pct"

