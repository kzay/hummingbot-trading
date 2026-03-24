"""Model registry for ML artifacts keyed by (exchange, pair, model_type).

Directory structure::

    {base_dir}/{exchange}/{pair}/{model_type}_v1.joblib
    {base_dir}/{exchange}/{pair}/{model_type}_v1_metadata.json
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def model_dir(base_dir: str | Path, exchange: str, pair: str) -> Path:
    """Return the model directory for an (exchange, pair)."""
    return Path(base_dir) / exchange / pair


def model_path(
    base_dir: str | Path, exchange: str, pair: str, model_type: str,
) -> Path:
    """Return the path to the model joblib file."""
    return model_dir(base_dir, exchange, pair) / f"{model_type}_v1.joblib"


def metadata_path(
    base_dir: str | Path, exchange: str, pair: str, model_type: str,
) -> Path:
    """Return the path to the model metadata JSON file."""
    return model_dir(base_dir, exchange, pair) / f"{model_type}_v1_metadata.json"


def save_model(
    model: Any,
    metadata: dict[str, Any],
    base_dir: str | Path,
    exchange: str,
    pair: str,
    model_type: str,
) -> Path:
    """Save a model and its metadata to the registry.

    Returns the path to the saved model file.
    """
    import joblib

    out_dir = model_dir(base_dir, exchange, pair)
    out_dir.mkdir(parents=True, exist_ok=True)

    m_path = model_path(base_dir, exchange, pair, model_type)
    joblib.dump(model, m_path)

    meta_path = metadata_path(base_dir, exchange, pair, model_type)
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    logger.info("Saved model %s/%s/%s → %s", exchange, pair, model_type, m_path)
    return m_path


def load_model(
    base_dir: str | Path, exchange: str, pair: str, model_type: str,
) -> Any:
    """Load a model from the registry. Raises FileNotFoundError if absent."""
    import joblib

    m_path = model_path(base_dir, exchange, pair, model_type)
    if not m_path.exists():
        raise FileNotFoundError(f"Model not found: {m_path}")
    return joblib.load(m_path)


def load_metadata(
    base_dir: str | Path, exchange: str, pair: str, model_type: str,
) -> dict[str, Any] | None:
    """Load model metadata. Returns None if the file doesn't exist."""
    meta_path = metadata_path(base_dir, exchange, pair, model_type)
    if not meta_path.exists():
        return None
    with open(meta_path) as f:
        return json.load(f)
