from __future__ import annotations

from types import SimpleNamespace

from controllers.runtime.core import resolve_runtime_compatibility, runtime_metadata


def test_resolve_runtime_compatibility_preserves_legacy_epp_surface() -> None:
    surface = resolve_runtime_compatibility(
        SimpleNamespace(controller_name="epp_v2_4_bot7", artifact_namespace=""),
        runtime_impl="PullbackV1",
    )

    assert surface.artifact_namespace == "epp_v24"
    assert surface.daily_state_prefix == "epp"
    assert surface.telemetry_producer_prefix == "hb.epp_v2_4"
    assert runtime_metadata(surface) == {
        "controller_contract_version": "runtime_v24",
        "runtime_impl": "PullbackV1",
    }


def test_resolve_runtime_compatibility_uses_neutral_namespace_for_non_epp_controller() -> None:
    surface = resolve_runtime_compatibility(
        SimpleNamespace(controller_name="bot7_pullback_v1", artifact_namespace=""),
        runtime_impl="PullbackV1",
    )

    assert surface.artifact_namespace == "runtime_v24"
    assert surface.daily_state_prefix == "runtime_v24"
    assert surface.telemetry_producer_prefix == "hb.bot7_pullback_v1"
