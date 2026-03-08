"""Shared runtime logging exports used by strategy lanes and base runtime."""

from controllers.epp_logging import CsvSplitLogger

StrategyCsvLogger = CsvSplitLogger

__all__ = [
    "CsvSplitLogger",
    "StrategyCsvLogger",
]
