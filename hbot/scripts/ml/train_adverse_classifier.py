"""Train ML adverse fill classifier for EPP v2.4 (ROAD-11).

Thin wrapper around the unified research pipeline.

Usage:
    PYTHONPATH=hbot python -m scripts.ml.train_adverse_classifier \
        --exchange bitget --pair BTC-USDT
    PYTHONPATH=hbot python -m scripts.ml.train_adverse_classifier \
        --exchange bitget --pair BTC-USDT --tune --n-trials 30
"""
from __future__ import annotations

import argparse
import json
import sys

from controllers.ml.research import train_and_evaluate


def _find_adverse_dataset() -> str | None:
    """Auto-discover the most recent adverse fill parquet."""
    from pathlib import Path
    data_dir = Path("data/ml")
    candidates = sorted(data_dir.glob("adverse_fill_train_*.parquet"), reverse=True)
    return str(candidates[0]) if candidates else None


def main() -> None:
    ap = argparse.ArgumentParser(description="Train adverse fill classifier via unified pipeline")
    ap.add_argument("--exchange", default="bitget")
    ap.add_argument("--pair", default="BTC-USDT")
    ap.add_argument("--catalog-dir", default="data/historical")
    ap.add_argument("--dataset", default=None, help="Path to pre-built adverse parquet (auto-discovered if omitted)")
    ap.add_argument("--output", default="data/ml/models")
    ap.add_argument("--n-windows", type=int, default=5)
    ap.add_argument("--embargo-bars", type=int, default=None)
    ap.add_argument("--no-purge", action="store_true")
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--n-trials", type=int, default=50)
    args = ap.parse_args()

    dataset_path = args.dataset or _find_adverse_dataset()
    if dataset_path is None:
        print("ERROR: No adverse fill dataset found. Run build_adverse_fill_dataset.py first.", file=sys.stderr)
        sys.exit(1)
    print(f"Using adverse dataset: {dataset_path}", file=sys.stderr)

    metadata = train_and_evaluate(
        exchange=args.exchange,
        pair=args.pair,
        model_type="adverse",
        catalog_dir=args.catalog_dir,
        output_dir=args.output,
        n_windows=args.n_windows,
        embargo_bars=args.embargo_bars,
        purge=not args.no_purge,
        tune=args.tune,
        n_trials=args.n_trials,
        dataset_path=dataset_path,
    )

    status = "READY" if metadata["deployment_ready"] else "NOT_READY"
    print(f"\nAdverse Fill Classifier: {status}", file=sys.stderr)
    print(f"Mean OOS metric: {metadata['mean_oos_metric']:.4f}", file=sys.stderr)
    print(json.dumps(metadata, indent=2, default=str))


if __name__ == "__main__":
    main()
