from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any


def _event_files(event_store_root: Path) -> list[Path]:
    return sorted(event_store_root.glob("events_*.jsonl"), reverse=True)


def _read_jsonl_reverse(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for raw in reversed(lines):
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(payload, dict):
            out.append(payload)
    return out


def _iter_lines_reverse(path: Path, *, chunk_size: int = 1024 * 1024) -> Iterator[str]:
    """Yield lines from a text file in reverse order without loading it fully."""
    if not path.exists():
        return
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            file_size = handle.tell()
            remainder = b""
            position = file_size
            while position > 0:
                read_size = min(chunk_size, position)
                position -= read_size
                handle.seek(position)
                chunk = handle.read(read_size)
                parts = (chunk + remainder).split(b"\n")
                remainder = parts[0]
                for raw in reversed(parts[1:]):
                    yield raw.decode("utf-8", errors="ignore")
            if remainder:
                yield remainder.decode("utf-8", errors="ignore")
    except Exception:
        return


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    """Yield parsed JSONL rows in file order with bounded memory use."""
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(payload, dict):
                    yield payload
    except OSError:
        return []


def _iter_jsonl_reverse_streaming(path: Path) -> Iterable[dict[str, Any]]:
    """Yield parsed JSONL rows in reverse order with bounded memory use."""
    for raw in _iter_lines_reverse(path):
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(payload, dict):
            yield payload


def _merged_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload", {}) if isinstance(row.get("payload"), dict) else {}
    merged: dict[str, Any] = dict(payload)
    for key in ("event_id", "event_type", "ts_utc", "instance_name", "controller_id", "connector_name", "trading_pair"):
        value = row.get(key)
        if value not in (None, "") and key not in merged:
            merged[key] = value
    if "ts" not in merged and row.get("ts_utc"):
        merged["ts"] = row.get("ts_utc")
    return merged


def load_bot_snapshot_windows(
    event_store_root: Path,
    *,
    max_snapshots_per_bot: int = 2,
) -> dict[str, list[dict[str, Any]]]:
    windows: dict[str, list[dict[str, Any]]] = {}
    max_snapshots_per_bot = max(1, int(max_snapshots_per_bot))
    for event_file in _event_files(event_store_root):
        all_satisfied = bool(windows) and all(len(rows) >= max_snapshots_per_bot for rows in windows.values())
        if all_satisfied:
            break
        for row in _iter_jsonl_reverse_streaming(event_file):
            if str(row.get("event_type", "")).strip() != "bot_minute_snapshot":
                continue
            snapshot = _merged_snapshot(row)
            bot = str(snapshot.get("instance_name", "")).strip()
            if not bot:
                continue
            bucket = windows.setdefault(bot, [])
            if len(bucket) >= max_snapshots_per_bot:
                continue
            bucket.append(snapshot)
    return windows


def count_bot_fill_events(event_store_root: Path, bot: str, *, day_utc: str | None = None) -> int:
    files: list[Path]
    if day_utc:
        files = [event_store_root / f"events_{str(day_utc).replace('-', '')}.jsonl"]
    else:
        files = _event_files(event_store_root)
    count = 0
    bot_name = str(bot or "").strip()
    for event_file in files:
        for row in _iter_jsonl(event_file):
            event_type = str(row.get("event_type", "")).strip().lower()
            if event_type not in {"order_filled", "bot_fill"}:
                continue
            if str(row.get("instance_name", "")).strip() != bot_name:
                continue
            count += 1
    return count
