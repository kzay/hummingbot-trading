"""Train ML regime classifier for EPP v2.4 (ROAD-10).

Walk-forward cross-validation on regime_train_*.parquet dataset.
Uses LightGBM (preferred) with fallback to sklearn RandomForestClassifier.

Deployment criteria (from ml-trading-guardrails.mdc):
- OOS accuracy >= 55% (random baseline: 40% for 4-class weighted)
- OOS Sharpe improvement >= 0.3 (requires backtest comparison)

Usage:
    python hbot/scripts/ml/train_regime_classifier.py --data hbot/data/ml/regime_train_20260227.parquet
    python hbot/scripts/ml/train_regime_classifier.py --data hbot/data/ml/regime_train_20260227.parquet --n-windows 3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REGIME_LABELS = ["neutral_low_vol", "neutral_high_vol", "up", "down", "high_vol_shock"]
TARGET_COL = "regime_label"
DROP_COLS = ["regime_str", "ts", TARGET_COL]


def _get_feature_cols(df) -> List[str]:
    return [c for c in df.columns if c not in DROP_COLS]


def _load_data(parquet_path: str):
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        print("ERROR: pandas required. Run: pip install pandas pyarrow", file=sys.stderr)
        sys.exit(1)
    p = Path(parquet_path)
    if not p.exists():
        print(f"ERROR: Data file not found: {p}", file=sys.stderr)
        sys.exit(1)
    df = pd.read_parquet(p)
    print(f"Loaded {len(df)} rows from {p}", file=sys.stderr)
    print(f"Regime distribution:\n{df['regime_str'].value_counts().to_string()}", file=sys.stderr)
    return df


def _build_model(use_lightgbm: bool = True):
    if use_lightgbm:
        try:
            from lightgbm import LGBMClassifier  # type: ignore
            return LGBMClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.05,
                num_leaves=31,
                subsample=0.8,
                colsample_bytree=0.8,
                class_weight="balanced",
                random_state=42,
                verbose=-1,
            )
        except ImportError:
            print("LightGBM not available, falling back to RandomForest", file=sys.stderr)

    from sklearn.ensemble import RandomForestClassifier  # type: ignore
    return RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )


def _walk_forward_cv(df, n_windows: int = 3) -> List[Dict]:
    from sklearn.metrics import accuracy_score, classification_report  # type: ignore
    import numpy as np  # type: ignore

    n = len(df)
    window = n // (n_windows + 1)
    fit_size = window * 2
    test_size = window

    results = []
    for w in range(n_windows):
        offset = w * (test_size // max(1, n_windows))
        fit_start = offset
        fit_end = offset + fit_size
        test_start = fit_end
        test_end = min(test_start + test_size, n)

        if test_end > n or test_start >= n:
            break

        df_fit = df.iloc[fit_start:fit_end]
        df_test = df.iloc[test_start:test_end]

        feature_cols = _get_feature_cols(df)
        X_fit = df_fit[feature_cols].values
        y_fit = df_fit[TARGET_COL].values
        X_test = df_test[feature_cols].values
        y_test = df_test[TARGET_COL].values

        model = _build_model()
        model.fit(X_fit, y_fit)

        y_pred = model.predict(X_test)
        acc = float(accuracy_score(y_test, y_pred))

        label_names = [REGIME_LABELS[i] for i in sorted(set(y_test.tolist()))]
        report = classification_report(y_test, y_pred, target_names=label_names, output_dict=True, zero_division=0)

        baseline_acc = float(np.bincount(y_test.astype(int)).max() / len(y_test))

        results.append({
            "window": w + 1,
            "fit_rows": len(df_fit),
            "test_rows": len(df_test),
            "oos_accuracy": round(acc, 4),
            "baseline_accuracy_majority": round(baseline_acc, 4),
            "accuracy_lift_vs_majority": round(acc - baseline_acc, 4),
            "passed": acc >= 0.55,
            "classification_report": report,
        })

        print(f"Window {w + 1}: OOS accuracy={acc:.4f} (baseline={baseline_acc:.4f}) — {'PASS' if acc >= 0.55 else 'FAIL'}", file=sys.stderr)

    return results


def train_and_save(
    parquet_path: str,
    output_dir: str = "hbot/data/ml",
    n_windows: int = 3,
) -> Path:
    try:
        import pandas as pd  # type: ignore
        import joblib  # type: ignore
    except ImportError:
        print("ERROR: pandas, pyarrow, scikit-learn, and joblib required.", file=sys.stderr)
        sys.exit(1)

    df = _load_data(parquet_path)
    feature_cols = _get_feature_cols(df)

    print(f"\nRunning {n_windows}-window walk-forward CV ...", file=sys.stderr)
    cv_results = _walk_forward_cv(df, n_windows=n_windows)

    all_passed = all(r["passed"] for r in cv_results)
    mean_acc = sum(r["oos_accuracy"] for r in cv_results) / max(1, len(cv_results))

    if not all_passed:
        print(f"\nWARNING: Not all windows passed (mean OOS accuracy={mean_acc:.4f}). See ROAD-10 deployment criteria.", file=sys.stderr)
        print("Model will be saved but flagged as NOT_READY for deployment.", file=sys.stderr)

    print(f"\nTraining final model on all data ...", file=sys.stderr)
    X_all = df[feature_cols].values
    y_all = df[TARGET_COL].values
    final_model = _build_model()
    final_model.fit(X_all, y_all)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "regime_classifier_v1.joblib"
    joblib.dump(final_model, model_path)
    print(f"Model saved to {model_path}", file=sys.stderr)

    from datetime import date
    metadata = {
        "model_type": type(final_model).__name__,
        "feature_set": "v2",
        "feature_columns": feature_cols,
        "regime_labels": REGIME_LABELS,
        "n_training_rows": int(len(df)),
        "walk_forward_n_windows": n_windows,
        "mean_oos_accuracy": round(mean_acc, 4),
        "all_windows_passed": all_passed,
        "deployment_ready": all_passed,
        "training_date": date.today().isoformat(),
        "cv_results": cv_results,
    }
    meta_path = out_dir / "regime_classifier_v1_metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Metadata saved to {meta_path}", file=sys.stderr)

    status = "READY" if all_passed else "NOT_READY"
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Regime Classifier Training Complete", file=sys.stderr)
    print(f"Status: {status}", file=sys.stderr)
    print(f"Mean OOS Accuracy: {mean_acc:.4f} (threshold: 0.55)", file=sys.stderr)
    print(f"Model: {model_path}", file=sys.stderr)
    if all_passed:
        print(f"\nTo deploy:", file=sys.stderr)
        print(f"  1. Set ML_ENABLED=true in compose env for signal-service", file=sys.stderr)
        print(f"  2. Set ML_MODEL_URI=file://{model_path.resolve()}", file=sys.stderr)
        print(f"  3. Set ML_FEATURE_SET=v2", file=sys.stderr)
        print(f"  4. Set ml_regime_enabled: true in epp_v2_4_bot_a.yml", file=sys.stderr)
        print(f"  5. Restart signal-service and bot1", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    return model_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Train ML regime classifier for EPP v2.4")
    ap.add_argument("--data", required=True, help="Path to regime_train_*.parquet")
    ap.add_argument("--output", default="hbot/data/ml")
    ap.add_argument("--n-windows", type=int, default=3)
    args = ap.parse_args()

    model_path = train_and_save(
        parquet_path=args.data,
        output_dir=args.output,
        n_windows=args.n_windows,
    )
    print(str(model_path))
