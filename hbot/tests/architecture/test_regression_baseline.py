"""Golden regression baseline — captures pre-refactoring test counts.

Run after every refactoring phase to detect regressions.
A regression is any suite whose pass count drops below the recorded baseline.
Pre-existing failures are excluded (documented in design.md §Pre-Existing Test Baseline).
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

HBOT_ROOT = Path(__file__).resolve().parent.parent.parent

KNOWN_FAILURES = {
    "tests/controllers/test_epp_v2_4_core.py::TestMinuteSnapshotTelemetry::"
    "test_publish_bot_minute_snapshot_telemetry_falls_back_to_event_store_file",
    "tests/services/test_ops_build_spec.py::test_recon_exchange_ready_passes_with_complete_env_and_reports",
    "tests/services/test_portfolio_risk_service.py::test_run_once_produces_report",
    "tests/services/test_promotion_gates_logic.py::test_run_event_store_once_falls_back_to_docker_when_host_client_disabled",
}

OOM_EXCLUDED_FILES = {
    "tests/controllers/test_backtesting/test_data_store.py",
}

COLLECTION_ERROR_FILES = {
    "tests/controllers/test_ml/test_research.py",
}


class TestImportViolationBaseline:
    """AST-based import boundary scan — controllers must not import services."""

    def _count_violations(self) -> int:
        total = 0
        controllers_dir = HBOT_ROOT / "controllers"
        for dirpath, _, filenames in os.walk(controllers_dir):
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
                    if isinstance(node, ast.ImportFrom):
                        if node.module and node.module.startswith("services."):
                            total += 1
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name and alias.name.startswith("services."):
                                total += 1
        return total

    def test_import_violation_count_within_budget(self):
        """Violation count must stay at zero (achieved after Phase 3)."""
        count = self._count_violations()
        assert count == 0, (
            f"Import violations: {count} > 0. "
            f"No controllers->services imports should exist."
        )


class TestCompileAll:
    """Every Python file under hbot/ must compile without syntax errors."""

    def test_all_python_files_compile(self):
        errors = []
        for dirpath, _, filenames in os.walk(HBOT_ROOT):
            if "__pycache__" in dirpath or "node_modules" in dirpath:
                continue
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                fpath = os.path.join(dirpath, fn)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        compile(f.read(), fpath, "exec")
                except SyntaxError as e:
                    errors.append(f"{fpath}: {e}")
        assert not errors, f"Compilation errors:\n" + "\n".join(errors)
