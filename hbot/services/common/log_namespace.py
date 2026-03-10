from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator, Sequence

# Prefer neutral namespace first while still supporting legacy logs.
DEFAULT_LOG_NAMESPACES: tuple[str, ...] = ("runtime_v24", "epp_v24")


def _dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def _sort_by_mtime_desc(paths: Iterable[Path]) -> list[Path]:
    raw = _dedupe_paths(paths)
    try:
        return sorted(raw, key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return sorted(raw, key=lambda p: str(p))


def iter_bot_log_files(
    data_root: Path,
    filename: str,
    *,
    namespaces: Sequence[str] = DEFAULT_LOG_NAMESPACES,
) -> Iterator[Path]:
    if not filename:
        return
    yielded: set[Path] = set()
    for namespace in namespaces:
        pattern = f"*/logs/{namespace}/*/{filename}"
        for path in data_root.glob(pattern):
            if path in yielded:
                continue
            yielded.add(path)
            yield path


def list_bot_log_files(
    data_root: Path,
    filename: str,
    *,
    namespaces: Sequence[str] = DEFAULT_LOG_NAMESPACES,
) -> list[Path]:
    return _sort_by_mtime_desc(iter_bot_log_files(data_root, filename, namespaces=namespaces))


def list_bot_log_dirs(
    bot_data_dir: Path,
    *,
    namespaces: Sequence[str] = DEFAULT_LOG_NAMESPACES,
) -> list[Path]:
    dirs: list[Path] = []
    for namespace in namespaces:
        dirs.extend(bot_data_dir.glob(f"logs/{namespace}/*/"))
    return _sort_by_mtime_desc(dirs)


def list_instance_log_files(
    data_root: Path,
    instance_name: str,
    filename: str,
    *,
    namespaces: Sequence[str] = DEFAULT_LOG_NAMESPACES,
) -> list[Path]:
    if not instance_name or not filename:
        return []
    files: list[Path] = []
    for namespace in namespaces:
        root = data_root / instance_name / "logs" / namespace
        if not root.exists():
            continue
        files.extend(root.glob(f"*/{filename}"))
    return _sort_by_mtime_desc(files)
