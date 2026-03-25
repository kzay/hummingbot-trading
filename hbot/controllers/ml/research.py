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
    "adverse": "adverse_label",
}

_CLASSIFICATION_TYPES = {"regime", "direction", "adverse"}

REGIME_LABEL_MAP: dict[int, str] = {
    0: "neutral_low_vol",
    1: "neutral_high_vol",
    2: "up",
    3: "down",
}

_LABEL_MAPS: dict[str, dict[int, str]] = {
    "regime": REGIME_LABEL_MAP,
    "direction": {0: "down", 1: "up"},
    "adverse": {0: "normal", 1: "adverse"},
}

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

_DEFAULT_LGB_PARAMS: dict[str, Any] = {
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

_MAX_LABEL_HORIZON_BARS = 60  # default for 1m data with 60-min max label


_LABEL_COLS = {
    "timestamp_ms", "adverse_label", "pnl_vs_mid_bps",
}


def _get_feature_cols(dataset: pd.DataFrame) -> list[str]:
    return [
        c for c in dataset.columns
        if c not in _LABEL_COLS
        and not c.startswith("fwd_")
        and not c.startswith("tradability_")
    ]


def purged_walk_forward_cv(
    dataset: pd.DataFrame,
    model_type: str,
    n_windows: int = 5,
    embargo_bars: int | None = None,
    purge: bool = True,
    lgb_params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Purged walk-forward CV with embargo gaps (de Prado-style).

    For each fold the training set is *expanding* ``[0 : train_end]`` and the
    test set is a fixed-size window after a mandatory embargo gap.  When
    ``purge=True`` any training sample whose forward-label window overlaps the
    test period start is removed.

    Parameters
    ----------
    dataset:
        DataFrame with ``timestamp_ms``, feature columns and label columns.
    model_type:
        One of the keys in ``_MODEL_TYPE_TARGETS``.
    n_windows:
        Number of CV folds.
    embargo_bars:
        Rows to skip between train-end and test-start.  Defaults to
        ``2 * _MAX_LABEL_HORIZON_BARS``.
    purge:
        If *True*, remove training rows whose label window would leak into
        the test period.
    lgb_params:
        LightGBM hyperparameters.  Falls back to ``_DEFAULT_LGB_PARAMS``.

    Returns
    -------
    list[dict]
        Per-fold results including metrics, feature importances, fold sizes,
        embargo/purge details, and the fitted model.
    """
    import lightgbm as lgb

    target_col = _MODEL_TYPE_TARGETS.get(model_type)
    if target_col is None:
        raise ValueError(f"Unknown model_type: {model_type}")

    is_classification = model_type in _CLASSIFICATION_TYPES
    feature_cols = _get_feature_cols(dataset)

    clean = dataset.dropna(subset=[target_col]).reset_index(drop=True)
    n = len(clean)

    if embargo_bars is None:
        embargo_bars = 2 * _MAX_LABEL_HORIZON_BARS

    min_rows_needed = (n_windows + 1) * 50 + n_windows * embargo_bars
    if n < min_rows_needed:
        raise ValueError(
            f"Insufficient data for purged CV: {n} rows, need >= {min_rows_needed} "
            f"({n_windows} windows + embargo={embargo_bars})"
        )

    usable = n - n_windows * embargo_bars
    window_size = usable // (n_windows + 1)

    params = dict(_DEFAULT_LGB_PARAMS)
    if lgb_params:
        params.update(lgb_params)

    results: list[dict[str, Any]] = []

    for w in range(n_windows):
        train_end = window_size * (w + 1)
        test_start = train_end + embargo_bars
        test_end = min(test_start + window_size, n)

        if test_start >= n or test_end - test_start < 10:
            continue

        train_idx = np.arange(0, train_end)

        purged_count = 0
        if purge and _MAX_LABEL_HORIZON_BARS > 0:
            purge_boundary = test_start - _MAX_LABEL_HORIZON_BARS
            if purge_boundary < train_end:
                purge_mask = train_idx >= purge_boundary
                purged_count = int(purge_mask.sum())
                train_idx = train_idx[~purge_mask]

        train = clean.iloc[train_idx]
        test = clean.iloc[test_start:test_end]

        if len(train) < 50 or len(test) < 10:
            continue

        X_train = train[feature_cols].values
        y_train = train[target_col].values
        X_test = test[feature_cols].values
        y_test = test[target_col].values

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
            "embargo_bars": embargo_bars,
            "purged_count": purged_count,
            "metric_name": metric_name,
            "metric_value": metric_value,
            "top_10_features": top_10,
            "feature_importances": importances,
            "model": model,
        })
        logger.info(
            "Window %d: %s=%.4f (train=%d, test=%d, embargo=%d, purged=%d)",
            w, metric_name, metric_value,
            len(train), len(test), embargo_bars, purged_count,
        )

    return results


def walk_forward_cv(
    dataset: pd.DataFrame,
    model_type: str,
    n_windows: int = 5,
) -> list[dict[str, Any]]:
    """Legacy unpurged walk-forward CV.  Delegates to purged variant."""
    return purged_walk_forward_cv(
        dataset, model_type, n_windows=n_windows,
        embargo_bars=0, purge=False,
    )


# ---------------------------------------------------------------------------
# Hyperparameter tuning (Optuna)
# ---------------------------------------------------------------------------

_SEARCH_SPACES: dict[str, dict[str, tuple]] = {
    "regime": {
        "n_estimators": (100, 500),
        "learning_rate": (0.01, 0.15),
        "max_depth": (3, 10),
        "num_leaves": (15, 63),
        "min_child_samples": (10, 50),
        "subsample": (0.6, 1.0),
        "colsample_bytree": (0.5, 1.0),
    },
    "direction": {
        "n_estimators": (100, 500),
        "learning_rate": (0.01, 0.15),
        "max_depth": (3, 10),
        "num_leaves": (15, 63),
        "min_child_samples": (10, 50),
        "subsample": (0.6, 1.0),
        "colsample_bytree": (0.5, 1.0),
    },
    "sizing": {
        "n_estimators": (100, 500),
        "learning_rate": (0.01, 0.15),
        "max_depth": (3, 10),
        "num_leaves": (15, 63),
        "min_child_samples": (10, 50),
        "subsample": (0.6, 1.0),
        "colsample_bytree": (0.5, 1.0),
    },
    "adverse": {
        "n_estimators": (50, 300),
        "learning_rate": (0.01, 0.15),
        "max_depth": (3, 8),
        "num_leaves": (15, 63),
        "min_child_samples": (20, 100),
        "subsample": (0.6, 1.0),
        "colsample_bytree": (0.5, 1.0),
    },
}


def run_hyperparameter_tuning(
    dataset: pd.DataFrame,
    model_type: str,
    n_windows: int = 5,
    embargo_bars: int | None = None,
    n_trials: int = 50,
    seed: int = 42,
) -> dict[str, Any]:
    """Run Optuna TPE search over LightGBM hyperparams.

    Returns dict with ``best_params``, ``best_score``, ``n_trials``,
    ``search_space``.

    Raises ``ImportError`` if ``optuna`` is not installed.
    """
    try:
        import optuna  # noqa: F811
    except ImportError:
        raise ImportError(
            "Optuna is required for hyperparameter tuning.  "
            "Install it with: pip install optuna"
        )

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    search_space = _SEARCH_SPACES.get(model_type, _SEARCH_SPACES["regime"])

    def objective(trial: "optuna.Trial") -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", *search_space["n_estimators"]),
            "learning_rate": trial.suggest_float("learning_rate", *search_space["learning_rate"], log=True),
            "max_depth": trial.suggest_int("max_depth", *search_space["max_depth"]),
            "num_leaves": trial.suggest_int("num_leaves", *search_space["num_leaves"]),
            "min_child_samples": trial.suggest_int("min_child_samples", *search_space["min_child_samples"]),
            "subsample": trial.suggest_float("subsample", *search_space["subsample"]),
            "colsample_bytree": trial.suggest_float("colsample_bytree", *search_space["colsample_bytree"]),
            "verbose": -1,
            "random_state": seed,
        }
        results = purged_walk_forward_cv(
            dataset, model_type, n_windows=n_windows,
            embargo_bars=embargo_bars, purge=True, lgb_params=params,
        )
        if not results:
            return 0.0
        return float(np.mean([r["metric_value"] for r in results]))

    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials)

    logger.info(
        "Optuna tuning complete: best_score=%.4f after %d trials",
        study.best_value, len(study.trials),
    )

    return {
        "best_params": study.best_params,
        "best_score": study.best_value,
        "n_trials": len(study.trials),
        "search_space": {k: list(v) for k, v in search_space.items()},
    }


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
    if model_type == "adverse":
        pass_min = mean_metric >= 0.60
        gates.append(f"OOS accuracy {mean_metric:.4f} >= 0.60 (adverse): {'PASS' if pass_min else 'FAIL'}")
    elif is_classification:
        pass_min = mean_metric >= 0.55
        gates.append(f"OOS accuracy {mean_metric:.4f} >= 0.55: {'PASS' if pass_min else 'FAIL'}")
    else:
        pass_min = mean_metric > 0.0
        gates.append(f"OOS R² {mean_metric:.4f} > 0: {'PASS' if pass_min else 'FAIL'}")

    # Gate 2: Improvement over baseline
    if is_classification and baseline_metric > 0:
        improvement = mean_metric - baseline_metric
        min_improvement = 0.03 if model_type == "adverse" else 0.05
        pass_improvement = improvement >= min_improvement
        gates.append(
            f"Improvement {improvement:.4f} >= {min_improvement}: {'PASS' if pass_improvement else 'FAIL'}"
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
# Feature importance tracking
# ---------------------------------------------------------------------------

_TOP_K_FEATURES = 15


def compute_feature_importance_summary(
    cv_results: list[dict[str, Any]],
    top_k: int = _TOP_K_FEATURES,
) -> dict[str, Any]:
    """Aggregate per-fold importances into a compact summary.

    Returns dict with ``top_features``, ``stability`` scores, and
    ``aggregate_importances``.
    """
    all_importances: list[dict[str, float]] = [
        r["feature_importances"] for r in cv_results
        if r.get("feature_importances")
    ]
    if not all_importances:
        return {"top_features": [], "stability": {}, "aggregate_importances": {}}

    all_features: set[str] = set()
    for imp in all_importances:
        all_features |= imp.keys()

    n_folds = len(all_importances)
    aggregate: dict[str, float] = {}
    for feat in all_features:
        aggregate[feat] = float(np.mean([
            imp.get(feat, 0.0) for imp in all_importances
        ]))

    top_features = sorted(aggregate, key=aggregate.get, reverse=True)[:top_k]

    stability: dict[str, float] = {}
    for feat in all_features:
        fold_top_k_sets = []
        for imp in all_importances:
            fold_sorted = sorted(imp, key=imp.get, reverse=True)[:top_k]
            fold_top_k_sets.append(set(fold_sorted))
        appearances = sum(1 for s in fold_top_k_sets if feat in s)
        stability[feat] = round(appearances / n_folds, 3)

    return {
        "top_features": top_features,
        "stability": {f: stability.get(f, 0.0) for f in top_features},
        "aggregate_importances": {f: round(aggregate[f], 4) for f in top_features},
    }


def write_feature_importance_report(
    cv_results: list[dict[str, Any]],
    output_path: Path,
) -> Path:
    """Write a detailed fold-level feature importance report as JSON.

    Returns the path of the written report.
    """
    report: list[dict[str, Any]] = []
    for r in cv_results:
        if not r.get("feature_importances"):
            continue
        sorted_feats = sorted(
            r["feature_importances"].items(), key=lambda x: x[1], reverse=True,
        )
        report.append({
            "window": r["window"],
            "metric_name": r.get("metric_name"),
            "metric_value": r.get("metric_value"),
            "top_features": [
                {"feature": f, "importance": round(v, 4)} for f, v in sorted_feats[:20]
            ],
            "all_importances": {f: round(v, 4) for f, v in sorted_feats},
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2))
    logger.info("Feature importance report written to %s", output_path)
    return output_path


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
    embargo_bars: int | None = None,
    purge: bool = True,
    tune: bool = False,
    n_trials: int = 50,
    seed: int = 42,
    dataset_path: str | Path | None = None,
) -> dict[str, Any]:
    """End-to-end: assemble, CV, baseline, gate check, save.

    When ``tune=True``, runs Optuna hyperparameter search first, then
    final CV with the best parameters.  Returns the metadata dict.

    If *dataset_path* is provided, load from that parquet directly
    instead of assembling from raw candle data.  Useful for model types
    whose labels require non-candle data (e.g. adverse fills).
    """
    if dataset_path is not None:
        dataset = pd.read_parquet(dataset_path)
        logger.info("Loaded pre-built dataset from %s: %d rows", dataset_path, len(dataset))
    else:
        dataset = assemble_dataset(exchange, pair, catalog_dir)

    tuning_result: dict[str, Any] | None = None
    lgb_params: dict[str, Any] | None = None

    if tune:
        tuning_result = run_hyperparameter_tuning(
            dataset, model_type, n_windows=n_windows,
            embargo_bars=embargo_bars, n_trials=n_trials, seed=seed,
        )
        lgb_params = {**tuning_result["best_params"], "verbose": -1, "random_state": seed}

    cv_results = purged_walk_forward_cv(
        dataset, model_type, n_windows=n_windows,
        embargo_bars=embargo_bars, purge=purge, lgb_params=lgb_params,
    )

    if not cv_results:
        raise RuntimeError("No CV windows completed")

    baseline_metric = compute_baseline(dataset, model_type)
    deployment_ready, gate_results = check_deployment_gates(
        cv_results, baseline_metric, model_type,
    )

    target_col = _MODEL_TYPE_TARGETS[model_type]
    feature_cols = _get_feature_cols(dataset)

    # Use the last window's model as the final model
    final_model = cv_results[-1]["model"]

    metrics = [r["metric_value"] for r in cv_results]
    fold_embargo = cv_results[0].get("embargo_bars", 0) if cv_results else 0
    fold_purged_total = sum(r.get("purged_count", 0) for r in cv_results)

    metadata: dict[str, Any] = {
        "exchange": exchange,
        "pair": pair,
        "model_type": model_type,
        "feature_columns": feature_cols,
        "label_column": target_col,
        "walk_forward_results": [
            {k: v for k, v in r.items() if k not in ("model", "feature_importances")}
            for r in cv_results
        ],
        "cv_config": {
            "embargo_bars": fold_embargo,
            "purge": purge,
            "n_windows": n_windows,
            "purged_samples_total": fold_purged_total,
        },
        "mean_oos_metric": float(np.mean(metrics)),
        "baseline_metric": baseline_metric,
        "deployment_ready": deployment_ready,
        "gate_results": gate_results,
        "training_date": datetime.now(UTC).isoformat(),
        "data_start": str(dataset["timestamp_ms"].min()) if "timestamp_ms" in dataset.columns else "N/A",
        "data_end": str(dataset["timestamp_ms"].max()) if "timestamp_ms" in dataset.columns else "N/A",
        "dataset_rows": len(dataset),
        "label_mapping": _LABEL_MAPS.get(model_type, {}),
    }

    if tuning_result is not None:
        metadata["tuning"] = {
            "best_params": tuning_result["best_params"],
            "best_score": tuning_result["best_score"],
            "n_trials": tuning_result["n_trials"],
            "search_space": tuning_result["search_space"],
        }

    fi_summary = compute_feature_importance_summary(cv_results)
    metadata["feature_importance"] = fi_summary

    out_dir = Path(output_dir)
    report_path = out_dir / exchange / pair / f"{model_type}_feature_importance_report.json"
    write_feature_importance_report(cv_results, report_path)
    metadata["feature_importance_report"] = str(report_path)

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
    parser.add_argument("--embargo-bars", type=int, default=None)
    parser.add_argument("--no-purge", action="store_true")
    parser.add_argument("--tune", action="store_true", help="Run Optuna hyperparameter tuning before final training")
    parser.add_argument("--n-trials", type=int, default=50, help="Number of Optuna trials (default 50)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--dataset", default=None, help="Pre-built parquet path (bypasses assemble_dataset)")
    args = parser.parse_args()

    metadata = train_and_evaluate(
        exchange=args.exchange,
        pair=args.pair,
        model_type=args.model_type,
        catalog_dir=args.catalog_dir,
        output_dir=args.output,
        n_windows=args.windows,
        embargo_bars=args.embargo_bars,
        purge=not args.no_purge,
        tune=args.tune,
        n_trials=args.n_trials,
        seed=args.seed,
        dataset_path=args.dataset,
    )
    print(json.dumps(metadata, indent=2, default=str))


if __name__ == "__main__":
    main()
