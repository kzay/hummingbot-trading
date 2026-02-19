from services.contracts.event_schemas import MlSignalEvent
from services.risk_service.main import evaluate_ml_signal


def _signal(conf: float, age_ms: int, pred: float) -> MlSignalEvent:
    return MlSignalEvent(
        producer="signal",
        instance_name="bot1",
        controller_id="epp_v2_4",
        trading_pair="BTC-USDT",
        model_id="m1",
        model_version="v1",
        runtime="sklearn_joblib",
        horizon_s=60,
        predicted_return=pred,
        confidence=conf,
        feature_hash="a" * 64,
        inference_latency_ms=10,
        signal_age_ms=age_ms,
    )


def test_ml_signal_approved_when_within_limits():
    approved, reason = evaluate_ml_signal(_signal(conf=0.8, age_ms=100, pred=0.01), 0.6, 3000, 0.05)
    assert approved is True
    assert reason == "approved_ml"


def test_ml_signal_rejected_for_low_confidence():
    approved, reason = evaluate_ml_signal(_signal(conf=0.4, age_ms=100, pred=0.01), 0.6, 3000, 0.05)
    assert approved is False
    assert "ml_low_confidence" in reason


def test_ml_signal_rejected_for_stale_age():
    approved, reason = evaluate_ml_signal(_signal(conf=0.8, age_ms=5000, pred=0.01), 0.6, 3000, 0.05)
    assert approved is False
    assert "ml_stale_signal" in reason

