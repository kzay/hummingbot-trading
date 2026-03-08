"""Compatibility alias for the canonical runtime logging module.

Prefer importing from `controllers.runtime.logging`.
"""

from controllers.runtime.logging import CsvSplitLogger, StrategyCsvLogger

__all__ = [
    "CsvSplitLogger",
    "StrategyCsvLogger",
]
