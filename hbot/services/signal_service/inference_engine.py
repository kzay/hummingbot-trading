from __future__ import annotations

import logging
import time

from services.signal_service.model_loader import LoadedModel

logger = logging.getLogger(__name__)

VOL_REGIME_LABELS = ["vol_low", "vol_normal", "vol_elevated", "vol_extreme"]

REGIME_LABELS = ["neutral_low_vol", "neutral_high_vol", "up", "down", "high_vol_shock"]

_COMPOSITE_REGIME_MAP: dict[tuple[str, str], str] = {
    ("vol_low", "up"): "up", ("vol_low", "down"): "down",
    ("vol_low", "neutral"): "neutral_low_vol", ("vol_low", ""): "neutral_low_vol",
    ("vol_normal", "up"): "up", ("vol_normal", "down"): "down",
    ("vol_normal", "neutral"): "neutral_low_vol", ("vol_normal", ""): "neutral_low_vol",
    ("vol_elevated", "up"): "neutral_high_vol", ("vol_elevated", "down"): "neutral_high_vol",
    ("vol_elevated", "neutral"): "neutral_high_vol", ("vol_elevated", ""): "neutral_high_vol",
    ("vol_extreme", "up"): "high_vol_shock", ("vol_extreme", "down"): "high_vol_shock",
    ("vol_extreme", "neutral"): "high_vol_shock", ("vol_extreme", ""): "high_vol_shock",
}


def resolve_composite_regime(vol_label: str, direction_hint: str = "") -> str:
    """Map (vol_prediction, direction_hint) -> operating regime name."""
    return _COMPOSITE_REGIME_MAP.get((vol_label, direction_hint or ""), "neutral_low_vol")


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
    direction_hint: str = "",
) -> tuple[str, float, int]:
    """Predict regime from a classifier model.

    Returns ``(regime_str, confidence, latency_ms)``.
    Uses VOL_REGIME_LABELS by default, then composes with direction_hint
    via resolve_composite_regime() to produce an operating regime name.
    """
    labels = regime_labels or VOL_REGIME_LABELS
    start_ms = int(time.time() * 1000)
    vol_label = "vol_low"
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
                        vol_label = labels[idx] if 0 <= idx < len(labels) else "vol_low"
                    else:
                        vol_label = str(cls)
                elif best_idx < len(labels):
                    vol_label = labels[best_idx]
            elif hasattr(model, "predict"):
                pred = model.predict([feature_vector])[0]
                if isinstance(pred, (int, float)):
                    idx = int(pred)
                    vol_label = labels[idx] if 0 <= idx < len(labels) else "vol_low"
                else:
                    vol_label = str(pred)
                confidence = 0.5
        elif loaded.runtime == "custom_python":
            if hasattr(model, "predict_regime"):
                vol_label, confidence = model.predict_regime(feature_vector)
            elif hasattr(model, "predict"):
                pred = model.predict(feature_vector)
                vol_label = str(pred)
                confidence = 0.5
    except Exception:
        vol_label = "vol_low"
        confidence = 0.0

    regime_str = resolve_composite_regime(vol_label, direction_hint)
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

