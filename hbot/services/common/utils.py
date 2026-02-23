"""Canonical utility helpers shared across all services and scripts.

Every service/script should import from here instead of defining its own
``_safe_float``, ``_utc_now``, ``_read_json``, etc.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional


def to_decimal(value: Any) -> Decimal:
    """Convert any value to Decimal via its string representation (safe)."""
    return Decimal(str(value))


def safe_float(value: object, default: float = 0.0) -> float:
    """Parse *value* as float, returning *default* on failure."""
    try:
        if value in (None, ""):
            return default
        return float(str(value))
    except (TypeError, ValueError):
        return default


def safe_bool(value: object, default: bool = False) -> bool:
    """Interpret common truthy strings (``1``, ``true``, ``yes``, ``on``)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    """Read an integer from an environment variable with fallback."""
    import os

    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_bool(name: str, default: bool) -> bool:
    """Read a boolean from an environment variable with fallback."""
    import os

    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def today_utc() -> str:
    """Return the current UTC date as ``YYYYMMDD``."""
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def now_ms() -> int:
    """Epoch milliseconds (UTC)."""
    import time

    return int(time.time() * 1000)


def parse_iso_ts(value: object) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def read_json(path: Path, default: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Read a JSON file and return its dict payload, or *default* on error."""
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else default
    except Exception:
        return default


def write_json(path: Path, payload: Dict[str, object]) -> None:
    """Write a dict as pretty-printed JSON, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def read_last_csv_row(path: Path) -> Optional[Dict[str, str]]:
    """Return the last data row from a CSV file, or ``None``.

    Uses a tail-seek strategy: reads the last 8 KB of the file to find the
    last complete line, then parses it with the header from line 1.
    Falls back to full iteration for very small files.
    """
    if not path.exists():
        return None
    try:
        size = path.stat().st_size
        if size == 0:
            return None
        with path.open("r", encoding="utf-8", newline="") as f:
            header_line = f.readline().strip()
            if not header_line:
                return None
            fieldnames = header_line.split(",")
            if size <= 8192:
                reader = csv.DictReader(f, fieldnames=fieldnames)
                last = None
                for row in reader:
                    last = row
                return last
            f.seek(max(0, size - 8192))
            f.readline()
            lines = f.readlines()
            if not lines:
                return None
            for line in reversed(lines):
                stripped = line.strip()
                if stripped and stripped != header_line:
                    values = stripped.split(",")
                    if len(values) == len(fieldnames):
                        return dict(zip(fieldnames, values))
    except Exception:
        return None
    return None


def read_last_n_csv_rows(path: Path, n: int = 2) -> List[Dict[str, str]]:
    """Return the last *n* data rows from a CSV file."""
    if not path.exists() or n <= 0:
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows: List[Dict[str, str]] = []
            for row in reader:
                rows.append(row)
                if len(rows) > n:
                    rows.pop(0)
            return rows
    except Exception:
        return []


def count_csv_rows(path: Path) -> int:
    """Count data rows (excluding header) in a CSV file."""
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            count = -1
            for _ in reader:
                count += 1
        return max(0, count)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Cached file reader (mtime-based)
# ---------------------------------------------------------------------------

class CachedJsonFile:
    """Reads a JSON file and caches the result until the file changes.

    Uses ``os.path.getmtime()`` to detect changes — avoids re-parsing
    on every access when the file hasn't been modified.
    """

    def __init__(self, path: Path, default: Optional[Dict[str, object]] = None):
        self._path = path
        self._default = default if default is not None else {}
        self._mtime: float = 0.0
        self._cached: Dict[str, object] = dict(self._default)

    def get(self) -> Dict[str, object]:
        """Return the cached payload, re-reading only if mtime changed."""
        import os
        try:
            current_mtime = os.path.getmtime(self._path)
        except OSError:
            return dict(self._default)
        if current_mtime != self._mtime:
            self._mtime = current_mtime
            self._cached = read_json(self._path, self._default)
        return self._cached
