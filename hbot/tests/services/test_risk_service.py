from __future__ import annotations

from types import SimpleNamespace

from services.risk_service.main import evaluate_ml_signal


def _make_signal(**overrides):
    defaults = dict(
        confidence=0.80,
        signal_age_ms=500,
        predicted_return=0.01,
        regime="neutral_low_vol",
        model_version="v1",
        instance_name="bot1",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_approved_when_all_within_limits():
    approved, reason = evaluate_ml_signal(
        _make_signal(), confidence_min=0.60, max_signal_age_ms=3000, max_abs_predicted_return=0.05,
    )
    assert approved is True
    assert reason == "approved_ml"


def test_rejected_low_confidence():
    approved, reason = evaluate_ml_signal(
        _make_signal(confidence=0.40), confidence_min=0.60, max_signal_age_ms=3000, max_abs_predicted_return=0.05,
    )
    assert approved is False
    assert "ml_low_confidence" in reason


def test_rejected_stale_signal():
    approved, reason = evaluate_ml_signal(
        _make_signal(signal_age_ms=5000), confidence_min=0.60, max_signal_age_ms=3000, max_abs_predicted_return=0.05,
    )
    assert approved is False
    assert "ml_stale_signal" in reason


def test_rejected_outlier_return():
    approved, reason = evaluate_ml_signal(
        _make_signal(predicted_return=0.10), confidence_min=0.60, max_signal_age_ms=3000, max_abs_predicted_return=0.05,
    )
    assert approved is False
    assert "ml_predicted_return_outlier" in reason


def test_multiple_rejections():
    approved, reason = evaluate_ml_signal(
        _make_signal(confidence=0.10, signal_age_ms=9999, predicted_return=0.50),
        confidence_min=0.60, max_signal_age_ms=3000, max_abs_predicted_return=0.05,
    )
    assert approved is False
    assert "ml_low_confidence" in reason
    assert "ml_stale_signal" in reason
    assert "ml_predicted_return_outlier" in reason
