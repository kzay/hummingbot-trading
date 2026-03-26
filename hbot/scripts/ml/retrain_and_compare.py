#!/usr/bin/env python3
"""Retrain the regime model with fixed labels and new features.

Runs the full training pipeline and generates a comparison report
between the old model metadata and the new results.

Usage::

    python -m scripts.ml.retrain_and_compare \\
        --exchange bitget --pair BTC-USDT \\
        --catalog-dir data/historical \\
        --output data/ml/models \\
        --windows 5
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrain regime model and compare results")
    parser.add_argument("--exchange", default="bitget")
    parser.add_argument("--pair", default="BTC-USDT")
    parser.add_argument("--catalog-dir", default="data/historical")
    parser.add_argument("--output", default="data/ml/models")
    parser.add_argument("--windows", type=int, default=5)
    parser.add_argument("--tune", action="store_true")
    parser.add_argument("--n-trials", type=int, default=50)
    args = parser.parse_args()

    from controllers.ml import model_registry
    from controllers.ml.research import train_and_evaluate

    output_dir = Path(args.output)

    # ── Load old model metadata for comparison ─────────────────────
    old_metadata = None
    try:
        old_metadata = model_registry.load_metadata(
            args.output, args.exchange, args.pair, "regime",
        )
        logger.info(
            "Old model found: accuracy=%.4f, trained=%s",
            old_metadata.get("mean_oos_metric", 0),
            old_metadata.get("training_date", "unknown"),
        )
    except FileNotFoundError:
        logger.info("No previous model found — this will be the first")

    # ── Train new model ────────────────────────────────────────────
    logger.info("Starting training with fixed labels and new features...")
    new_metadata = train_and_evaluate(
        exchange=args.exchange,
        pair=args.pair,
        model_type="regime",
        catalog_dir=args.catalog_dir,
        output_dir=args.output,
        n_windows=args.windows,
        tune=args.tune,
        n_trials=args.n_trials,
    )

    # ── Generate comparison report ─────────────────────────────────
    report: dict = {
        "comparison_date": datetime.now(UTC).isoformat(),
        "exchange": args.exchange,
        "pair": args.pair,
    }

    report["new_model"] = {
        "accuracy": new_metadata.get("mean_oos_metric", 0),
        "baseline": new_metadata.get("baseline_metric", 0),
        "deployment_ready": new_metadata.get("deployment_ready", False),
        "label_mapping": new_metadata.get("label_mapping", {}),
        "n_features": len(new_metadata.get("feature_columns", [])),
        "dataset_rows": new_metadata.get("dataset_rows", 0),
        "gates": new_metadata.get("gate_results", []),
    }

    if old_metadata:
        report["old_model"] = {
            "accuracy": old_metadata.get("mean_oos_metric", 0),
            "baseline": old_metadata.get("baseline_metric", 0),
            "deployment_ready": old_metadata.get("deployment_ready", False),
            "label_mapping": old_metadata.get("label_mapping", {}),
            "n_features": len(old_metadata.get("feature_columns", [])),
            "dataset_rows": old_metadata.get("dataset_rows", 0),
        }

        old_acc = old_metadata.get("mean_oos_metric", 0)
        new_acc = new_metadata.get("mean_oos_metric", 0)
        report["comparison"] = {
            "accuracy_delta": round(new_acc - old_acc, 4),
            "label_mapping_changed": old_metadata.get("label_mapping") != new_metadata.get("label_mapping"),
            "feature_count_delta": len(new_metadata.get("feature_columns", [])) - len(old_metadata.get("feature_columns", [])),
        }

        # Compare top features
        old_top = old_metadata.get("feature_importance", {}).get("top_features", [])
        new_top = new_metadata.get("feature_importance", {}).get("top_features", [])
        report["comparison"]["top_features_overlap"] = len(set(old_top) & set(new_top))
        report["comparison"]["new_top_features"] = [f for f in new_top if f not in old_top]
        report["comparison"]["dropped_top_features"] = [f for f in old_top if f not in new_top]

    # Add validation results if present
    if "validation" in new_metadata:
        report["validation"] = new_metadata["validation"]
    if "feature_diagnostics" in new_metadata:
        report["feature_diagnostics"] = new_metadata["feature_diagnostics"]

    # ── Write report ───────────────────────────────────────────────
    report_path = output_dir / args.exchange / args.pair / "retrain_comparison.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, default=str))
    logger.info("Comparison report written to %s", report_path)

    # ── Print summary ──────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("REGIME MODEL RETRAIN COMPARISON")
    print("=" * 60)

    if old_metadata:
        old_acc = old_metadata.get("mean_oos_metric", 0)
        new_acc = new_metadata.get("mean_oos_metric", 0)
        delta = new_acc - old_acc
        print(f"\nOld accuracy: {old_acc:.4f}")
        print(f"New accuracy: {new_acc:.4f}")
        print(f"Delta:        {delta:+.4f} {'(improved)' if delta > 0 else '(regressed)' if delta < 0 else '(unchanged)'}")
        print(f"\nOld labels:   {old_metadata.get('label_mapping', {})}")
        print(f"New labels:   {new_metadata.get('label_mapping', {})}")
        print(f"\nOld features: {len(old_metadata.get('feature_columns', []))}")
        print(f"New features: {len(new_metadata.get('feature_columns', []))}")
    else:
        print(f"\nNew accuracy: {new_metadata.get('mean_oos_metric', 0):.4f}")
        print(f"Baseline:     {new_metadata.get('baseline_metric', 0):.4f}")

    print(f"\nDeployment:   {'READY' if new_metadata.get('deployment_ready') else 'NOT READY'}")
    for gate in new_metadata.get("gate_results", []):
        print(f"  {gate}")

    # Per-class summary
    wfr = new_metadata.get("walk_forward_results", [])
    if wfr and "per_class_metrics" in wfr[-1]:
        print("\nPer-class metrics (last fold):")
        for name, m in wfr[-1]["per_class_metrics"].items():
            print(f"  {name:20s}  P={m['precision']:.3f}  R={m['recall']:.3f}  F1={m['f1']:.3f}  n={m['support']}")

    # Validation summary
    validation = new_metadata.get("validation", {})
    if "transition_matrix" in validation:
        trans = validation["transition_matrix"]
        print(f"\nRegime persistence: {trans.get('mean_persistence', 0):.3f}")

    print("\n" + "=" * 60)
    print(f"Full report: {report_path}")


if __name__ == "__main__":
    main()
