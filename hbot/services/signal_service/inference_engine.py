from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

from services.signal_service.model_loader import LoadedModel


def run_inference(loaded: LoadedModel, feature_vector: List[float], feature_map: Dict[str, float]) -> Tuple[float, float, int]:
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
            confidence = min(1.0, abs(predicted_return) * 100)
    elif loaded.runtime == "custom_python":
        # Custom model should accept dict-like or list-like features.
        if hasattr(model, "predict_with_confidence"):
            pred, conf = model.predict_with_confidence(feature_map)
            predicted_return = float(pred)
            confidence = float(conf)
        elif hasattr(model, "predict"):
            pred = model.predict(feature_map)
            predicted_return = float(pred)
            confidence = min(1.0, abs(predicted_return) * 100)
        else:
            raise RuntimeError("custom_python model missing predict method")
    else:
        raise ValueError(f"Unsupported runtime={loaded.runtime}")

    latency_ms = int(time.time() * 1000) - start_ms
    confidence = max(0.0, min(1.0, confidence))
    return predicted_return, confidence, latency_ms

