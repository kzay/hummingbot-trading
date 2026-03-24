"""Feature builder for ML signal service.

Builds feature vectors from MarketSnapshotEvent for online inference.

Feature sets:
  v1 — basic 8 features (original)
  v2 — enriched 16 features for regime classification (ROAD-10)
  v3 — enriched features + time encoding for regime + adverse selection (ROAD-11)
"""
from __future__ import annotations

import hashlib
import json
import math
import time

from platform_lib.contracts.event_schemas import MarketSnapshotEvent


def _safe_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _time_encoding(timestamp_ms: int) -> tuple[float, float]:
    """Sine/cosine encoding of hour-of-day from timestamp_ms."""
    hour = (timestamp_ms // 3_600_000) % 24
    angle = 2 * math.pi * hour / 24.0
    return math.sin(angle), math.cos(angle)


def build_features(
    market: MarketSnapshotEvent,
    feature_set: str = "v1",
) -> tuple[list[float], dict[str, float], str]:
    """Build a feature vector from a MarketSnapshotEvent.

    Returns: (feature_vector, feature_map, feature_hash)
    - feature_vector: ordered list of floats for model.predict()
    - feature_map: named dict for debugging and feature importance
    - feature_hash: SHA-256 of feature_map for deduplication / audit
    """
    if feature_set == "v1":
        return _build_v1(market)
    if feature_set in ("v2", "v3"):
        return _build_v2(market, include_time=(feature_set == "v3"))
    raise ValueError(f"Unsupported feature_set={feature_set!r}. Use 'v1', 'v2', or 'v3'.")


def _build_v1(market: MarketSnapshotEvent) -> tuple[list[float], dict[str, float], str]:
    """Original 8-feature set (backward compatible)."""
    feature_map: dict[str, float] = {
        "mid_price": _safe_float(market.mid_price),
        "equity_quote": _safe_float(market.equity_quote),
        "base_pct": _safe_float(market.base_pct),
        "target_base_pct": _safe_float(market.target_base_pct),
        "spread_pct": _safe_float(market.spread_pct),
        "net_edge_pct": _safe_float(market.net_edge_pct),
        "turnover_x": _safe_float(market.turnover_x),
        "inventory_gap": _safe_float(market.target_base_pct - market.base_pct),
    }
    ordered_keys = sorted(feature_map.keys())
    feature_vector = [feature_map[k] for k in ordered_keys]
    feature_hash = hashlib.sha256(json.dumps(feature_map, sort_keys=True).encode()).hexdigest()
    return feature_vector, feature_map, feature_hash


def _build_v2(
    market: MarketSnapshotEvent,
    include_time: bool = False,
) -> tuple[list[float], dict[str, float], str]:
    """Enriched feature set (v2/v3) for regime classification and adverse fill prediction.

    Reads additional fields from market.extra dict populated by v2_with_controllers.py.
    Falls back gracefully when extra fields are missing.
    """
    extra = market.extra or {}

    mid = _safe_float(market.mid_price)
    eq = _safe_float(market.equity_quote)
    base = _safe_float(market.base_pct)
    tgt = _safe_float(market.target_base_pct)
    spread = _safe_float(market.spread_pct)
    net_edge = _safe_float(market.net_edge_pct)
    turnover = _safe_float(market.turnover_x)
    inv_gap = tgt - base

    band_pct = _safe_float(extra.get("band_pct", 0))
    adverse_drift_bps = _safe_float(extra.get("adverse_drift_bps", 0))
    funding_rate_bps = _safe_float(extra.get("funding_rate_bps", 0))
    ob_imbalance = _safe_float(extra.get("ob_imbalance", 0))
    fill_edge_ewma_bps = _safe_float(extra.get("fill_edge_ewma_bps", 0))
    drawdown_pct = _safe_float(extra.get("drawdown_pct", 0))

    feature_map: dict[str, float] = {
        "mid_price": mid,
        "equity_quote": eq,
        "base_pct": base,
        "target_base_pct": tgt,
        "spread_pct": spread,
        "net_edge_pct": net_edge,
        "turnover_x": turnover,
        "inventory_gap": inv_gap,
        "band_pct": band_pct,
        "adverse_drift_bps": adverse_drift_bps,
        "funding_rate_bps": funding_rate_bps,
        "ob_imbalance": ob_imbalance,
        "fill_edge_ewma_bps": fill_edge_ewma_bps,
        "drawdown_pct": drawdown_pct,
        "abs_inv_gap": abs(inv_gap),
        "spread_x_band": spread * band_pct,
    }

    if include_time:
        ts_ms = market.timestamp_ms or int(time.time() * 1000)
        time_sin, time_cos = _time_encoding(ts_ms)
        feature_map["time_sin"] = time_sin
        feature_map["time_cos"] = time_cos

    ordered_keys = sorted(feature_map.keys())
    feature_vector = [feature_map[k] for k in ordered_keys]
    feature_hash = hashlib.sha256(json.dumps(feature_map, sort_keys=True).encode()).hexdigest()
    return feature_vector, feature_map, feature_hash


def get_feature_names(feature_set: str = "v1") -> list[str]:
    """Return ordered feature names for a given feature set."""
    if feature_set == "v1":
        return sorted([
            "mid_price", "equity_quote", "base_pct", "target_base_pct",
            "spread_pct", "net_edge_pct", "turnover_x", "inventory_gap",
        ])
    if feature_set == "v2":
        return sorted([
            "mid_price", "equity_quote", "base_pct", "target_base_pct",
            "spread_pct", "net_edge_pct", "turnover_x", "inventory_gap",
            "band_pct", "adverse_drift_bps", "funding_rate_bps",
            "ob_imbalance", "fill_edge_ewma_bps", "drawdown_pct",
            "abs_inv_gap", "spread_x_band",
        ])
    if feature_set == "v3":
        return sorted([
            "mid_price", "equity_quote", "base_pct", "target_base_pct",
            "spread_pct", "net_edge_pct", "turnover_x", "inventory_gap",
            "band_pct", "adverse_drift_bps", "funding_rate_bps",
            "ob_imbalance", "fill_edge_ewma_bps", "drawdown_pct",
            "abs_inv_gap", "spread_x_band", "time_sin", "time_cos",
        ])
    raise ValueError(f"Unknown feature_set={feature_set!r}")
