"""Run backtesting tests with OOM protection.

Three run modes, chosen automatically based on available tooling:

1. --forked  (preferred): each test file in its own subprocess via pytest-forked
2. --batched : lightweight tests first, then heavyweight, separate processes
3. --single  : fallback single-process run with aggressive GC (conftest.py handles this)

Usage:
    PYTHONPATH=hbot python -m scripts.release.run_backtesting_tests
    PYTHONPATH=hbot python -m scripts.release.run_backtesting_tests --mode forked
    PYTHONPATH=hbot python -m scripts.release.run_backtesting_tests --mode batched
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_BACKTEST_DIR = "tests/controllers/test_backtesting"

_LIGHTWEIGHT_FILES = [
    "test_metrics.py",
    "test_harness_stress.py",
    "test_harness_cli.py",
    "test_csv_importer.py",
    "test_data_store.py",
    "test_replay_foundations.py",
    "test_harness.py",
]

_HEAVYWEIGHT_FILES = [
    "test_backtest_smoke.py",
    "test_runtime_adapter.py",
    "test_e2e_integration.py",
    "test_replay_harness.py",
    "test_replay_environment_verification.py",
    "test_replay_runtime_surfaces.py",
    "test_data_pipeline.py",
    "test_data_downloader.py",
    "test_walkforward.py",
    "test_sweep.py",
    "test_book_synthesizer.py",
    "test_historical_feed.py",
]


def _resolve_root() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in [here.parent.parent, Path.cwd()]:
        if (candidate / _BACKTEST_DIR).is_dir():
            return candidate
    sys.exit(f"Cannot find {_BACKTEST_DIR} relative to {here}")


def _run(cmd: list[str], cwd: Path) -> int:
    print(f"\n{'='*60}")
    print(f"  CMD: {' '.join(cmd)}")
    print(f"{'='*60}\n", flush=True)
    proc = subprocess.run(cmd, cwd=str(cwd), check=False)
    return proc.returncode


def run_forked(root: Path, extra_args: list[str]) -> int:
    """Each test file gets its own subprocess — memory freed between files."""
    cmd = [
        sys.executable, "-m", "pytest",
        _BACKTEST_DIR,
        "--forked",
        "-q", "--tb=short", "--disable-warnings",
        *extra_args,
    ]
    return _run(cmd, root)


def run_batched(root: Path, extra_args: list[str]) -> int:
    """Lightweight tests first (single process), then heavyweight one-by-one."""
    light_targets = [f"{_BACKTEST_DIR}/{f}" for f in _LIGHTWEIGHT_FILES]
    light_cmd = [
        sys.executable, "-m", "pytest",
        *light_targets,
        "-q", "--tb=short", "--disable-warnings",
        *extra_args,
    ]
    rc = _run(light_cmd, root)
    if rc != 0:
        print(f"\nLightweight batch failed (rc={rc}), skipping heavyweight.")
        return rc

    for f in _HEAVYWEIGHT_FILES:
        target = f"{_BACKTEST_DIR}/{f}"
        if not (root / target).exists():
            continue
        cmd = [
            sys.executable, "-m", "pytest",
            target,
            "-q", "--tb=short", "--disable-warnings",
            *extra_args,
        ]
        rc = _run(cmd, root)
        if rc != 0:
            print(f"\nHeavyweight test {f} failed (rc={rc}).")
            return rc
    return 0


def run_single(root: Path, extra_args: list[str]) -> int:
    """Single-process fallback — relies on conftest.py GC hooks."""
    cmd = [
        sys.executable, "-m", "pytest",
        _BACKTEST_DIR,
        "-q", "--tb=short", "--disable-warnings",
        *extra_args,
    ]
    return _run(cmd, root)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run backtesting tests with OOM protection")
    parser.add_argument(
        "--mode",
        choices=["forked", "batched", "single", "auto"],
        default="auto",
        help="Run mode (default: auto — tries forked, falls back to batched)",
    )
    args, extra = parser.parse_known_args()

    root = _resolve_root()
    mode = args.mode

    if mode == "auto":
        try:
            import pytest_forked  # noqa: F401
            mode = "forked"
        except ImportError:
            mode = "batched"

    print(f"Running backtesting tests in '{mode}' mode from {root}")

    runners = {"forked": run_forked, "batched": run_batched, "single": run_single}
    rc = runners[mode](root, extra)
    sys.exit(rc)


if __name__ == "__main__":
    main()
