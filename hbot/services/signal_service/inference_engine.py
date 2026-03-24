from __future__ import annotations

import logging
import time

from services.signal_service.model_loader import LoadedModel

logger = logging.getLogger(__name__)

REGIME_LABELS = ["neutral_low_vol", "neutral_high_vol", "up", "down", "high_vol_shock"]


def run_inference(loaded: LoadedModel, feature_vector: list[float], feature_map: dict[str, float]) -> tuple[float, float, int]:
    start_ms = int(time.time() * 1000)
    model = loaded.model
    predicted_return = 0.0
    confidence = 0.0

    if loaded.runtime == "sklearn_joblib":
        pred = model.predict([feature_vector])
        predicted_return = float(pred[0]) if len(pred) > 0 else 0.0
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba([feature_vector])[0]
            confidence = float(max(proba))
        elif hasattr(model, "decision_function"):
            decision = float(model.decision_function([feature_vector])[0])
            confidence = max(0.0, min(1.0, (abs(decision) / 5.0)))
        else:
            confidence = 0.0
            logger.warning("sklearn model has neither predict_proba nor decision_function — confidence forced to 0.0")
    elif loaded.runtime == "custom_python":
        # Custom model should accept dict-like or list-like features.
        if hasattr(model, "predict_with_confidence"):
            pred, conf = model.predict_with_confidence(feature_map)
            predicted_return = float(pred)
            confidence = float(conf)
        elif hasattr(model, "predict"):
            pred = model.predict(feature_map)
            predicted_return = float(pred)
            confidence = 0.0
        else:
            raise RuntimeError("custom_python model missing predict method")
    else:
        raise ValueError(f"Unsupported runtime={loaded.runtime}")

    latency_ms = int(time.time() * 1000) - start_ms
    confidence = max(0.0, min(1.0, confidence))
    return predicted_return, confidence, latency_ms


def predict_regime(
    loaded: LoadedModel,
    feature_vector: list[float],
    regime_labels: list[str] | None = None,
) -> tuple[str, float, int]:
    """Predict regime from a classifier model.

    Returns: (regime_str, confidence, latency_ms)

    For sklearn classifiers: uses predict_proba to get the top class and confidence.
    Falls back gracefully for non-classifier models.
    """
    labels = regime_labels or REGIME_LABELS
    start_ms = int(time.time() * 1000)
    regime_str = "neutral_low_vol"
    confidence = 0.0

    try:
        model = loaded.model
        if loaded.runtime == "sklearn_joblib":
            if hasattr(model, "predict_proba"):
                proba = model.predict_proba([feature_vector])[0]
                best_idx = int(max(range(len(proba)), key=lambda i: proba[i]))
                confidence = float(proba[best_idx])
                if hasattr(model, "classes_"):
                    cls = model.classes_[best_idx]
                    if isinstance(cls, (int, float)):
                        idx = int(cls)
                        regime_str = labels[idx] if 0 <= idx < len(labels) else "neutral_low_vol"
                    else:
                        regime_str = str(cls)
                elif best_idx < len(labels):
                    regime_str = labels[best_idx]
            elif hasattr(model, "predict"):
                pred = model.predict([feature_vector])[0]
                if isinstance(pred, (int, float)):
                    idx = int(pred)
                    regime_str = labels[idx] if 0 <= idx < len(labels) else "neutral_low_vol"
                else:
                    regime_str = str(pred)
                confidence = 0.5
        elif loaded.runtime == "custom_python":
            if hasattr(model, "predict_regime"):
                regime_str, confidence = model.predict_regime(feature_vector)
            elif hasattr(model, "predict"):
                pred = model.predict(feature_vector)
                regime_str = str(pred)
                confidence = 0.5
    except Exception:
        regime_str = "neutral_low_vol"
        confidence = 0.0

    latency_ms = int(time.time() * 1000) - start_ms
    return regime_str, max(0.0, min(1.0, confidence)), latency_ms


def is_classifier(loaded: LoadedModel) -> bool:
    """Return True if the loaded model is a multi-class classifier."""
    model = loaded.model
    if loaded.runtime == "sklearn_joblib":
        return hasattr(model, "predict_proba") and hasattr(model, "classes_")
    if loaded.runtime == "custom_python":
        return hasattr(model, "predict_regime")
    return False

