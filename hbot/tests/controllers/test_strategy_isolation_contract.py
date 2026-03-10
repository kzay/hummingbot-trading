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
        CONTROLLERS_DIR / "runtime" / "execution_context.py",
        CONTROLLERS_DIR / "runtime" / "logging.py",
        CONTROLLERS_DIR / "runtime" / "market_making_core.py",
        CONTROLLERS_DIR / "runtime" / "market_making_types.py",
        CONTROLLERS_DIR / "runtime" / "risk_context.py",
        CONTROLLERS_DIR / "epp_v2_4.py",
        CONTROLLERS_DIR / "price_buffer.py",
        CONTROLLERS_DIR / "regime_detector.py",
        CONTROLLERS_DIR / "spread_engine.py",
        CONTROLLERS_DIR / "tick_emitter.py",
        CONTROLLERS_DIR / "shared_mm_v24.py",
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


def test_legacy_wrappers_map_to_one_strategy_lane() -> None:
    expected = {
        "epp_v2_4_bot5.py": "controllers.bots.bot5.ift_jota_v1",
        "epp_v2_4_bot6.py": "controllers.bots.bot6.cvd_divergence_v1",
        "epp_v2_4_bot7.py": "controllers.bots.bot7.adaptive_grid_v1",
        "bot5_ift_jota_v1.py": "controllers.bots.bot5.ift_jota_v1",
        "bot6_cvd_divergence_v1.py": "controllers.bots.bot6.cvd_divergence_v1",
        "bot7_adaptive_grid_v1.py": "controllers.bots.bot7.adaptive_grid_v1",
    }
    for wrapper_rel_path, lane_module in expected.items():
        modules = _imported_modules(CONTROLLERS_DIR / wrapper_rel_path)
        lane_imports = sorted(m for m in modules if m.startswith("controllers.bots."))
        assert lane_imports == [lane_module], (
            f"{wrapper_rel_path} must point only to {lane_module}; got {lane_imports}"
        )
