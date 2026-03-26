"""Regime model validation framework.

Answers key questions:
1. Is the regime model predictive?
2. Does it improve risk-adjusted returns?
3. Does it reduce drawdowns?
4. What are the transition probabilities between regimes?
5. How persistent are regime predictions?

All functions are pure — accept DataFrames, return dicts.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def per_regime_forward_returns(
    dataset: pd.DataFrame,
    regime_col: str,
    return_cols: tuple[str, ...] = ("fwd_return_5m", "fwd_return_15m", "fwd_return_60m"),
) -> dict[str, Any]:
    """Compute forward return statistics conditioned on predicted regime.

    This is the key test: do different regimes have meaningfully different
    forward return distributions?

    Returns per-regime: mean, std, sharpe, skew, median, count.
    """
    results: dict[str, Any] = {}

    for ret_col in return_cols:
        if ret_col not in dataset.columns:
            continue
        regime_stats: dict[str, dict[str, float]] = {}

        for regime_name, group in dataset.groupby(regime_col):
            returns = group[ret_col].dropna()
            if len(returns) < 10:
                continue
            mean_ret = float(returns.mean())
            std_ret = float(returns.std())
            regime_stats[str(regime_name)] = {
                "mean": round(mean_ret, 6),
                "std": round(std_ret, 6),
                "sharpe": round(mean_ret / std_ret, 4) if std_ret > 0 else 0.0,
                "skew": round(float(returns.skew()), 4),
                "median": round(float(returns.median()), 6),
                "count": int(len(returns)),
                "pct_positive": round(float((returns > 0).mean()), 4),
            }

        results[ret_col] = regime_stats

    return results


def per_regime_volatility_stats(
    dataset: pd.DataFrame,
    regime_col: str,
    vol_cols: tuple[str, ...] = ("fwd_vol_5m", "fwd_vol_15m", "fwd_vol_60m"),
) -> dict[str, Any]:
    """Compute forward volatility statistics conditioned on predicted regime.

    Validates that vol-based regimes actually separate volatility levels.
    """
    results: dict[str, Any] = {}

    for vol_col in vol_cols:
        if vol_col not in dataset.columns:
            continue
        regime_stats: dict[str, dict[str, float]] = {}
        for regime_name, group in dataset.groupby(regime_col):
            vols = group[vol_col].dropna()
            if len(vols) < 10:
                continue
            regime_stats[str(regime_name)] = {
                "mean": round(float(vols.mean()), 6),
                "median": round(float(vols.median()), 6),
                "p75": round(float(vols.quantile(0.75)), 6),
                "p95": round(float(vols.quantile(0.95)), 6),
                "count": int(len(vols)),
            }
        results[vol_col] = regime_stats

    return results


def regime_transition_matrix(
    predictions: pd.Series,
) -> dict[str, Any]:
    """Compute regime transition probability matrix.

    Returns:
    - ``matrix``: dict of dict — P(next_regime | current_regime)
    - ``persistence``: per-regime probability of staying in same regime
    - ``mean_persistence``: average across regimes
    """
    regimes = predictions.dropna()
    if len(regimes) < 2:
        return {"matrix": {}, "persistence": {}, "mean_persistence": 0.0}

    current = regimes.iloc[:-1].values
    next_regime = regimes.iloc[1:].values

    all_labels = sorted(set(current) | set(next_regime))
    counts: dict[str, dict[str, int]] = {r: {} for r in all_labels}

    for c, n in zip(current, next_regime, strict=True):
        counts[str(c)][str(n)] = counts[str(c)].get(str(n), 0) + 1

    matrix: dict[str, dict[str, float]] = {}
    persistence: dict[str, float] = {}
    for regime, transitions in counts.items():
        total = sum(transitions.values())
        if total > 0:
            matrix[regime] = {k: round(v / total, 4) for k, v in transitions.items()}
            persistence[regime] = round(transitions.get(regime, 0) / total, 4)
        else:
            matrix[regime] = {}
            persistence[regime] = 0.0

    mean_pers = float(np.mean(list(persistence.values()))) if persistence else 0.0

    return {
        "matrix": matrix,
        "persistence": persistence,
        "mean_persistence": round(mean_pers, 4),
    }


def regime_persistence_stats(
    predictions: pd.Series,
) -> dict[str, Any]:
    """Compute how long each regime tends to persist (run-length statistics).

    Returns per-regime: mean_duration, median_duration, max_duration (in bars).
    """
    regimes = predictions.dropna().values
    if len(regimes) == 0:
        return {}

    runs: dict[str, list[int]] = {}
    current = regimes[0]
    length = 1

    for i in range(1, len(regimes)):
        if regimes[i] == current:
            length += 1
        else:
            name = str(current)
            runs.setdefault(name, []).append(length)
            current = regimes[i]
            length = 1
    # Last run
    runs.setdefault(str(current), []).append(length)

    stats: dict[str, dict[str, float]] = {}
    for regime, lengths in runs.items():
        arr = np.array(lengths)
        stats[regime] = {
            "mean_duration": round(float(arr.mean()), 2),
            "median_duration": round(float(np.median(arr)), 2),
            "max_duration": int(arr.max()),
            "min_duration": int(arr.min()),
            "n_episodes": len(lengths),
        }

    return stats


def regime_class_distribution(
    dataset: pd.DataFrame,
    label_col: str,
) -> dict[str, Any]:
    """Report class distribution of regime labels.

    Returns per-class: count, percentage.
    """
    counts = dataset[label_col].value_counts().sort_index()
    total = int(counts.sum())
    distribution: dict[str, dict[str, Any]] = {}
    for cls_val, count in counts.items():
        distribution[str(cls_val)] = {
            "count": int(count),
            "pct": round(int(count) / total * 100, 2) if total > 0 else 0.0,
        }
    return {
        "distribution": distribution,
        "total": total,
        "n_classes": len(counts),
        "majority_class": str(counts.idxmax()) if len(counts) > 0 else None,
        "majority_pct": round(float(counts.max() / total * 100), 2) if total > 0 else 0.0,
    }


def ablation_feature_groups(
    dataset: pd.DataFrame,
    model_type: str,
    feature_groups: dict[str, list[str]],
    n_windows: int = 3,
) -> dict[str, Any]:
    """Run ablation tests: train with each feature group removed.

    Returns per-group: accuracy with group removed, accuracy delta vs full model.
    Useful for identifying which feature groups contribute most.
    """
    from controllers.ml.research import purged_walk_forward_cv

    # Full model baseline
    full_results = purged_walk_forward_cv(dataset, model_type, n_windows=n_windows)
    full_accuracy = float(np.mean([r["metric_value"] for r in full_results])) if full_results else 0.0

    ablation: dict[str, dict[str, float]] = {}

    for group_name, group_cols in feature_groups.items():
        # Create dataset without this group
        cols_to_drop = [c for c in group_cols if c in dataset.columns]
        if not cols_to_drop:
            continue

        reduced = dataset.drop(columns=cols_to_drop, errors="ignore")
        try:
            results = purged_walk_forward_cv(reduced, model_type, n_windows=n_windows)
            if results:
                reduced_accuracy = float(np.mean([r["metric_value"] for r in results]))
                delta = full_accuracy - reduced_accuracy
                ablation[group_name] = {
                    "accuracy_without": round(reduced_accuracy, 4),
                    "accuracy_delta": round(delta, 4),
                    "features_removed": len(cols_to_drop),
                    "contribution": "positive" if delta > 0.005 else (
                        "neutral" if delta > -0.005 else "negative"
                    ),
                }
            else:
                ablation[group_name] = {"error": "no CV windows completed"}
        except Exception as exc:
            ablation[group_name] = {"error": str(exc)}

    return {
        "full_accuracy": round(full_accuracy, 4),
        "ablation_results": ablation,
        "n_windows": n_windows,
    }


def calibration_analysis(
    probabilities: np.ndarray,
    true_labels: np.ndarray,
    n_bins: int = 10,
) -> dict[str, Any]:
    """Assess probability calibration of classifier predictions.

    For each confidence bin, computes the actual accuracy vs predicted confidence.
    Perfect calibration: predicted confidence == actual accuracy.

    Returns:
    - ``bins``: list of {bin_center, predicted_confidence, actual_accuracy, count}
    - ``ece``: Expected Calibration Error (lower is better)
    """
    # For multi-class: use max probability as confidence
    if probabilities.ndim == 2:
        confidences = probabilities.max(axis=1)
        predictions = probabilities.argmax(axis=1)
    else:
        confidences = probabilities
        predictions = (probabilities > 0.5).astype(int)

    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    bins: list[dict[str, Any]] = []
    ece = 0.0
    total = len(confidences)

    for i in range(n_bins):
        lo, hi = bin_boundaries[i], bin_boundaries[i + 1]
        mask = (confidences >= lo) & (confidences < hi)
        if i == n_bins - 1:
            mask = (confidences >= lo) & (confidences <= hi)

        count = int(mask.sum())
        if count == 0:
            continue

        bin_confidence = float(confidences[mask].mean())
        bin_accuracy = float((predictions[mask] == true_labels[mask]).mean())
        ece += abs(bin_accuracy - bin_confidence) * (count / total)

        bins.append({
            "bin_center": round((lo + hi) / 2, 2),
            "predicted_confidence": round(bin_confidence, 4),
            "actual_accuracy": round(bin_accuracy, 4),
            "count": count,
        })

    return {
        "bins": bins,
        "ece": round(ece, 4),
        "n_bins": n_bins,
        "n_samples": total,
    }


__all__ = [
    "ablation_feature_groups",
    "calibration_analysis",
    "per_regime_forward_returns",
    "per_regime_volatility_stats",
    "regime_class_distribution",
    "regime_persistence_stats",
    "regime_transition_matrix",
]
