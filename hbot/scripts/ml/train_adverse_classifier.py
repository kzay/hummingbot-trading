"""Train ML adverse fill classifier for EPP v2.4 (ROAD-11).

Walk-forward validation on adverse_fill_train_*.parquet dataset.
Uses LightGBM binary classifier (preferred) with sklearn fallback.

Deployment criteria (from ml-trading-guardrails.mdc):
- OOS precision >= 0.60 at recall = 0.70
- Adverse fill rate drop >= 15% in paper simulation
- Do NOT deploy if OOS precision < 0.55 (worse than baseline)

Usage:
    PYTHONPATH=hbot python -m scripts.ml.train_adverse_classifier --data data/ml/adverse_fill_train_20260227.parquet
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TARGET_COL = "adverse_label"
DROP_COLS = [TARGET_COL, "pnl_vs_mid_bps"]


def _get_feature_cols(df) -> list[str]:
    return [c for c in df.columns if c not in DROP_COLS]


def _load_data(parquet_path: str):
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        print("ERROR: pandas required.", file=sys.stderr)
        sys.exit(1)
    p = Path(parquet_path)
    if not p.exists():
        print(f"ERROR: File not found: {p}", file=sys.stderr)
        sys.exit(1)
    df = pd.read_parquet(p)
    adverse_rate = df[TARGET_COL].mean()
    print(f"Loaded {len(df)} fills | adverse rate: {adverse_rate:.1%}", file=sys.stderr)
    return df


def _build_model(use_lightgbm: bool = True):
    if use_lightgbm:
        try:
            from lightgbm import LGBMClassifier  # type: ignore
            return LGBMClassifier(
                n_estimators=100,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                class_weight="balanced",
                random_state=42,
                verbose=-1,
            )
        except ImportError:
            print("LightGBM not available, using sklearn GradientBoosting", file=sys.stderr)

    from sklearn.ensemble import GradientBoostingClassifier  # type: ignore
    return GradientBoostingClassifier(
        n_estimators=100,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        random_state=42,
    )


def _precision_at_recall(y_true, y_proba, target_recall: float = 0.70):
    """Find precision at the threshold where recall >= target_recall."""
    try:
        import numpy as np  # type: ignore
        from sklearn.metrics import precision_recall_curve  # type: ignore
        precision, recall, thresholds = precision_recall_curve(y_true, y_proba)
        valid = recall >= target_recall
        if not any(valid):
            return 0.0, 0.0
        best_idx = int(np.argmax(precision[valid]))
        return float(precision[valid][best_idx]), float(recall[valid][best_idx])
    except Exception:
        return 0.0, 0.0


def _walk_forward_cv(df, n_windows: int = 3) -> list[dict]:
    results = []
    n = len(df)
    fit_size = n * 3 // (n_windows + 1) * 2 // 3
    test_size = n // (n_windows + 1)

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

        y_proba = model.predict_proba(X_test)[:, 1]
        prec, rec = _precision_at_recall(y_test, y_proba, target_recall=0.70)
        baseline_prec = float(y_test.mean())

        passed = prec >= 0.60

        results.append({
            "window": w + 1,
            "fit_rows": len(df_fit),
            "test_rows": len(df_test),
            "precision_at_recall_0_70": round(prec, 4),
            "recall_achieved": round(rec, 4),
            "baseline_precision": round(baseline_prec, 4),
            "precision_lift": round(prec - baseline_prec, 4),
            "passed": passed,
        })

        status = "PASS" if passed else "FAIL"
        print(f"Window {w + 1}: precision@recall=0.70={prec:.4f} (baseline={baseline_prec:.4f}) — {status}", file=sys.stderr)

    return results


def train_and_save(
    parquet_path: str,
    output_dir: str = "data/ml",
    n_windows: int = 3,
) -> Path:
    try:
        import joblib  # type: ignore
    except ImportError:
        print("ERROR: joblib required: pip install joblib", file=sys.stderr)
        sys.exit(1)

    df = _load_data(parquet_path)
    feature_cols = _get_feature_cols(df)

    print(f"\nRunning {n_windows}-window walk-forward CV ...", file=sys.stderr)
    cv_results = _walk_forward_cv(df, n_windows=n_windows)

    all_passed = all(r["passed"] for r in cv_results)
    mean_prec = sum(r["precision_at_recall_0_70"] for r in cv_results) / max(1, len(cv_results))
    baseline = df[TARGET_COL].mean()

    if mean_prec < 0.55:
        print(f"\nERROR: Mean OOS precision {mean_prec:.4f} < baseline {baseline:.4f}.", file=sys.stderr)
        print("Model is WORSE than not using it. Do NOT deploy.", file=sys.stderr)

    print("\nTraining final model on all data ...", file=sys.stderr)
    X_all = df[feature_cols].values
    y_all = df[TARGET_COL].values
    final_model = _build_model()
    final_model.fit(X_all, y_all)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "adverse_classifier_v1.joblib"
    joblib.dump(final_model, model_path)
    print(f"Model saved to {model_path}", file=sys.stderr)

    from datetime import date
    metadata = {
        "model_type": type(final_model).__name__,
        "feature_columns": feature_cols,
        "n_training_rows": len(df),
        "adverse_rate": float(baseline),
        "walk_forward_n_windows": n_windows,
        "mean_precision_at_recall_0_70": round(mean_prec, 4),
        "baseline_precision": round(float(baseline), 4),
        "all_windows_passed": all_passed,
        "deployment_ready": all_passed and mean_prec >= 0.55,
        "training_date": date.today().isoformat(),
        "cv_results": cv_results,
    }
    meta_path = out_dir / "adverse_classifier_v1_metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Metadata saved to {meta_path}", file=sys.stderr)

    status = "READY" if metadata["deployment_ready"] else "NOT_READY"
    print(f"\n{'='*60}", file=sys.stderr)
    print("Adverse Fill Classifier Training Complete", file=sys.stderr)
    print(f"Status: {status}", file=sys.stderr)
    print(f"Mean precision@recall=0.70: {mean_prec:.4f} (threshold: 0.60)", file=sys.stderr)
    if metadata["deployment_ready"]:
        print("\nTo deploy:", file=sys.stderr)
        print("  1. Set adverse_classifier_enabled: true in epp_v2_4_bot_a.yml", file=sys.stderr)
        print(f"  2. Set adverse_classifier_model_path: {model_path.resolve()}", file=sys.stderr)
        print("  3. Restart bot1", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    return model_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Train adverse fill classifier for EPP v2.4")
    ap.add_argument("--data", required=True, help="Path to adverse_fill_train_*.parquet")
    ap.add_argument("--output", default="data/ml")
    ap.add_argument("--n-windows", type=int, default=3)
    args = ap.parse_args()

    model_path = train_and_save(
        parquet_path=args.data,
        output_dir=args.output,
        n_windows=args.n_windows,
    )
    print(str(model_path))
