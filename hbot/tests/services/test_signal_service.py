from __future__ import annotations

from unittest.mock import MagicMock

from services.signal_service.inference_engine import (
    REGIME_LABELS,
    is_classifier,
    predict_regime,
    run_inference,
)
from services.signal_service.model_loader import LoadedModel


def _make_loaded(runtime="sklearn_joblib", **model_attrs):
    model = MagicMock()
    for k, v in model_attrs.items():
        setattr(model, k, v)
    return LoadedModel(
        model=model,
        model_id="test",
        model_version="v1",
        runtime=runtime,
        source_uri="file://test",
        loaded_at_ms=0,
    )


def test_run_inference_sklearn():
    loaded = _make_loaded()
    loaded.model.predict.return_value = [0.02]
    loaded.model.predict_proba.return_value = [[0.3, 0.7]]
    pred, conf, latency = run_inference(loaded, [1.0, 2.0], {"a": 1.0})
    assert pred == 0.02
    assert conf == 0.7


def test_run_inference_custom_python():
    loaded = _make_loaded(runtime="custom_python")
    loaded.model.predict_with_confidence.return_value = (0.01, 0.85)
    pred, conf, latency = run_inference(loaded, [1.0], {"a": 1.0})
    assert pred == 0.01
    assert conf == 0.85


def test_predict_regime_with_proba():
    loaded = _make_loaded()
    loaded.model.predict_proba.return_value = [[0.1, 0.6, 0.1, 0.1, 0.1]]
    loaded.model.classes_ = [0, 1, 2, 3, 4]
    regime, conf, latency = predict_regime(loaded, [1.0, 2.0])
    assert regime == REGIME_LABELS[1]
    assert conf == 0.6


def test_is_classifier_sklearn():
    loaded = _make_loaded()
    loaded.model.predict_proba = MagicMock()
    loaded.model.classes_ = [0, 1]
    assert is_classifier(loaded) is True


def test_is_classifier_no_proba():
    loaded = _make_loaded()
    del loaded.model.predict_proba
    del loaded.model.classes_
    assert is_classifier(loaded) is False
