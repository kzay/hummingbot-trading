from __future__ import annotations

import time
from pathlib import Path

from platform_lib.logging.log_namespace import iter_bot_log_files


def active_bots_from_minute_logs(data_root: Path, *, active_within_minutes: int = 30) -> dict[str, dict[str, object]]:
    now_ts = time.time()
    max_age_seconds = max(1, int(active_within_minutes)) * 60
    active: dict[str, dict[str, object]] = {}
    for minute_file in iter_bot_log_files(data_root, "minute.csv"):
        try:
            mtime = float(minute_file.stat().st_mtime)
        except (OSError, ValueError):
            continue
        age_seconds = max(0.0, now_ts - mtime)
        if age_seconds > max_age_seconds:
            continue
        try:
            bot = minute_file.parts[-5]
        except (IndexError, TypeError):
            continue
        current = active.get(bot)
        if current is None or float(current.get("mtime", 0.0)) < mtime:
            active[bot] = {
                "minute_path": str(minute_file),
                "mtime": mtime,
                "age_seconds": age_seconds,
            }
    return active
