"""Compatibility alias for historical `shared_mm_logging` imports.

Prefer importing from `controllers.strategy_runtime_logging`.
"""

from controllers.runtime.logging import CsvSplitLogger

__all__ = ["CsvSplitLogger"]
