"""JSONL-backed hypothesis and experiment manifest registry.

Each candidate gets its own JSONL file under ``hbot/data/research/experiments/``.
Lines are append-only immutable manifests linking config, git SHA, data window,
seed, fill model, and result paths.
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_EXPERIMENTS_DIR = Path("hbot/data/research/experiments")


def _get_git_sha() -> str:
    """Capture current git HEAD SHA, suffixed with -dirty if uncommitted changes."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        dirty_check = subprocess.run(
            ["git", "diff", "--quiet"],
            capture_output=True, timeout=5,
        )
        if dirty_check.returncode != 0:
            sha += "-dirty"
        return sha
    except Exception:
        return "unknown"


def _config_hash(config: dict[str, Any]) -> str:
    """SHA-256 of the serialised config dict for reproducibility."""
    blob = json.dumps(config, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


class HypothesisRegistry:
    """Append-only JSONL registry for experiment manifests."""

    def __init__(self, experiments_dir: str | Path | None = None) -> None:
        self._dir = Path(experiments_dir or _DEFAULT_EXPERIMENTS_DIR)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _manifest_path(self, candidate_name: str) -> Path:
        safe_name = candidate_name.replace("/", "_").replace("\\", "_")
        return self._dir / f"{safe_name}.jsonl"

    def record_experiment(
        self,
        candidate_name: str,
        config: dict[str, Any],
        data_window: tuple[str, str],
        seed: int,
        fill_model: str,
        result_path: str,
        robustness_score: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append an immutable experiment manifest and return it."""
        manifest = {
            "run_id": str(uuid.uuid4()),
            "candidate_name": candidate_name,
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "config_hash": _config_hash(config),
            "git_sha": _get_git_sha(),
            "data_window": {"start": data_window[0], "end": data_window[1]},
            "seed": seed,
            "fill_model": fill_model,
            "result_path": result_path,
            "robustness_score": robustness_score,
        }
        if extra:
            manifest["extra"] = extra

        path = self._manifest_path(candidate_name)
        with open(path, "a") as f:
            f.write(json.dumps(manifest, default=str) + "\n")

        logger.info("Recorded experiment %s for candidate %s", manifest["run_id"], candidate_name)
        return manifest

    def list_experiments(
        self,
        candidate_name: str,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Read and optionally filter experiment manifests for a candidate."""
        path = self._manifest_path(candidate_name)
        if not path.exists():
            return []

        results: list[dict[str, Any]] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                results.append(entry)

        if not filters:
            return results

        filtered = results
        if "min_score" in filters:
            min_s = filters["min_score"]
            filtered = [e for e in filtered if (e.get("robustness_score") or 0) >= min_s]
        if "fill_model" in filters:
            fm = filters["fill_model"]
            filtered = [e for e in filtered if e.get("fill_model") == fm]
        if "date_start" in filters:
            ds = filters["date_start"]
            filtered = [e for e in filtered if e.get("timestamp_utc", "") >= ds]
        if "date_end" in filters:
            de = filters["date_end"]
            filtered = [e for e in filtered if e.get("timestamp_utc", "") <= de]

        return filtered
