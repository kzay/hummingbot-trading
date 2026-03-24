"""Data readers — canonical module name for fallback_readers.

The legacy name ``fallback_readers`` is retained for backward compatibility.
New imports should use ``data_readers`` instead.
"""
from services.realtime_ui_api.fallback_readers import *  # noqa: F401, F403
from services.realtime_ui_api.fallback_readers import DeskSnapshotFallback, OpsDbReadModel  # noqa: F401
