"""conftest.py for test_backtesting — OOM prevention.

Two mechanisms:
1. GC cleanup after every test class / module to reduce peak memory.
2. pytest markers (heavyweight / lightweight) so CI can split runs.

For full OOM protection in containers, run with:
    pytest tests/controllers/test_backtesting/ --forked
or:
    pytest tests/controllers/test_backtesting/ -n auto --forked
"""
from __future__ import annotations

import gc
from typing import Generator

import pytest

# ---------------------------------------------------------------------------
# Heavyweight test modules — these transitively pull in simulation.*,
# controllers.runtime.*, pandas, pyarrow, ccxt, scikit-learn, etc.
# ---------------------------------------------------------------------------
_HEAVYWEIGHT_MODULES = frozenset({
    "test_e2e_integration",
    "test_backtest_smoke",
    "test_runtime_adapter",
    "test_replay_harness",
    "test_replay_environment_verification",
    "test_replay_runtime_surfaces",
    "test_data_pipeline",
    "test_data_downloader",
    "test_walkforward",
    "test_sweep",
    "test_book_synthesizer",
    "test_historical_feed",
})


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-tag tests as heavyweight or lightweight based on their module."""
    heavy = pytest.mark.heavyweight
    light = pytest.mark.lightweight
    for item in items:
        module_name = item.module.__name__.rsplit(".", 1)[-1] if item.module else ""
        if module_name in _HEAVYWEIGHT_MODULES:
            item.add_marker(heavy)
        else:
            item.add_marker(light)


@pytest.fixture(autouse=True)
def _gc_after_each_test() -> Generator[None, None, None]:
    """Force garbage collection after every test to release transient allocations."""
    yield
    gc.collect()


def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> None:
    """Aggressive GC at module boundaries (when the next test is in a different file).

    This is where the biggest wins come in single-process mode: the previous
    module's test fixtures, mock objects, and captured DataFrames become
    collectible before the next module's imports land.
    """
    if nextitem is None or (item.module is not nextitem.module):
        gc.collect()
