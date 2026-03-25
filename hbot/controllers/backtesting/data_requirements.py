"""Data requirements manifest: load and compute refresh scope from YAML."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_MANIFEST = Path(__file__).resolve().parent.parent.parent / "config" / "data_requirements.yml"


def load_manifest(path: str | Path | None = None) -> dict[str, Any]:
    """Parse the YAML manifest and return raw dict.

    Falls back to the default ``config/data_requirements.yml`` when *path* is
    ``None``.  Returns ``{"consumers": {}}`` if the file is missing or invalid.
    """
    p = Path(path) if path else _DEFAULT_MANIFEST
    if not p.exists():
        logger.warning("Data requirements manifest not found at %s — using empty defaults", p)
        return {"consumers": {}}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "consumers" not in data:
            logger.warning("Manifest at %s missing 'consumers' key — using empty defaults", p)
            return {"consumers": {}}
        return data
    except yaml.YAMLError as exc:
        logger.warning("Invalid YAML in manifest %s: %s — using empty defaults", p, exc)
        return {"consumers": {}}


def compute_refresh_scope(manifest: dict[str, Any]) -> dict[str, Any]:
    """Derive the union of all consumer requirements.

    Returns::

        {
            "pairs": ["BTC-USDT", "ETH-USDT"],
            "canonical_datasets": ["1m", "mark_1m", ...],
            "materialized_datasets": ["5m", "15m", "1h"],
            "exchange": "bitget",
            "max_lookback_bars": 20160,
            "retention_policy": "full_history" | None,
            "bootstrap_from": "90d" | None,
        }
    """
    consumers = manifest.get("consumers", {})

    pairs: set[str] = set()
    canonical: set[str] = set()
    materialized: set[str] = set()
    exchanges: set[str] = set()
    max_lookback = 0
    has_full_history = False
    bootstrap_from: str | None = None

    for _name, spec in consumers.items():
        if not isinstance(spec, dict):
            continue
        for p in spec.get("pairs", []):
            pairs.add(p)
        for d in spec.get("canonical_datasets", []):
            canonical.add(d)
        for d in spec.get("materialized_datasets", []):
            materialized.add(d)
        ex = spec.get("exchange")
        if ex:
            exchanges.add(ex)
        lb = spec.get("required_lookback_bars", 0)
        if lb and lb > max_lookback:
            max_lookback = lb
        if spec.get("retention_policy") == "full_history":
            has_full_history = True
        bf = spec.get("bootstrap_from")
        if bf:
            bootstrap_from = bf

    exchange = sorted(exchanges)[0] if exchanges else "bitget"

    return {
        "pairs": sorted(pairs),
        "canonical_datasets": sorted(canonical),
        "materialized_datasets": sorted(materialized),
        "exchange": exchange,
        "max_lookback_bars": max_lookback,
        "retention_policy": "full_history" if has_full_history else None,
        "bootstrap_from": bootstrap_from,
    }
