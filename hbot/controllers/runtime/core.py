from __future__ import annotations

from typing import Any

from controllers.runtime.contracts import RuntimeCompatibilitySurface


def sanitize_runtime_namespace(raw: Any, fallback: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return fallback
    text = text.replace("\\", "_").replace("/", "_").replace(" ", "_")
    while "__" in text:
        text = text.replace("__", "_")
    text = text.strip("_")
    return text or fallback


def default_artifact_namespace(config: Any) -> str:
    controller_name = str(getattr(config, "controller_name", "") or "").strip().lower()
    if controller_name.startswith("epp_"):
        return "epp_v24"
    return "runtime_v24"


def artifact_namespace(config: Any) -> str:
    default_ns = default_artifact_namespace(config)
    explicit = getattr(config, "artifact_namespace", "")
    return sanitize_runtime_namespace(explicit, default_ns)


def daily_state_store_prefix(config: Any) -> str:
    namespace = artifact_namespace(config)
    if namespace == "epp_v24":
        return "epp"
    return namespace


def telemetry_producer_prefix(config: Any) -> str:
    controller_name = str(getattr(config, "controller_name", "") or "").strip().lower()
    if controller_name.startswith("epp_"):
        return "hb.epp_v2_4"
    runtime_tag = sanitize_runtime_namespace(controller_name or "strategy_runtime_v24", "strategy_runtime_v24")
    return f"hb.{runtime_tag}"


def resolve_runtime_compatibility(config: Any, *, runtime_impl: str) -> RuntimeCompatibilitySurface:
    return RuntimeCompatibilitySurface(
        artifact_namespace=artifact_namespace(config),
        daily_state_prefix=daily_state_store_prefix(config),
        telemetry_producer_prefix=telemetry_producer_prefix(config),
        controller_contract_version="runtime_v24",
        runtime_impl=sanitize_runtime_namespace(runtime_impl, "shared_mm_v24"),
    )


def runtime_metadata(surface: RuntimeCompatibilitySurface) -> dict[str, str]:
    return {
        "controller_contract_version": surface.controller_contract_version,
        "runtime_impl": surface.runtime_impl,
    }


__all__ = [
    "RuntimeCompatibilitySurface",
    "artifact_namespace",
    "daily_state_store_prefix",
    "default_artifact_namespace",
    "resolve_runtime_compatibility",
    "runtime_metadata",
    "sanitize_runtime_namespace",
    "telemetry_producer_prefix",
]
