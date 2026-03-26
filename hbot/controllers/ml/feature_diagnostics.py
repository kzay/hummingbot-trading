"""Feature quality diagnostics for the ML pipeline.

Provides tooling for:
- Correlation analysis (grouped by feature category)
- Feature drift detection (train vs recent distribution shift)
- Missing / stale data detection
- Feature importance summary

All functions are pure — they accept DataFrames and return dicts or DataFrames.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Feature group definitions for structured analysis
FEATURE_GROUPS: dict[str, list[str]] = {
    "returns": ["return_1m", "return_5m", "return_15m", "return_1h", "return_4h"],
    "atr": ["atr_1m", "atr_5m", "atr_15m", "atr_1h", "atr_4h"],
    "atr_ratios": ["atr_ratio_5m_1m", "atr_ratio_15m_1m", "atr_ratio_1h_1m"],
    "candle_structure": [
        "close_in_range_1m", "close_in_range_5m", "close_in_range_15m",
        "body_ratio_1m", "body_ratio_5m", "body_ratio_15m",
    ],
    "trend": [
        "trend_alignment_1m_1h", "trend_alignment_1m_5m", "trend_alignment_1m_15m",
        "bb_position_1m", "rsi_1m", "adx_1m",
    ],
    "williams_r": [
        "wr_1m_p14", "wr_1m_p50", "wr_5m_p14", "wr_5m_p50",
        "wr_15m_p14", "wr_15m_p50", "wr_1h_p14", "wr_1h_p50",
        "wr_divergence_1m_5m", "wr_divergence_1m_1h",
        "wr_extreme_1m",
    ],
    "volatility": [
        "realized_vol_15m", "realized_vol_1h", "realized_vol_4h",
        "parkinson_vol", "garman_klass_vol", "vol_of_vol",
        "atr_pctl_24h", "atr_pctl_7d", "range_expansion",
        "vol_regime_agreement",
    ],
    "vol_change": [
        "vol_change_ratio", "atr_acceleration", "momentum_exhaustion",
    ],
    "microstructure": [
        "cvd", "flow_imbalance", "large_trade_ratio",
        "trade_arrival_rate", "vwap_deviation",
    ],
    "sentiment": [
        "funding_rate", "funding_momentum", "funding_rate_zscore",
        "ls_ratio", "ls_ratio_momentum",
        "basis", "basis_momentum", "basis_zscore",
    ],
    "temporal": [
        "hour_sin", "hour_cos", "day_sin", "day_cos",
        "session_flag", "minutes_since_funding",
    ],
}


def compute_correlation_report(
    features: pd.DataFrame,
    threshold: float = 0.85,
) -> dict[str, Any]:
    """Find highly correlated feature pairs.

    Returns dict with:
    - ``high_correlation_pairs``: list of (feat_a, feat_b, corr) where |corr| >= threshold
    - ``group_correlations``: per-group mean within-group correlation
    """
    # Only numeric columns, drop timestamp
    numeric_cols = [c for c in features.columns if c != "timestamp_ms"]
    corr = features[numeric_cols].corr()

    # Find pairs above threshold
    pairs: list[tuple[str, str, float]] = []
    seen: set[tuple[str, str]] = set()
    for i, col_a in enumerate(numeric_cols):
        for j, col_b in enumerate(numeric_cols):
            if i >= j:
                continue
            r = corr.iloc[i, j]
            if abs(r) >= threshold and not np.isnan(r):
                pair = (col_a, col_b)
                if pair not in seen:
                    pairs.append((col_a, col_b, round(float(r), 4)))
                    seen.add(pair)

    pairs.sort(key=lambda x: abs(x[2]), reverse=True)

    # Per-group within-group mean correlation
    group_corrs: dict[str, float] = {}
    for group_name, group_cols in FEATURE_GROUPS.items():
        present = [c for c in group_cols if c in numeric_cols]
        if len(present) < 2:
            continue
        sub_corr = features[present].corr()
        # Mean of upper triangle (excluding diagonal)
        mask = np.triu(np.ones_like(sub_corr, dtype=bool), k=1)
        vals = sub_corr.values[mask]
        vals = vals[~np.isnan(vals)]
        if len(vals) > 0:
            group_corrs[group_name] = round(float(np.mean(np.abs(vals))), 4)

    return {
        "high_correlation_pairs": pairs,
        "group_correlations": group_corrs,
        "threshold": threshold,
        "n_features": len(numeric_cols),
    }


def compute_drift_report(
    train_features: pd.DataFrame,
    recent_features: pd.DataFrame,
    psi_threshold: float = 0.2,
) -> dict[str, Any]:
    """Detect feature distribution drift between train and recent data.

    Uses Population Stability Index (PSI) as the drift metric.
    PSI > 0.1 = some shift, PSI > 0.2 = significant shift.

    Returns dict with per-feature PSI values and flagged features.
    """
    numeric_cols = [
        c for c in train_features.columns
        if c != "timestamp_ms" and c in recent_features.columns
    ]

    drift: dict[str, float] = {}
    flagged: list[str] = []

    for col in numeric_cols:
        train_vals = train_features[col].dropna().values
        recent_vals = recent_features[col].dropna().values
        if len(train_vals) < 20 or len(recent_vals) < 20:
            continue

        psi = _compute_psi(train_vals, recent_vals)
        drift[col] = round(psi, 4)
        if psi >= psi_threshold:
            flagged.append(col)

    return {
        "psi_per_feature": drift,
        "flagged_features": sorted(flagged),
        "psi_threshold": psi_threshold,
        "n_evaluated": len(drift),
    }


def compute_missing_report(features: pd.DataFrame) -> dict[str, Any]:
    """Report missing / NaN data per feature.

    Returns dict with:
    - ``missing_pct``: per-feature missing percentage
    - ``all_nan_features``: features that are entirely NaN
    - ``high_missing_features``: features with >50% NaN
    """
    n = len(features)
    numeric_cols = [c for c in features.columns if c != "timestamp_ms"]

    missing_pct: dict[str, float] = {}
    all_nan: list[str] = []
    high_missing: list[str] = []

    for col in numeric_cols:
        nan_count = int(features[col].isna().sum())
        pct = round(nan_count / n * 100, 2) if n > 0 else 0.0
        missing_pct[col] = pct
        if pct >= 99.9:
            all_nan.append(col)
        elif pct >= 50.0:
            high_missing.append(col)

    return {
        "missing_pct": missing_pct,
        "all_nan_features": sorted(all_nan),
        "high_missing_features": sorted(high_missing),
        "n_features": len(numeric_cols),
        "n_rows": n,
    }


def feature_group_importance(
    feature_importances: dict[str, float],
) -> dict[str, float]:
    """Aggregate feature importances by group.

    Returns dict mapping group name → sum of member importances.
    """
    group_sums: dict[str, float] = {}
    for group_name, group_cols in FEATURE_GROUPS.items():
        total = sum(feature_importances.get(c, 0.0) for c in group_cols)
        if total > 0:
            group_sums[group_name] = round(total, 4)
    return dict(sorted(group_sums.items(), key=lambda x: x[1], reverse=True))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_psi(
    expected: np.ndarray,
    actual: np.ndarray,
    n_bins: int = 10,
) -> float:
    """Population Stability Index between two distributions."""
    # Use expected percentiles as bin boundaries for consistent binning
    breakpoints = np.percentile(expected, np.linspace(0, 100, n_bins + 1))
    breakpoints[0] = -np.inf
    breakpoints[-1] = np.inf
    # Remove duplicate breakpoints
    breakpoints = np.unique(breakpoints)

    expected_counts = np.histogram(expected, bins=breakpoints)[0]
    actual_counts = np.histogram(actual, bins=breakpoints)[0]

    # Normalize to proportions (add small epsilon to avoid log(0))
    eps = 1e-6
    expected_pct = (expected_counts + eps) / (expected_counts.sum() + eps * len(expected_counts))
    actual_pct = (actual_counts + eps) / (actual_counts.sum() + eps * len(actual_counts))

    psi = float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))
    return max(0.0, psi)


__all__ = [
    "FEATURE_GROUPS",
    "compute_correlation_report",
    "compute_drift_report",
    "compute_missing_report",
    "feature_group_importance",
]
