from __future__ import annotations

import hashlib
import json
from typing import Dict, List, Tuple

from services.contracts.event_schemas import MarketSnapshotEvent


def build_features(market: MarketSnapshotEvent, feature_set: str = "v1") -> Tuple[List[float], Dict[str, float], str]:
    if feature_set != "v1":
        raise ValueError(f"Unsupported feature_set={feature_set}")
    feature_map: Dict[str, float] = {
        "mid_price": float(market.mid_price),
        "equity_quote": float(market.equity_quote),
        "base_pct": float(market.base_pct),
        "target_base_pct": float(market.target_base_pct),
        "spread_pct": float(market.spread_pct),
        "net_edge_pct": float(market.net_edge_pct),
        "turnover_x": float(market.turnover_x),
        "inventory_gap": float(market.target_base_pct - market.base_pct),
    }
    ordered_keys = sorted(feature_map.keys())
    feature_vector = [feature_map[k] for k in ordered_keys]
    feature_hash = hashlib.sha256(json.dumps(feature_map, sort_keys=True).encode("utf-8")).hexdigest()
    return feature_vector, feature_map, feature_hash

