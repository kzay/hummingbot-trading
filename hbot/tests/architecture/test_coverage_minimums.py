"""Architecture test enforcing minimum test counts per critical module.

Ensures test coverage doesn't regress — each critical module must have
at least the specified number of test cases.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent.parent


def _count_test_functions(test_dir: Path) -> int:
    """Count all test_* functions and methods in a directory tree."""
    count = 0
    if not test_dir.exists():
        return 0
    for dirpath, _, filenames in os.walk(test_dir):
        if "__pycache__" in dirpath:
            continue
        for fn in filenames:
            if not fn.startswith("test_") or not fn.endswith(".py"):
                continue
            fpath = os.path.join(dirpath, fn)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    tree = ast.parse(f.read(), filename=fpath)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith("test_"):
                        count += 1
    return count


class TestCoverageMinimums:
    """Enforce minimum test counts per critical area."""

    def test_controllers_minimum(self):
        count = _count_test_functions(TESTS_ROOT / "controllers")
        assert count >= 50, f"controllers tests: {count} < 50 minimum"

    def test_services_minimum(self):
        count = _count_test_functions(TESTS_ROOT / "services")
        assert count >= 50, f"services tests: {count} < 50 minimum"

    def test_architecture_minimum(self):
        count = _count_test_functions(TESTS_ROOT / "architecture")
        assert count >= 5, f"architecture tests: {count} < 5 minimum"

    def test_simulation_minimum(self):
        count = _count_test_functions(TESTS_ROOT / "test_simulation")
        assert count >= 4, f"simulation tests: {count} < 4 minimum"

    def test_kernel_minimum(self):
        count = _count_test_functions(TESTS_ROOT / "controllers" / "test_kernel")
        assert count >= 10, f"kernel tests: {count} < 10 minimum"

    def test_total_minimum(self):
        total = sum(
            _count_test_functions(TESTS_ROOT / d)
            for d in ("controllers", "services", "architecture", "simulation", "scripts")
        )
        assert total >= 150, f"total tests: {total} < 150 minimum"
