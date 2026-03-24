"""CLI entry point for strategy candidate evaluation.

Usage:
    python -m controllers.research.evaluate --candidate path/to/candidate.yml
    python -m controllers.research.evaluate --candidate path/to/candidate.yml --dry-run
    python -m controllers.research.evaluate --candidate path/to/candidate.yml --skip-walkforward
"""
from __future__ import annotations

import argparse
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate a strategy candidate through the research lab pipeline",
    )
    parser.add_argument("--candidate", required=True, help="Path to candidate YAML file")
    parser.add_argument("--dry-run", action="store_true", help="Validate candidate without running pipeline")
    parser.add_argument("--skip-sweep", action="store_true", help="Skip parameter sweep step")
    parser.add_argument("--skip-walkforward", action="store_true", help="Skip walk-forward step")
    parser.add_argument("--output-dir", default="hbot/data/research/reports", help="Output directory for reports")
    parser.add_argument("--fill-model", default="latency_aware", help="Fill model preset")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    from controllers.research import StrategyCandidate
    from controllers.research.experiment_orchestrator import (
        EvaluationConfig,
        ExperimentOrchestrator,
    )
    from controllers.research.lifecycle_manager import LifecycleManager

    # Load candidate
    try:
        candidate = StrategyCandidate.from_yaml(args.candidate)
    except Exception as e:
        logger.error("Failed to load candidate: %s", e)
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"Strategy Research Lab — Candidate Evaluation")
    print(f"{'='*60}")
    print(f"  Name:       {candidate.name}")
    print(f"  Hypothesis: {candidate.hypothesis}")
    print(f"  Adapter:    {candidate.adapter_mode}")
    print(f"  Params:     {len(candidate.parameter_space)} tunable")
    print(f"  Lifecycle:  {candidate.lifecycle.value}")
    print(f"{'='*60}\n")

    if args.dry_run:
        print("[DRY RUN] Pipeline steps that would execute:")
        print("  1. Verification backtest")
        if not args.skip_sweep and candidate.parameter_space:
            print("  2. Parameter sweep")
        else:
            print("  2. Parameter sweep (SKIPPED)")
        if not args.skip_walkforward:
            print("  3. Walk-forward evaluation")
        else:
            print("  3. Walk-forward (SKIPPED)")
        print("  4. Robustness scoring")
        print("  5. Experiment manifest")
        print("  6. Report generation")
        print("\nCandidate validated successfully. Use without --dry-run to execute.")
        return

    config = EvaluationConfig(
        skip_sweep=args.skip_sweep,
        skip_walkforward=args.skip_walkforward,
        fill_model_preset=args.fill_model,
        output_dir=args.output_dir,
    )

    orchestrator = ExperimentOrchestrator(config)

    try:
        result = orchestrator.evaluate(candidate)
    except Exception as e:
        logger.error("Evaluation failed: %s", e)
        sys.exit(1)

    score = result.score_breakdown
    print(f"\n{'='*60}")
    print(f"RESULTS: {candidate.name}")
    print(f"{'='*60}")

    if score:
        print(f"\nRobustness Score: {score.total_score:.3f}")
        print(f"Recommendation:   {score.recommendation.upper()}")
        print(f"\nComponent Breakdown:")
        print(f"  {'Component':<20} {'Raw':>8} {'Norm':>8} {'Weight':>8} {'Contrib':>8}")
        print(f"  {'-'*20} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
        for name, cs in score.components.items():
            print(f"  {name:<20} {cs.raw_value:>8.3f} {cs.normalised:>8.3f} {cs.weight:>8.2f} {cs.weighted_contribution:>8.3f}")

    # Update lifecycle
    lm = LifecycleManager()
    if score and score.recommendation == "reject":
        try:
            lm.transition(candidate.name, candidate.lifecycle.value, "rejected",
                          reason=f"score {score.total_score:.3f} < 0.35")
            print(f"\nLifecycle: {candidate.lifecycle.value} → rejected")
        except ValueError:
            pass
    elif score and score.recommendation == "pass":
        try:
            lm.transition(candidate.name, candidate.lifecycle.value, "paper",
                          reason=f"score {score.total_score:.3f} >= 0.55")
            print(f"\nLifecycle: {candidate.lifecycle.value} → paper")
        except ValueError:
            pass

    print(f"\nReport: {result.report_path}")
    print(f"Run ID: {result.run_id}")


if __name__ == "__main__":
    main()
