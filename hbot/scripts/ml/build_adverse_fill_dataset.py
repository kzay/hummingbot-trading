"""Build training dataset for the ML adverse fill classifier (ROAD-11).

Joins fills.csv with minute.csv on nearest timestamp to get market state features
at fill time. Labels each fill as adverse (pnl_vs_mid < -2 bps).

Requirements:
    pip install pandas pyarrow

Usage:
    python hbot/scripts/ml/build_adverse_fill_dataset.py
    python hbot/scripts/ml/build_adverse_fill_dataset.py --root hbot/data/bot1/logs/epp_v24/bot1_a

Gate: Run after collecting >= 5,000 fills (~20 days at current fill rate).
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ADVERSE_THRESHOLD_BPS = -2.0

FILL_FEATURES = [
    "side",  # encoded as 0=buy, 1=sell
    "is_maker",  # 0 or 1
]

MINUTE_FEATURES = [
    "regime",  # one-hot encoded
    "spread_pct",
    "net_edge_pct",
    "adverse_drift_30s",
    "spread_floor_pct",
    "base_pct",
    "ob_imbalance",
    "fill_edge_ewma_bps",
    "turnover_today_x",
    "time_sin",  # computed from ts
    "time_cos",  # computed from ts
]

REGIME_LABELS = ["neutral_low_vol", "neutral_high_vol", "up", "down", "high_vol_shock"]


def _safe_float(x, default: float = 0.0) -> float:
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return default


def _parse_ts(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _load_csv(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = _parse_ts(row.get("ts", ""))
            if ts is None:
                continue
            rows.append({"_ts": ts, **row})
    rows.sort(key=lambda r: r["_ts"])
    return rows


def _find_nearest_minute(minute_rows: List[Dict], ts: datetime) -> Optional[Dict]:
    """Binary search for nearest minute row by timestamp."""
    if not minute_rows:
        return None
    lo, hi = 0, len(minute_rows) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if minute_rows[mid]["_ts"] < ts:
            lo = mid + 1
        else:
            hi = mid
    if lo > 0:
        d1 = abs((minute_rows[lo]["_ts"] - ts).total_seconds())
        d0 = abs((minute_rows[lo - 1]["_ts"] - ts).total_seconds())
        if d0 < d1:
            return minute_rows[lo - 1]
    return minute_rows[lo]


def _compute_pnl_vs_mid_bps(row: Dict) -> float:
    price = _safe_float(row.get("price", 0))
    mid_ref = _safe_float(row.get("mid_ref", 0))
    side = str(row.get("side", "")).lower().strip()
    if mid_ref <= 0 or price <= 0:
        return 0.0
    if side == "buy":
        return (mid_ref - price) / mid_ref * 10000
    else:
        return (price - mid_ref) / mid_ref * 10000


def build_feature_vector(fill_row: Dict, minute_row: Optional[Dict]) -> Dict[str, float]:
    import math

    feats: Dict[str, float] = {}

    side = str(fill_row.get("side", "")).lower().strip()
    feats["side_buy"] = 1.0 if side == "buy" else 0.0
    feats["side_sell"] = 1.0 if side == "sell" else 0.0
    feats["is_maker"] = 1.0 if str(fill_row.get("is_maker", "")).lower() in {"true", "1", "yes"} else 0.0

    ts = fill_row.get("_ts")
    if ts is not None and isinstance(ts, datetime):
        hour = ts.hour
        feats["time_sin"] = math.sin(2 * math.pi * hour / 24.0)
        feats["time_cos"] = math.cos(2 * math.pi * hour / 24.0)
    else:
        feats["time_sin"] = 0.0
        feats["time_cos"] = 0.0

    regime_str = ""
    if minute_row:
        regime_str = str(minute_row.get("regime", "")).strip()
        feats["spread_pct"] = _safe_float(minute_row.get("spread_pct", 0))
        feats["net_edge_pct"] = _safe_float(minute_row.get("net_edge_pct", 0))
        feats["adverse_drift_bps"] = _safe_float(minute_row.get("adverse_drift_30s", 0)) * 10000
        feats["spread_floor_pct"] = _safe_float(minute_row.get("spread_floor_pct", 0))
        feats["base_pct"] = _safe_float(minute_row.get("base_pct", 0))
        feats["ob_imbalance"] = _safe_float(minute_row.get("ob_imbalance", 0))
        feats["fill_edge_ewma_bps"] = _safe_float(minute_row.get("fill_edge_ewma_bps", 0))
        feats["turnover_x"] = _safe_float(minute_row.get("turnover_today_x", 0))
    else:
        for k in ["spread_pct", "net_edge_pct", "adverse_drift_bps", "spread_floor_pct",
                  "base_pct", "ob_imbalance", "fill_edge_ewma_bps", "turnover_x"]:
            feats[k] = 0.0

    for r in REGIME_LABELS:
        feats[f"regime_{r}"] = 1.0 if regime_str == r else 0.0

    feats["base_pct_signed"] = feats["base_pct"] * (1.0 if side == "sell" else -1.0)

    return feats


def build_dataset(fills_path: Path, minute_path: Path, output_dir: Path) -> Path:
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        print("ERROR: pandas and pyarrow required. Run: pip install pandas pyarrow", file=sys.stderr)
        sys.exit(1)

    fills = _load_csv(fills_path)
    minute_rows = _load_csv(minute_path)

    if not fills:
        print(f"ERROR: No fills found at {fills_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(fills)} fills, {len(minute_rows)} minute rows", file=sys.stderr)

    feature_dicts: List[Dict[str, float]] = []
    labels: List[int] = []
    pnl_bps_list: List[float] = []

    for fill in fills:
        nearest_min = _find_nearest_minute(minute_rows, fill["_ts"])
        feats = build_feature_vector(fill, nearest_min)

        pnl_bps = _compute_pnl_vs_mid_bps(fill)
        label = 1 if pnl_bps < ADVERSE_THRESHOLD_BPS else 0

        feature_dicts.append(feats)
        labels.append(label)
        pnl_bps_list.append(pnl_bps)

    df = pd.DataFrame(feature_dicts)
    df["adverse_label"] = labels
    df["pnl_vs_mid_bps"] = pnl_bps_list

    adverse_rate = sum(labels) / max(1, len(labels))
    print(f"Adverse fill rate: {adverse_rate:.1%} ({sum(labels)}/{len(labels)} fills)", file=sys.stderr)
    print(f"Features: {list(df.columns)}", file=sys.stderr)

    output_dir.mkdir(parents=True, exist_ok=True)
    from datetime import date
    date_str = date.today().strftime("%Y%m%d")
    out_path = output_dir / f"adverse_fill_train_{date_str}.parquet"
    df.to_parquet(out_path, index=False)
    print(f"Saved {len(df)} rows to {out_path}", file=sys.stderr)

    if len(df) < 5_000:
        print(f"WARNING: Only {len(df)} fills (need >= 5,000 for reliable training).", file=sys.stderr)

    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build adverse fill classification dataset")
    ap.add_argument("--root", default="hbot/data/bot1/logs/epp_v24/bot1_a")
    ap.add_argument("--output", default="hbot/data/ml")
    args = ap.parse_args()

    root = Path(args.root)
    out_path = build_dataset(root / "fills.csv", root / "minute.csv", Path(args.output))
    print(str(out_path))
