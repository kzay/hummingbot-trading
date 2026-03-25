"""Build training dataset for the ML regime classifier (ROAD-10).

Reads minute.csv (and legacy files) from bot log dirs, extracts feature columns
+ regime label, adds lag features, and outputs a Parquet file ready for
train_regime_classifier.py.

Supports combining multiple bots via ``--roots`` for larger datasets.

Requirements:
    pip install pandas pyarrow

Usage:
    PYTHONPATH=hbot python -m scripts.ml.build_regime_dataset --root data/bot1/logs/epp_v24/bot1_a
    PYTHONPATH=hbot python -m scripts.ml.build_regime_dataset --roots data/bot5/logs/epp_v24/bot5_a,data/bot6/logs/epp_v24/bot6_a,data/bot7/logs/epp_v24/bot7_a

Gate: Run after collecting >= 10,000 minute.csv rows (~7 days of 1-minute bars).
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

REGIME_LABELS = ["neutral_low_vol", "neutral_high_vol", "up", "down", "high_vol_shock"]
REGIME_TO_INT = {r: i for i, r in enumerate(REGIME_LABELS)}

FEATURE_COLUMNS = [
    "mid",
    "equity_quote",
    "base_pct",
    "target_base_pct",
    "spread_pct",
    "net_edge_pct",
    "turnover_today_x",
    "adverse_drift_30s",
    "spread_floor_pct",
    "funding_rate",
    "ob_imbalance",
    "fill_edge_ewma_bps",
    "drawdown_pct",
    "daily_loss_pct",
]

LAG_STEPS = [1, 2, 5]


def _safe_float(x, default: float = 0.0) -> float:
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return default


def _parse_ts(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def load_minute_csv(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        print(f"ERROR: minute.csv not found at {path}", file=sys.stderr)
        return rows
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = _parse_ts(row.get("ts", ""))
            regime = str(row.get("regime", "")).strip()
            if ts is None or not regime or regime not in REGIME_TO_INT:
                continue
            rows.append({"_ts": ts, "_regime": regime, **row})
    return rows


def build_features_from_row(row: dict) -> dict[str, float]:
    feats: dict[str, float] = {}
    for col in FEATURE_COLUMNS:
        feats[col] = _safe_float(row.get(col, 0))

    ts = row.get("_ts")
    if ts is not None and isinstance(ts, datetime):
        import math
        hour = ts.hour
        feats["time_sin"] = math.sin(2 * math.pi * hour / 24.0)
        feats["time_cos"] = math.cos(2 * math.pi * hour / 24.0)

    mid = feats.get("mid", 1.0) or 1.0
    eq = feats.get("equity_quote", 1.0) or 1.0
    feats["inv_gap"] = feats.get("target_base_pct", 0) - feats.get("base_pct", 0)
    feats["spread_x_band"] = feats.get("spread_pct", 0) * feats.get("spread_floor_pct", 0)
    feats["abs_inv_gap"] = abs(feats["inv_gap"])
    feats["pnl_vs_open"] = _safe_float(row.get("pnl_quote", 0)) / max(0.01, eq)

    return feats


def add_lag_features(rows: list[dict], feature_rows: list[dict[str, float]]) -> list[dict[str, float]]:
    """Add lag features for mid price returns at t-1, t-2, t-5."""
    n = len(feature_rows)
    result: list[dict[str, float]] = []
    for i in range(n):
        row = dict(feature_rows[i])
        mid_now = row.get("mid", 0)
        for lag in LAG_STEPS:
            if i >= lag:
                mid_lag = feature_rows[i - lag].get("mid", mid_now) or mid_now
                ret = (mid_now - mid_lag) / max(0.01, mid_lag)
            else:
                ret = 0.0
            row[f"mid_return_lag{lag}"] = ret
        result.append(row)
    return result


def _collect_minute_csvs(root: Path) -> list[Path]:
    """Find all minute.csv and minute.legacy_*.csv files under *root*."""
    found: list[Path] = []
    for p in sorted(root.rglob("minute*.csv")):
        if p.name == "minute.csv" or p.name.startswith("minute.legacy_"):
            found.append(p)
    return found


def build_dataset(minute_paths: list[Path], output_dir: Path) -> Path:
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        print("ERROR: pandas and pyarrow required. Run: pip install pandas pyarrow", file=sys.stderr)
        sys.exit(1)

    rows: list[dict] = []
    for mp in minute_paths:
        chunk = load_minute_csv(mp)
        print(f"  {mp}: {len(chunk)} rows", file=sys.stderr)
        rows.extend(chunk)

    if not rows:
        print("ERROR: No valid rows found in any minute.csv", file=sys.stderr)
        sys.exit(1)

    rows.sort(key=lambda r: r["_ts"])
    print(f"Total rows after merge: {len(rows)}", file=sys.stderr)

    feature_rows = [build_features_from_row(r) for r in rows]
    feature_rows_with_lags = add_lag_features(rows, feature_rows)

    labels = [REGIME_TO_INT[r["_regime"]] for r in rows]
    regime_strs = [r["_regime"] for r in rows]
    timestamps = [r["_ts"].isoformat() if r.get("_ts") else "" for r in rows]

    df = pd.DataFrame(feature_rows_with_lags)
    df["regime_label"] = labels
    df["regime_str"] = regime_strs
    df["ts"] = timestamps

    pre_dedup = len(df)
    df.drop_duplicates(subset=["ts"], keep="first", inplace=True)
    dropped = pre_dedup - len(df)
    print(f"After dedup: {len(df)} rows (dropped {dropped} duplicate timestamps)", file=sys.stderr)
    if dropped > pre_dedup * 0.3:
        print(
            f"WARNING: {dropped}/{pre_dedup} rows dropped — bots have overlapping timestamps. "
            "Use --roots with bots that have non-overlapping time coverage for maximum data.",
            file=sys.stderr,
        )

    print(f"Feature columns: {list(df.columns)}", file=sys.stderr)
    print(f"Regime distribution:\n{pd.Series(df['regime_str']).value_counts().to_string()}", file=sys.stderr)

    output_dir.mkdir(parents=True, exist_ok=True)
    from datetime import date
    date_str = date.today().strftime("%Y%m%d")
    out_path = output_dir / f"regime_train_{date_str}.parquet"
    df.to_parquet(out_path, index=False)
    print(f"Saved {len(df)} rows to {out_path}", file=sys.stderr)

    print(f"\nGate check: {len(df)} rows (need >= 10,000 for reliable training)", file=sys.stderr)
    if len(df) < 10_000:
        print("WARNING: Insufficient data for training. Keep running paper bot and retry.", file=sys.stderr)

    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build ML regime classification dataset from minute.csv")
    ap.add_argument("--root", default=None, help="Single bot log dir (legacy)")
    ap.add_argument("--roots", default=None, help="Comma-separated bot log dirs for combined training")
    ap.add_argument("--output", default="data/ml")
    args = ap.parse_args()

    minute_paths: list[Path] = []
    if args.roots:
        for root_str in args.roots.split(","):
            root = Path(root_str.strip())
            found = _collect_minute_csvs(root)
            if found:
                minute_paths.extend(found)
            else:
                mp = root / "minute.csv"
                if mp.exists():
                    minute_paths.append(mp)
    elif args.root:
        root = Path(args.root)
        found = _collect_minute_csvs(root)
        if found:
            minute_paths.extend(found)
        else:
            minute_paths.append(root / "minute.csv")
    else:
        minute_paths.append(Path("data/bot1/logs/epp_v24/bot1_a/minute.csv"))

    print(f"Loading from {len(minute_paths)} files:", file=sys.stderr)
    output_dir = Path(args.output)
    out_path = build_dataset(minute_paths, output_dir)
    print(str(out_path))
