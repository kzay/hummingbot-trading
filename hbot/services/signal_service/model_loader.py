from __future__ import annotations

import importlib
import os
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Optional, Tuple

try:
    import joblib  # type: ignore
except Exception:  # pragma: no cover
    joblib = None

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None


@dataclass
class LoadedModel:
    model: Any
    model_id: str
    model_version: str
    runtime: str
    source_uri: str
    loaded_at_ms: int


def _download_http_to_temp(uri: str, timeout_sec: int) -> str:
    if requests is None:
        raise RuntimeError("requests not installed")
    response = requests.get(uri, timeout=timeout_sec)
    response.raise_for_status()
    fd, path = tempfile.mkstemp(prefix="ml_model_", suffix=".bin")
    with os.fdopen(fd, "wb") as handle:
        handle.write(response.content)
    return path


def _download_s3_to_temp(uri: str, timeout_sec: int) -> str:
    # s3://bucket/key support is best-effort and requires boto3 + credentials.
    try:
        import boto3  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("boto3 not installed for s3:// model loading") from exc
    if not uri.startswith("s3://"):
        raise ValueError("S3 URI must start with s3://")
    no_prefix = uri[len("s3://") :]
    bucket, key = no_prefix.split("/", 1)
    fd, path = tempfile.mkstemp(prefix="ml_model_", suffix=".bin")
    os.close(fd)
    client = boto3.client("s3")
    client.download_file(bucket, key, path)
    return path


def _resolve_model_path(uri: str, timeout_sec: int) -> str:
    if uri.startswith("http://") or uri.startswith("https://"):
        return _download_http_to_temp(uri, timeout_sec)
    if uri.startswith("s3://"):
        return _download_s3_to_temp(uri, timeout_sec)
    return uri


def _load_custom_class(class_path: str) -> Any:
    if ":" not in class_path:
        raise ValueError("ML_CUSTOM_CLASS_PATH must be module.path:ClassName")
    module_path, class_name = class_path.split(":", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls()


def load_model(
    runtime: str,
    model_uri: str,
    custom_class_path: str = "",
    timeout_sec: int = 10,
) -> LoadedModel:
    runtime = runtime.strip().lower()
    source_path = _resolve_model_path(model_uri, timeout_sec)
    loaded_at_ms = int(time.time() * 1000)

    if runtime == "sklearn_joblib":
        if joblib is None:
            raise RuntimeError("joblib is not installed")
        model = joblib.load(source_path)
        model_version = str(getattr(model, "__class__", type(model)).__name__)
        return LoadedModel(
            model=model,
            model_id=os.path.basename(model_uri),
            model_version=model_version,
            runtime=runtime,
            source_uri=model_uri,
            loaded_at_ms=loaded_at_ms,
        )

    if runtime == "custom_python":
        model = _load_custom_class(custom_class_path)
        if hasattr(model, "load"):
            model.load(source_path)
        model_version = str(getattr(model, "version", getattr(model, "__class__", type(model)).__name__))
        return LoadedModel(
            model=model,
            model_id=os.path.basename(model_uri) or "custom_model",
            model_version=model_version,
            runtime=runtime,
            source_uri=model_uri,
            loaded_at_ms=loaded_at_ms,
        )

    raise ValueError(f"Unsupported runtime={runtime}")

