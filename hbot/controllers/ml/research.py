"""Offline ML research pipeline: dataset assembly, walk-forward CV, training.

Usage::

    python -m controllers.ml.research \\
        --exchange bitget --pair BTC-USDT \\
        --model-type regime --output data/ml/models
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from controllers.ml import model_registry
from controllers.ml.feature_pipeline import compute_features
from controllers.ml.label_generator import compute_labels

logger = logging.getLogger(__name__)

_MODEL_TYPE_TARGETS = {
    "regime": "fwd_vol_bucket_15m",
    "direction": "fwd_return_sign_15m",
    "sizing": "tradability_long_15m",
}

_CLASSIFICATION_TYPES = {"regime", "direction"}

# ---------------------------------------------------------------------------
# Dataset assembly
# ---------------------------------------------------------------------------


def assemble_dataset(
    exchange: str,
    pair: str,
    catalog_dir: str | Path,
) -> pd.DataFrame:
    """Load all available data for (exchange, pair), compute features + labels.

    Returns a single DataFrame with timestamp_ms, feature columns, and label
    columns joined on timestamp_ms.
    """
    from controllers.backtesting.data_catalog import DataCatalog
    from controllers.backtesting.data_store import (
        load_candles_df,
        load_funding_rates,
        load_long_short_ratio,
        resolve_data_path,
    )

    catalog_dir = Path(catalog_dir)
    catalog = DataCatalog(base_dir=catalog_dir)

    def _load_opt(resolution: str) -> pd.DataFrame | None:
        entry = catalog.find(exchange, pair, resolution)
        if entry is None:
            return None
        path = resolve_data_path(exchange, pair, resolution, catalog_dir)
        if not path.exists():
            return None
        return load_candles_df(path)

    candles_1m = _load_opt("1m")
    if candles_1m is None or candles_1m.empty:
        raise FileNotFoundError(f"No 1m candle data for {exchange}/{pair}")

    candles_5m = _load_opt("5m")
    candles_15m = _load_opt("15m")
    candles_1h = _load_opt("1h")
    mark_1m = _load_opt("mark_1m")
    index_1m = _load_opt("index_1m")

    # Funding
    funding_df = None
    funding_entry = catalog.find(exchange, pair, "funding")
    if funding_entry:
        funding_path = resolve_data_path(exchange, pair, "funding", catalog_dir)
        if funding_path.exists():
            rows = load_funding_rates(funding_path)
            funding_df = pd.DataFrame([
                {"timestamp_ms": r.timestamp_ms, "rate": float(r.rate)}
                for r in rows
            ])

    # LS ratio
    ls_df = None
    ls_entry = catalog.find(exchange, pair, "ls_ratio")
    if ls_entry:
        ls_path = resolve_data_path(exchange, pair, "ls_ratio", catalog_dir)
        if ls_path.exists():
            rows = load_long_short_ratio(ls_path)
            ls_df = pd.DataFrame([
                {
                    "timestamp_ms": r.timestamp_ms,
                    "long_account_ratio": r.long_account_ratio,
                    "short_account_ratio": r.short_account_ratio,
                    "long_short_ratio": r.long_short_ratio,
                }
                for r in rows
            ])

    logger.info(
        "Assembling dataset for %s/%s: 1m=%d rows, 5m=%s, 15m=%s, 1h=%s, "
        "mark=%s, index=%s, funding=%s, ls=%s",
        exchange, pair, len(candles_1m),
        len(candles_5m) if candles_5m is not None else "N/A",
        len(candles_15m) if candles_15m is not None else "N/A",
        len(candles_1h) if candles_1h is not None else "N/A",
        len(mark_1m) if mark_1m is not None else "N/A",
        len(index_1m) if index_1m is not None else "N/A",
        len(funding_df) if funding_df is not None else "N/A",
        len(ls_df) if ls_df is not None else "N/A",
    )

    features = compute_features(
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        candles_15m=candles_15m,
        candles_1h=candles_1h,
        funding=funding_df,
        ls_ratio=ls_df,
        mark_candles_1m=mark_1m,
        index_candles_1m=index_1m,
    )

    labels = compute_labels(candles_1m)

    dataset = features.merge(labels, on="timestamp_ms", how="inner")
    logger.info("Assembled dataset: %d rows, %d columns", len(dataset), len(dataset.columns))
    return dataset


# ---------------------------------------------------------------------------
# Walk-forward cross-validation
# ---------------------------------------------------------------------------


def walk_forward_cv(
    dataset: pd.DataFrame,
    model_type: str,
    n_windows: int = 5,
) -> list[dict[str, Any]]:
    """Run temporal walk-forward CV with LightGBM.

    Returns per-window results with OOS metrics and feature importances.
    """
    import lightgbm as lgb

    target_col = _MODEL_TYPE_TARGETS.get(model_type)
    if target_col is None:
        raise ValueError(f"Unknown model_type: {model_type}")

    is_classification = model_type in _CLASSIFICATION_TYPES

    feature_cols = [
        c for c in dataset.columns
        if c != "timestamp_ms" and not c.startswith("fwd_") and not c.startswith("tradability_")
    ]

    # Only require target to be non-NaN; LightGBM handles NaN features natively
    clean = dataset.dropna(subset=[target_col]).reset_index(drop=True)
    n = len(clean)
    if n < 1000:
        raise ValueError(f"Insufficient data for CV: {n} rows (need >= 1000)")

    window_size = n // (n_windows + 1)
    results = []

    for w in range(n_windows):
        train_end = window_size * (w + 1)
        test_end = min(train_end + window_size, n)
        train = clean.iloc[:train_end]
        test = clean.iloc[train_end:test_end]

        if len(test) < 10:
            continue

        X_train = train[feature_cols].values
        y_train = train[target_col].values
        X_test = test[feature_cols].values
        y_test = test[target_col].values

        params: dict[str, Any] = {
            "n_estimators": 200,
            "learning_rate": 0.05,
            "max_depth": 6,
            "num_leaves": 31,
            "min_child_samples": 20,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "verbose": -1,
            "random_state": 42,
        }

        if is_classification:
            y_train_int = y_train.astype(int)
            y_test_int = y_test.astype(int)
            model = lgb.LGBMClassifier(**params)
            model.fit(X_train, y_train_int)
            preds = model.predict(X_test)
            accuracy = float(np.mean(preds == y_test_int))
            metric_name = "accuracy"
            metric_value = accuracy
        else:
            model = lgb.LGBMRegressor(**params)
            model.fit(X_train, y_train)
            preds = model.predict(X_test)
            ss_res = np.sum((y_test - preds) ** 2)
            ss_tot = np.sum((y_test - np.mean(y_test)) ** 2)
            r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
            metric_name = "r_squared"
            metric_value = float(r2)

        importances = dict(zip(feature_cols, model.feature_importances_.tolist(), strict=True))
        top_10 = sorted(importances, key=importances.get, reverse=True)[:10]

        results.append({
            "window": w,
            "train_rows": len(train),
            "test_rows": len(test),
            "metric_name": metric_name,
            "metric_value": metric_value,
            "top_10_features": top_10,
            "model": model,
        })
        logger.info(
            "Window %d: %s=%.4f (train=%d, test=%d)",
            w, metric_name, metric_value, len(train), len(test),
        )

    return results


# ---------------------------------------------------------------------------
# Baseline comparison
# ---------------------------------------------------------------------------


def compute_baseline(
    dataset: pd.DataFrame,
    model_type: str,
) -> float:
    """Compute rule-based RegimeDetector baseline on the same labels.

    Returns baseline accuracy for classification, or 0 for regression.
    """
    if model_type not in _CLASSIFICATION_TYPES:
        return 0.0

    target_col = _MODEL_TYPE_TARGETS[model_type]
    clean = dataset.dropna(subset=[target_col]).reset_index(drop=True)

    if model_type == "regime":
        most_common = clean[target_col].mode()
        if len(most_common) == 0:
            return 0.0
        baseline_acc = float((clean[target_col] == most_common.iloc[0]).mean())
        logger.info("Baseline accuracy (majority class): %.4f", baseline_acc)
        return baseline_acc

    return 0.0


# ---------------------------------------------------------------------------
# Deployment gates
# ---------------------------------------------------------------------------


def check_deployment_gates(
    cv_results: list[dict[str, Any]],
    baseline_metric: float,
    model_type: str,
) -> tuple[bool, list[str]]:
    """Check if a model passes deployment gates.

    Returns (deployment_ready, list of gate results).
    """
    is_classification = model_type in _CLASSIFICATION_TYPES
    metrics = [r["metric_value"] for r in cv_results]
    mean_metric = float(np.mean(metrics))
    gates: list[str] = []

    # Gate 1: Minimum OOS performance
    if is_classification:
        pass_min = mean_metric >= 0.55
        gates.append(f"OOS accuracy {mean_metric:.4f} >= 0.55: {'PASS' if pass_min else 'FAIL'}")
    else:
        pass_min = mean_metric > 0.0
        gates.append(f"OOS R² {mean_metric:.4f} > 0: {'PASS' if pass_min else 'FAIL'}")

    # Gate 2: Improvement over baseline
    if is_classification and baseline_metric > 0:
        improvement = mean_metric - baseline_metric
        pass_improvement = improvement >= 0.05
        gates.append(
            f"Improvement {improvement:.4f} >= 0.05: {'PASS' if pass_improvement else 'FAIL'}"
        )
    else:
        pass_improvement = True

    # Gate 3: Feature importance stability
    all_top_10 = [set(r["top_10_features"]) for r in cv_results]
    if all_top_10:
        all_features = set()
        for s in all_top_10:
            all_features |= s
        stability_count = 0
        for feat in all_features:
            appearances = sum(1 for s in all_top_10 if feat in s)
            if appearances / len(all_top_10) >= 0.6:
                stability_count += 1
        pass_stability = stability_count >= 5
        gates.append(
            f"Feature stability ({stability_count} features in 60%+ windows): "
            f"{'PASS' if pass_stability else 'FAIL'}"
        )
    else:
        pass_stability = False

    deployment_ready = pass_min and pass_improvement and pass_stability
    return deployment_ready, gates


# ---------------------------------------------------------------------------
# Full training pipeline
# ---------------------------------------------------------------------------


def train_and_evaluate(
    exchange: str,
    pair: str,
    model_type: str,
    catalog_dir: str | Path,
    output_dir: str | Path,
    n_windows: int = 5,
) -> dict[str, Any]:
    """End-to-end: assemble, CV, baseline, gate check, save.

    Returns the metadata dict.
    """
    dataset = assemble_dataset(exchange, pair, catalog_dir)
    cv_results = walk_forward_cv(dataset, model_type, n_windows)

    if not cv_results:
        raise RuntimeError("No CV windows completed")

    baseline_metric = compute_baseline(dataset, model_type)
    deployment_ready, gate_results = check_deployment_gates(
        cv_results, baseline_metric, model_type,
    )

    target_col = _MODEL_TYPE_TARGETS[model_type]
    feature_cols = [
        c for c in dataset.columns
        if c != "timestamp_ms" and not c.startswith("fwd_") and not c.startswith("tradability_")
    ]

    # Use the last window's model as the final model
    final_model = cv_results[-1]["model"]

    metrics = [r["metric_value"] for r in cv_results]
    metadata = {
        "exchange": exchange,
        "pair": pair,
        "model_type": model_type,
        "feature_columns": feature_cols,
        "label_column": target_col,
        "walk_forward_results": [
            {k: v for k, v in r.items() if k != "model"}
            for r in cv_results
        ],
        "mean_oos_metric": float(np.mean(metrics)),
        "baseline_metric": baseline_metric,
        "deployment_ready": deployment_ready,
        "gate_results": gate_results,
        "training_date": datetime.now(UTC).isoformat(),
        "data_start": str(dataset["timestamp_ms"].min()),
        "data_end": str(dataset["timestamp_ms"].max()),
        "dataset_rows": len(dataset),
    }

    model_registry.save_model(
        final_model, metadata,
        base_dir=output_dir, exchange=exchange, pair=pair, model_type=model_type,
    )

    logger.info(
        "Training complete: %s/%s/%s — deployment_ready=%s, mean_metric=%.4f",
        exchange, pair, model_type, deployment_ready, np.mean(metrics),
    )
    for gate in gate_results:
        logger.info("  Gate: %s", gate)

    return metadata


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="ML research pipeline: train and evaluate models")
    parser.add_argument("--exchange", required=True)
    parser.add_argument("--pair", required=True)
    parser.add_argument("--model-type", required=True, choices=list(_MODEL_TYPE_TARGETS))
    parser.add_argument("--catalog-dir", default="data/historical")
    parser.add_argument("--output", default="data/ml/models")
    parser.add_argument("--windows", type=int, default=5)
    args = parser.parse_args()

    metadata = train_and_evaluate(
        exchange=args.exchange,
        pair=args.pair,
        model_type=args.model_type,
        catalog_dir=args.catalog_dir,
        output_dir=args.output,
        n_windows=args.windows,
    )
    print(json.dumps(metadata, indent=2, default=str))


if __name__ == "__main__":
    main()
