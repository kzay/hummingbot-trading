"""Data catalog: JSON manifest tracking available historical datasets."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def _file_sha256(path: Path) -> str:
    """Compute hex-encoded SHA-256 of *path* using 8 KB chunked reads."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


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
        sha256 = ""
        resolved = Path(file_path)
        if not resolved.is_absolute():
            resolved = self._base_dir / file_path
        if resolved.exists():
            try:
                sha256 = _file_sha256(resolved)
            except OSError:
                logger.warning("Could not compute SHA-256 for %s", resolved)

        # Normalize path separators so Windows-registered paths work on Linux.
        normalized_path = file_path.replace("\\", "/")
        entry = {
            "exchange": exchange,
            "pair": pair,
            "resolution": resolution,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "row_count": row_count,
            "file_path": normalized_path,
            "file_size_bytes": file_size_bytes,
            "sha256": sha256,
            "registered_at": datetime.now(tz=UTC).isoformat(),
        }
        exact_key = (exchange, pair, resolution, start_ms, end_ms, normalized_path)
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
        result = dict(matches[0])
        # Normalize path separators to the current OS so Windows-registered
        # entries (backslashes) resolve correctly on Linux containers.
        if "file_path" in result:
            fp = result["file_path"].replace("\\", "/")
            # Resolve relative paths to absolute using base_dir as anchor.
            # Walk up from base_dir until the file is found, handling cases
            # where the stored path was relative to a parent of base_dir
            # (e.g., stored as "hbot/data/..." but base_dir is "data/historical").
            p = Path(fp)
            if not p.is_absolute():
                candidate = p
                # Try resolving from each ancestor of base_dir (up to 4 levels)
                search_root = self._base_dir.resolve()
                found = False
                for _ in range(5):
                    resolved = search_root / fp
                    if resolved.exists():
                        candidate = resolved
                        found = True
                        break
                    if search_root.parent == search_root:
                        break
                    search_root = search_root.parent
                if found:
                    fp = str(candidate)
            result["file_path"] = fp
        return result

    # ------------------------------------------------------------------
    # Integrity verification
    # ------------------------------------------------------------------

    def verify_entry(self, entry: dict) -> list[str]:
        """Check a single catalog entry against the file on disk.

        Returns a list of warning strings (empty = all checks passed).
        """
        warnings: list[str] = []
        fp = Path(entry.get("file_path", ""))
        if not fp.is_absolute():
            fp = self._base_dir / fp

        if not fp.exists():
            warnings.append(f"File missing: {fp}")
            return warnings

        actual_size = fp.stat().st_size
        expected_size = entry.get("file_size_bytes")
        if expected_size is not None and actual_size != expected_size:
            warnings.append(
                f"Size mismatch: expected {expected_size}, got {actual_size}"
            )

        expected_hash = entry.get("sha256", "")
        if expected_hash:
            actual_hash = _file_sha256(fp)
            if actual_hash != expected_hash:
                warnings.append(
                    f"SHA-256 mismatch: expected {expected_hash[:16]}…, "
                    f"got {actual_hash[:16]}…"
                )
        else:
            logger.warning(
                "No sha256 in catalog entry %s/%s/%s — skipping hash check",
                entry.get("exchange"), entry.get("pair"), entry.get("resolution"),
            )

        expected_rows = entry.get("row_count")
        if expected_rows is not None:
            try:
                import pyarrow.parquet as pq
                pf = pq.ParquetFile(fp)
                actual_rows = pf.metadata.num_rows
                if actual_rows != expected_rows:
                    warnings.append(
                        f"Row count mismatch: expected {expected_rows}, got {actual_rows}"
                    )
            except Exception as exc:
                warnings.append(f"Could not read parquet metadata: {exc}")

        return warnings

    def verify_all(self) -> dict[str, list[str]]:
        """Run ``verify_entry`` on every catalog entry.

        Returns a dict mapping ``"{exchange}/{pair}/{resolution}"`` to
        warning lists.  Entries with empty warning lists passed all checks.
        """
        results: dict[str, list[str]] = {}
        for entry in self._datasets:
            key = f"{entry.get('exchange')}/{entry.get('pair')}/{entry.get('resolution')}"
            results[key] = self.verify_entry(entry)
        return results

    def reconcile_disk(self, base_dir: Path | None = None) -> dict:
        """Compare catalog entries with actual parquet files on disk.

        Returns ``{"orphans": [...], "stale": [...]}``:
        - *orphans*: ``data.parquet`` files on disk with no catalog entry.
        - *stale*: catalog entries whose ``file_path`` does not exist.
        """
        scan_dir = base_dir or self._base_dir
        catalog_paths: set[str] = set()
        stale: list[dict] = []
        for entry in self._datasets:
            fp = Path(entry.get("file_path", ""))
            if not fp.is_absolute():
                fp = self._base_dir / fp
            catalog_paths.add(str(fp.resolve()))
            if not fp.exists():
                stale.append(entry)

        orphans: list[str] = []
        for pq in scan_dir.rglob("data.parquet"):
            if str(pq.resolve()) not in catalog_paths:
                orphans.append(str(pq))

        return {"orphans": orphans, "stale": stale}

    # ------------------------------------------------------------------
    # Removal
    # ------------------------------------------------------------------

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
