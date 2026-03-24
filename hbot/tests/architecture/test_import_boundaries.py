"""Architectural import boundary enforcement.

Rules enforced:
1. platform_lib/ must NOT import from controllers, services, or simulation
2. simulation/ must NOT import from controllers or services
   (exception: simulation.bridge/ may import services.execution_gateway)
3. controllers/ must NOT import from services
   (exception: controllers/paper_engine_v2/__init__.py is a re-export shim)
4. No cross-service imports (one service importing another's internals)
"""

import ast
import os
from pathlib import Path

import pytest

HBOT_ROOT = Path(__file__).resolve().parent.parent.parent


def _scan_imports(
    root_dir: Path, *, top_level_only: bool = False
) -> list[tuple[str, int, str]]:
    """Return (filepath, lineno, module) for imports in root_dir.

    If top_level_only=True, skip imports inside functions/methods and
    TYPE_CHECKING blocks — only catch module-level unconditional imports.
    """
    results = []
    for dirpath, _, filenames in os.walk(root_dir):
        if "__pycache__" in dirpath:
            continue
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            fpath = os.path.join(dirpath, fn)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    tree = ast.parse(f.read(), filename=fpath)
            except SyntaxError:
                continue

            if top_level_only:
                for node in ast.iter_child_nodes(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        results.append((fpath, node.lineno, node.module))
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name:
                                results.append((fpath, node.lineno, alias.name))
                    elif isinstance(node, ast.If):
                        # Skip TYPE_CHECKING blocks
                        test = node.test
                        if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                            continue
                        for sub in ast.walk(node):
                            if isinstance(sub, ast.ImportFrom) and sub.module:
                                results.append((fpath, sub.lineno, sub.module))
                            elif isinstance(sub, ast.Import):
                                for alias in sub.names:
                                    if alias.name:
                                        results.append((fpath, sub.lineno, alias.name))
            else:
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        results.append((fpath, node.lineno, node.module))
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name:
                                results.append((fpath, node.lineno, alias.name))
    return results


class TestPlatformLibBoundaries:
    """platform_lib/ must not depend on controllers, services, or simulation."""

    FORBIDDEN = ("controllers.", "services.", "simulation.")

    def test_no_forbidden_imports(self):
        violations = []
        for fpath, lineno, module in _scan_imports(
            HBOT_ROOT / "platform_lib", top_level_only=True
        ):
            if any(module.startswith(prefix) for prefix in self.FORBIDDEN):
                violations.append(f"  {fpath}:{lineno} imports {module}")
        assert not violations, (
            f"platform_lib/ has {len(violations)} forbidden imports:\n"
            + "\n".join(violations)
        )


class TestSimulationBoundaries:
    """simulation/ must not import controllers or services (except bridge -> execution_gateway)."""

    def test_no_controller_imports(self):
        violations = []
        for fpath, lineno, module in _scan_imports(HBOT_ROOT / "simulation"):
            if module.startswith("controllers."):
                violations.append(f"  {fpath}:{lineno} imports {module}")
        assert not violations, (
            f"simulation/ has {len(violations)} controller imports:\n"
            + "\n".join(violations)
        )

    def test_no_service_imports_except_execution_gateway(self):
        violations = []
        for fpath, lineno, module in _scan_imports(HBOT_ROOT / "simulation"):
            if module.startswith("services."):
                rel = os.path.relpath(fpath, HBOT_ROOT)
                is_bridge = "bridge" in rel
                is_exec_gw = "execution_gateway" in module
                if not (is_bridge and is_exec_gw):
                    violations.append(f"  {fpath}:{lineno} imports {module}")
        assert not violations, (
            f"simulation/ has {len(violations)} forbidden service imports:\n"
            + "\n".join(violations)
        )


class TestControllerBoundaries:
    """controllers/ must not import services (except via shims)."""

    SHIM_DIRS = {"paper_engine_v2"}

    def test_no_service_imports(self):
        violations = []
        for fpath, lineno, module in _scan_imports(HBOT_ROOT / "controllers"):
            if not module.startswith("services."):
                continue
            rel = os.path.relpath(fpath, HBOT_ROOT / "controllers")
            top_dir = rel.split(os.sep)[0]
            if top_dir in self.SHIM_DIRS:
                continue
            violations.append(f"  {fpath}:{lineno} imports {module}")
        assert not violations, (
            f"controllers/ has {len(violations)} service imports:\n"
            + "\n".join(violations)
        )


class TestCrossServiceBoundaries:
    """No cross-service imports — each service must be independent.

    Shared infrastructure packages (hb_bridge for Redis, bot_metrics_exporter
    and control_plane_metrics_exporter for Prometheus, monitoring for re-exports)
    are allowed as cross-service dependencies since they provide common infra.
    """

    SERVICE_DIR = HBOT_ROOT / "services"
    SHARED = {
        "common", "contracts", "__pycache__",
        "hb_bridge",                          # shared Redis client provider
        "bot_metrics_exporter",               # shared Prometheus metrics
        "bot_metrics_exporter_pkg",           # package variant
        "control_plane_metrics_exporter",     # shared control-plane metrics
    }

    def test_no_cross_service_imports(self):
        violations = []
        if not self.SERVICE_DIR.exists():
            return
        service_dirs = {
            d.name
            for d in self.SERVICE_DIR.iterdir()
            if d.is_dir() and d.name not in self.SHARED
        }
        for svc_name in sorted(service_dirs):
            svc_dir = self.SERVICE_DIR / svc_name
            for fpath, lineno, module in _scan_imports(svc_dir):
                if not module.startswith("services."):
                    continue
                parts = module.split(".")
                if len(parts) < 2:
                    continue
                target_svc = parts[1]
                if target_svc == svc_name:
                    continue
                if target_svc in self.SHARED:
                    continue
                rel = os.path.relpath(fpath, HBOT_ROOT)
                violations.append(
                    f"  {rel}:{lineno}  services.{svc_name} imports services.{target_svc} ({module})"
                )
        assert not violations, (
            f"Cross-service imports detected ({len(violations)}):\n"
            + "\n".join(violations)
            + "\nEach service must only import from services.common or services.contracts."
        )


class TestNoPrintInProduction:
    """No print() calls in production code (controllers, services, simulation, platform_lib)."""

    _CLI_DIRS = {"research", "backtesting", "ml"}

    def test_no_bare_prints(self):
        count = 0
        for pkg in ("controllers", "services", "simulation", "platform_lib"):
            pkg_dir = HBOT_ROOT / pkg
            if not pkg_dir.exists():
                continue
            for dirpath, _, filenames in os.walk(pkg_dir):
                if "__pycache__" in dirpath:
                    continue
                rel = os.path.relpath(dirpath, pkg_dir)
                if rel.split(os.sep)[0] in self._CLI_DIRS:
                    continue
                for fn in filenames:
                    if not fn.endswith(".py"):
                        continue
                    fpath = os.path.join(dirpath, fn)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                            tree = ast.parse(f.read(), filename=fpath)
                    except SyntaxError:
                        continue
                    for node in ast.walk(tree):
                        if (
                            isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Name)
                            and node.func.id == "print"
                        ):
                            count += 1
        assert count == 0, (
            f"print() count {count} in production code (excludes CLI dirs: {self._CLI_DIRS}). "
            f"Replace prints with logger calls."
        )
