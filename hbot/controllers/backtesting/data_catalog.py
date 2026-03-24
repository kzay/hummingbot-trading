"""Data catalog: JSON manifest tracking available historical datasets."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class DataCatalog:
    """JSON-file-backed catalog of available historical datasets.

    The catalog lives at ``{base_dir}/catalog.json`` and is loaded/saved
    atomically on each mutation.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._path = base_dir / "catalog.json"
        self._datasets: list[dict] = []
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._datasets = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("Corrupt catalog at %s — starting fresh", self._path)
                self._datasets = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._datasets, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(
        self,
        exchange: str,
        pair: str,
        resolution: str,
        start_ms: int,
        end_ms: int,
        row_count: int,
        file_path: str,
        file_size_bytes: int,
    ) -> None:
        """Add or update a dataset entry."""
        entry = {
            "exchange": exchange,
            "pair": pair,
            "resolution": resolution,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "row_count": row_count,
            "file_path": file_path,
            "file_size_bytes": file_size_bytes,
            "registered_at": datetime.now(tz=UTC).isoformat(),
        }
        exact_key = (exchange, pair, resolution, start_ms, end_ms, file_path)
        self._datasets = [
            d for d in self._datasets
            if (
                d["exchange"],
                d["pair"],
                d["resolution"],
                d["start_ms"],
                d["end_ms"],
                d["file_path"],
            ) != exact_key
        ]
        self._datasets.append(entry)
        self._save()
        logger.info("Registered dataset: %s/%s/%s (%d rows)", exchange, pair, resolution, row_count)

    def list_datasets(self) -> list[dict]:
        """Return all registered datasets."""
        return list(self._datasets)

    def find(
        self,
        exchange: str,
        pair: str,
        resolution: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> dict | None:
        """Find the best matching dataset for a given key and optional window.

        Selection priority when *start_ms* / *end_ms* are provided:
        1. Prefer datasets that fully cover ``[start_ms, end_ms]``.
        2. Among equally suitable candidates, prefer the widest coverage.
        3. Break ties by newest registration time.

        When *start_ms* / *end_ms* are omitted, prefer the widest range
        (then newest), which is the safest default for general callers.
        """
        matches = [
            d for d in self._datasets
            if d["exchange"] == exchange and d["pair"] == pair and d["resolution"] == resolution
        ]
        if not matches:
            return None

        def _sort_key(d: dict) -> tuple:
            d_start = int(d["start_ms"])
            d_end = int(d["end_ms"])
            width = d_end - d_start
            reg_ts = datetime.fromisoformat(str(d["registered_at"])).timestamp()

            if start_ms is not None and end_ms is not None:
                covers = d_start <= start_ms and d_end >= end_ms
            else:
                covers = True

            # Primary: full coverage first (True > False, so negate)
            # Secondary: widest range first (negate width)
            # Tertiary: newest registration first
            return (not covers, -width, -reg_ts)

        matches.sort(key=_sort_key)
        return dict(matches[0])

    def remove(self, exchange: str, pair: str, resolution: str) -> bool:
        """Remove a dataset entry. Returns True if found and removed."""
        before = len(self._datasets)
        self._datasets = [
            d for d in self._datasets
            if (d["exchange"], d["pair"], d["resolution"]) != (exchange, pair, resolution)
        ]
        if len(self._datasets) < before:
            self._save()
            return True
        return False
