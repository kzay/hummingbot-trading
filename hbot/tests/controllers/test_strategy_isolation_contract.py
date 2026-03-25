from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROLLERS_DIR = ROOT / "controllers"
BOTS_DIR = CONTROLLERS_DIR / "bots"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _module_name_for(path: Path) -> str:
    rel = path.relative_to(CONTROLLERS_DIR).with_suffix("")
    return "controllers." + ".".join(rel.parts)


def _bot_lane_files() -> list[Path]:
    return sorted(p for p in BOTS_DIR.rglob("*.py") if p.name != "__init__.py")


def test_shared_runtime_modules_do_not_import_strategy_lanes() -> None:
    shared_files = [
        CONTROLLERS_DIR / "runtime" / "__init__.py",
        CONTROLLERS_DIR / "runtime" / "base.py",
        CONTROLLERS_DIR / "runtime" / "contracts.py",
        CONTROLLERS_DIR / "runtime" / "core.py",
        CONTROLLERS_DIR / "runtime" / "data_context.py",
        CONTROLLERS_DIR / "runtime" / "directional_core.py",
        CONTROLLERS_DIR / "runtime" / "directional_config.py",
        CONTROLLERS_DIR / "runtime" / "directional_runtime.py",
        CONTROLLERS_DIR / "runtime" / "kernel.py",
        CONTROLLERS_DIR / "runtime" / "execution_context.py",
        CONTROLLERS_DIR / "runtime" / "logging.py",
        CONTROLLERS_DIR / "runtime" / "market_making_core.py",
        CONTROLLERS_DIR / "runtime" / "market_making_types.py",
        CONTROLLERS_DIR / "runtime" / "runtime_types.py",
        CONTROLLERS_DIR / "runtime" / "risk_context.py",
        CONTROLLERS_DIR / "epp_v2_4.py",
        CONTROLLERS_DIR / "price_buffer.py",
        CONTROLLERS_DIR / "regime_detector.py",
        CONTROLLERS_DIR / "spread_engine.py",
        CONTROLLERS_DIR / "tick_emitter.py",
        CONTROLLERS_DIR / "position_recovery.py",
        CONTROLLERS_DIR / "shared_runtime_v24.py",
    ]
    violations: list[str] = []
    for path in shared_files:
        modules = _imported_modules(path)
        bad = sorted(
            m
            for m in modules
            if m.startswith("controllers.bots.")
        )
        if bad:
            violations.append(f"{path.name}: {', '.join(bad)}")
    assert not violations, (
        "Shared/runtime modules must not import strategy lanes. "
        + "Violations -> "
        + "; ".join(violations)
    )


def test_bot_strategy_lanes_do_not_cross_import_each_other() -> None:
    lane_files = _bot_lane_files()
    lane_modules = {_module_name_for(p) for p in lane_files}
    violations: list[str] = []
    for path in lane_files:
        self_module = _module_name_for(path)
        modules = _imported_modules(path)
        cross_imports = sorted(m for m in modules if m in lane_modules and m != self_module)
        if cross_imports:
            violations.append(f"{path.name}: {', '.join(cross_imports)}")
    assert not violations, (
        "Strategy lanes must be isolated and must not import other lanes. "
        + "Violations -> "
        + "; ".join(violations)
    )


def test_directional_runtime_stubs_mm_methods() -> None:
    """DirectionalRuntimeController must override every MM-only method."""
    import ast as _ast

    mm_only_methods = {
        "_update_edge_gate_ewma",
        "_edge_gate_update",
        "_compute_pnl_governor_size_mult",
        "_increment_governor_reason_count",
        "_compute_selective_quote_quality",
        "_compute_alpha_policy",
        "_fill_edge_below_cost_floor",
        "_adverse_fill_soft_pause_active",
        "_edge_confidence_soft_pause_active",
        "_slippage_soft_pause_active",
        "_apply_spread_competitiveness_cap",
        "_update_adaptive_history",
        "_get_kelly_order_quote",
        "_auto_calibration_record_minute",
        "_auto_calibration_record_fill",
        "_auto_calibration_maybe_run",
        "_evaluate_all_risk",
    }
    dr_path = CONTROLLERS_DIR / "runtime" / "directional_runtime.py"
    tree = _ast.parse(dr_path.read_text(encoding="utf-8"))
    defined_methods: set[str] = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.ClassDef) and node.name == "DirectionalRuntimeController":
            for item in node.body:
                if isinstance(item, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    defined_methods.add(item.name)
    missing = mm_only_methods - defined_methods
    assert not missing, (
        "DirectionalRuntimeController must override all MM-only methods. "
        f"Missing: {sorted(missing)}"
    )


def test_directional_bot_lanes_extend_directional_runtime() -> None:
    """Directional bot lanes (bot5/6/7) must extend DirectionalStrategyRuntimeV24Controller."""
    directional_lanes = [
        BOTS_DIR / "bot5" / "ift_jota_v1.py",
        BOTS_DIR / "bot6" / "cvd_divergence_v1.py",
        BOTS_DIR / "bot7" / "pullback_v1.py",
    ]
    violations: list[str] = []
    for path in directional_lanes:
        src = path.read_text(encoding="utf-8")
        if "DirectionalStrategyRuntimeV24Controller" not in src:
            violations.append(
                f"{path.name}: must extend DirectionalStrategyRuntimeV24Controller "
                f"(uses StrategyRuntimeV24Controller instead)"
            )
        if "DirectionalStrategyRuntimeV24Config" not in src:
            violations.append(
                f"{path.name}: must extend DirectionalStrategyRuntimeV24Config "
                f"(uses StrategyRuntimeV24Config instead)"
            )
    assert not violations, (
        "Directional bot lanes must use the directional runtime base. "
        + "Violations -> " + "; ".join(violations)
    )


def test_directional_bot_lanes_do_not_disable_mm_flags_manually() -> None:
    """Directional bot lanes should not set MM disable flags — the base handles it."""
    directional_lanes = [
        BOTS_DIR / "bot5" / "ift_jota_v1.py",
        BOTS_DIR / "bot6" / "cvd_divergence_v1.py",
        BOTS_DIR / "bot7" / "pullback_v1.py",
    ]
    mm_disable_flags = [
        "shared_edge_gate_enabled",
        "alpha_policy_enabled",
        "selective_quoting_enabled",
        "adverse_fill_soft_pause_enabled",
        "edge_confidence_soft_pause_enabled",
        "slippage_soft_pause_enabled",
    ]
    violations: list[str] = []
    for path in directional_lanes:
        src = path.read_text(encoding="utf-8")
        for flag in mm_disable_flags:
            if f"{flag}" in src and "Field(default=False)" in src.split(flag)[-1].split("\n")[0]:
                violations.append(f"{path.name}: redundantly overrides {flag}")
    assert not violations, (
        "Directional lanes should not override MM disable flags — "
        "DirectionalRuntimeConfig handles them. Violations -> "
        + "; ".join(violations)
    )


def test_directional_runtime_extends_kernel_not_mm() -> None:
    """DirectionalRuntimeController must inherit SharedRuntimeKernel, NOT EppV24Controller."""
    dr_path = CONTROLLERS_DIR / "runtime" / "directional_runtime.py"
    tree = ast.parse(dr_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "DirectionalRuntimeController":
            bases = [
                (getattr(b, "attr", None) or getattr(b, "id", None))
                for b in node.bases
            ]
            assert "SharedRuntimeKernel" in bases, (
                f"DirectionalRuntimeController must extend SharedRuntimeKernel; "
                f"found bases: {bases}"
            )
            assert "EppV24Controller" not in bases, (
                "DirectionalRuntimeController must NOT extend EppV24Controller directly"
            )
            break
    else:
        raise AssertionError("DirectionalRuntimeController class not found")


def test_bot_lanes_do_not_directly_mutate_pending_stale_cancel_actions() -> None:
    """Bot lanes must use enqueue_stale_cancels/replace_stale_cancels, not direct list mutation."""
    lane_files = _bot_lane_files()
    violations: list[str] = []
    for path in lane_files:
        src = path.read_text(encoding="utf-8")
        for i, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if "_pending_stale_cancel_actions" in stripped and (
                ".extend(" in stripped or ".append(" in stripped or "= [" in stripped or "= self._cancel" in stripped
            ):
                violations.append(f"{path.name}:{i}: {stripped}")
    assert not violations, (
        "Bot lanes must NOT directly mutate _pending_stale_cancel_actions — "
        "use enqueue_stale_cancels() or replace_stale_cancels(). "
        + "Violations -> " + "; ".join(violations)
    )


def test_bot_lanes_do_not_directly_assign_recently_issued_levels() -> None:
    """Bot lanes must use _reset_issued_levels(), not direct assignment."""
    lane_files = _bot_lane_files()
    violations: list[str] = []
    for path in lane_files:
        src = path.read_text(encoding="utf-8")
        for i, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if "_recently_issued_levels" in stripped and "= {}" in stripped:
                violations.append(f"{path.name}:{i}: {stripped}")
    assert not violations, (
        "Bot lanes must NOT directly clear _recently_issued_levels — "
        "use _reset_issued_levels(). "
        + "Violations -> " + "; ".join(violations)
    )


def test_bot_lanes_do_not_override_executor_refresh_time() -> None:
    """Bot lanes must not write to _runtime_levels.executor_refresh_time."""
    lane_files = _bot_lane_files()
    violations: list[str] = []
    for path in lane_files:
        src = path.read_text(encoding="utf-8")
        for i, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if "executor_refresh_time" in stripped and "=" in stripped and not stripped.startswith("#"):
                if "==" not in stripped and "!=" not in stripped and "metadata" not in stripped:
                    violations.append(f"{path.name}:{i}: {stripped}")
    assert not violations, (
        "Bot lanes must NOT override _runtime_levels.executor_refresh_time — "
        "use open_order_timeout_s on config instead. "
        + "Violations -> " + "; ".join(violations)
    )


def test_shared_kernel_exposes_framework_boundary_methods() -> None:
    """SharedRuntimeKernel must expose encapsulated framework boundary methods."""
    kernel_path = CONTROLLERS_DIR / "runtime" / "kernel" / "controller.py"
    tree = ast.parse(kernel_path.read_text(encoding="utf-8"))
    required_methods = {
        "enqueue_stale_cancels",
        "replace_stale_cancels",
        "_reset_issued_levels",
        "_strategy_extra_actions",
    }
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SharedRuntimeKernel":
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name in required_methods:
                        found.add(item.name)
    missing = required_methods - found
    assert not missing, (
        "SharedRuntimeKernel must expose framework boundary methods. "
        f"Missing: {sorted(missing)}"
    )


def test_directional_config_has_open_order_timeout_field() -> None:
    """DirectionalRuntimeConfig must declare open_order_timeout_s."""
    dc_path = CONTROLLERS_DIR / "runtime" / "directional_config.py"
    src = dc_path.read_text(encoding="utf-8")
    assert "open_order_timeout_s" in src, (
        "DirectionalRuntimeConfig must declare open_order_timeout_s field"
    )


# ── v3 Trading Desk isolation contracts ──────────────────────────────


def test_v3_signal_modules_have_no_framework_imports() -> None:
    """Signal modules in v3/ SHALL NOT import from controllers.runtime,
    hummingbot, services, or simulation.  Only standard library, decimal,
    dataclasses, typing, and the v3 type modules are allowed."""
    v3_dir = CONTROLLERS_DIR / "runtime" / "v3"
    forbidden_prefixes = (
        "controllers.runtime.kernel",
        "controllers.runtime.base",
        "controllers.runtime.core",
        "controllers.runtime.contracts",
        "controllers.epp",
        "controllers.shared_runtime",
        "hummingbot",
        "services.",
        "simulation.",
    )
    # Only check signal-related files (not the framework itself)
    # Infrastructure files that legitimately import from hummingbot/services
    infra_files = {
        "__init__.py", "data_surface.py", "migration_shim.py",
        "trading_desk.py", "telemetry.py", "desk_integration.py",
        "order_submitter.py",
    }
    signal_files = [
        p for p in v3_dir.rglob("*.py")
        if p.name not in infra_files
        and "risk" not in str(p.relative_to(v3_dir))
        and "execution" not in str(p.relative_to(v3_dir))
    ]
    violations: list[str] = []
    for path in signal_files:
        if not path.exists():
            continue
        modules = _imported_modules(path)
        bad = sorted(
            m for m in modules
            if any(m.startswith(p) for p in forbidden_prefixes)
        )
        if bad:
            violations.append(f"{path.name}: {', '.join(bad)}")
    assert not violations, (
        "v3 signal/type modules must not import framework internals. "
        + "Violations -> " + "; ".join(violations)
    )


def test_v3_types_are_frozen_dataclasses() -> None:
    """All v3 snapshot and signal types must be frozen dataclasses."""
    import dataclasses
    from controllers.runtime.v3.types import (
        EquitySnapshot, FundingSnapshot, IndicatorSnapshot,
        MarketSnapshot, MlSnapshot, OrderBookSnapshot,
        PositionSnapshot, RegimeSnapshot, TradeFlowSnapshot,
    )
    from controllers.runtime.v3.signals import (
        SignalLevel, TelemetryField, TelemetrySchema, TradingSignal,
    )
    from controllers.runtime.v3.orders import (
        DeskOrder, SubmitOrder, CancelOrder, ModifyOrder,
        ClosePosition, PartialReduce,
    )
    from controllers.runtime.v3.risk_types import RiskDecision

    for cls in [
        EquitySnapshot, FundingSnapshot, IndicatorSnapshot,
        MarketSnapshot, MlSnapshot, OrderBookSnapshot,
        PositionSnapshot, RegimeSnapshot, TradeFlowSnapshot,
        SignalLevel, TelemetryField, TelemetrySchema, TradingSignal,
        DeskOrder, SubmitOrder, CancelOrder, ModifyOrder,
        ClosePosition, PartialReduce, RiskDecision,
    ]:
        assert dataclasses.is_dataclass(cls), f"{cls.__name__} is not a dataclass"
        assert cls.__dataclass_params__.frozen, f"{cls.__name__} is not frozen"


def test_v3_protocols_are_runtime_checkable() -> None:
    """All v3 protocols must be runtime_checkable."""
    from controllers.runtime.v3.protocols import (
        ExecutionAdapter, RiskLayer, StrategySignalSource, TradingDeskProtocol,
    )
    for proto in [ExecutionAdapter, RiskLayer, StrategySignalSource, TradingDeskProtocol]:
        # runtime_checkable protocols have _is_runtime_protocol attribute
        assert getattr(proto, "_is_runtime_protocol", False), (
            f"{proto.__name__} must be @runtime_checkable"
        )


def test_v3_strategy_registry_entries_are_valid() -> None:
    """All registered strategies must have valid module_path and signal_class."""
    from controllers.runtime.v3.strategy_registry import STRATEGY_REGISTRY
    for name, entry in STRATEGY_REGISTRY.items():
        assert entry.module_path, f"{name}: empty module_path"
        assert entry.signal_class, f"{name}: empty signal_class"
        assert entry.execution_family in ("mm_grid", "directional", "hybrid"), (
            f"{name}: invalid execution_family '{entry.execution_family}'"
        )


def test_legacy_wrappers_map_to_one_strategy_lane() -> None:
    expected = {
        "epp_v2_4_bot5.py": "controllers.bots.bot5.ift_jota_v1",
        "epp_v2_4_bot6.py": "controllers.bots.bot6.cvd_divergence_v1",
        "epp_v2_4_bot7.py": "controllers.bots.bot7.pullback_v1",
        "bot5_ift_jota_v1.py": "controllers.bots.bot5.ift_jota_v1",
        "bot6_cvd_divergence_v1.py": "controllers.bots.bot6.cvd_divergence_v1",
        "bot7_pullback_v1.py": "controllers.bots.bot7.pullback_v1",
    }
    for wrapper_rel_path, lane_module in expected.items():
        modules = _imported_modules(CONTROLLERS_DIR / wrapper_rel_path)
        lane_imports = sorted(m for m in modules if m.startswith("controllers.bots."))
        assert lane_imports == [lane_module], (
            f"{wrapper_rel_path} must point only to {lane_module}; got {lane_imports}"
        )
