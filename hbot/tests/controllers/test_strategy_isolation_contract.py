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
