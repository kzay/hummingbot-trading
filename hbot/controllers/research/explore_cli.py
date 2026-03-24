"""CLI entry point for the LLM strategy exploration agent.

Usage:
    PYTHONPATH=hbot python -m controllers.research.explore_cli \\
        --provider anthropic --iterations 5

    PYTHONPATH=hbot python -m controllers.research.explore_cli \\
        --provider openai --iterations 3 --adapters atr_mm,simple
"""
from __future__ import annotations

import argparse
import json
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM-driven strategy exploration — generate, evaluate, revise",
    )
    parser.add_argument(
        "--provider", default="anthropic",
        help="LLM provider (anthropic | openai). Default: anthropic",
    )
    parser.add_argument(
        "--iterations", type=int, default=5,
        help="Maximum exploration iterations. Default: 5",
    )
    parser.add_argument(
        "--temperature", type=float, default=0.7,
        help="LLM sampling temperature. Default: 0.7",
    )
    parser.add_argument(
        "--instrument", default="BTC-USDT",
        help="Target trading pair. Default: BTC-USDT",
    )
    parser.add_argument(
        "--exchange", default="bitget",
        help="Target exchange. Default: bitget",
    )
    parser.add_argument(
        "--adapters", default="atr_mm,simple,candle",
        help="Comma-separated adapter modes. Default: atr_mm,simple,candle",
    )
    parser.add_argument(
        "--extra-context", default="",
        help="Extra market context string for the LLM",
    )
    parser.add_argument(
        "--output-dir", default="hbot/data/research/explorations",
        help="Output directory for session artefacts",
    )
    parser.add_argument(
        "--reports-dir", default="hbot/data/research/reports",
        help="Reports directory passed to EvaluationConfig",
    )
    parser.add_argument(
        "--experiments-dir", default="hbot/data/research/experiments",
        help="Experiments directory for hypothesis registry",
    )
    parser.add_argument(
        "--lifecycle-dir", default="hbot/data/research/lifecycle",
        help="Lifecycle state directory",
    )
    parser.add_argument(
        "--skip-sweep", action="store_true",
        help="Skip parameter sweep in evaluation",
    )
    parser.add_argument(
        "--skip-walkforward", action="store_true",
        help="Skip walk-forward in evaluation",
    )
    parser.add_argument(
        "--no-lifecycle", action="store_true",
        help="Disable automatic lifecycle transitions",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger(__name__)

    from controllers.research.llm_client import build_client
    from controllers.research.exploration_session import ExplorationSession, SessionConfig

    try:
        client = build_client(args.provider)
    except (EnvironmentError, ValueError) as e:
        log.error("Failed to initialise LLM client: %s", e)
        sys.exit(1)

    config = SessionConfig(
        provider=args.provider,
        max_iterations=args.iterations,
        temperature=args.temperature,
        target_instrument=args.instrument,
        target_exchange=args.exchange,
        available_adapters=[a.strip() for a in args.adapters.split(",")],
        extra_market_context=args.extra_context,
        output_dir=args.output_dir,
        reports_dir=args.reports_dir,
        experiments_dir=args.experiments_dir,
        lifecycle_dir=args.lifecycle_dir,
        skip_sweep=args.skip_sweep,
        skip_walkforward=args.skip_walkforward,
        auto_lifecycle=not args.no_lifecycle,
    )

    print(f"\n{'='*60}")
    print("Strategy Research Lab — LLM Exploration Agent")
    print(f"{'='*60}")
    print(f"  Provider:       {config.provider}")
    print(f"  Iterations:     {config.max_iterations}")
    print(f"  Temperature:    {config.temperature}")
    print(f"  Instrument:     {config.target_instrument}")
    print(f"  Exchange:       {config.target_exchange}")
    print(f"  Adapters:       {', '.join(config.available_adapters)}")
    print(f"  Auto lifecycle: {config.auto_lifecycle}")
    print(f"{'='*60}\n")

    session = ExplorationSession(client, config)
    result = session.run()

    print(f"\n{'='*60}")
    print("SESSION RESULTS")
    print(f"{'='*60}")
    print(f"  Total iterations:   {len(result.iterations)}")
    print(f"  Best score:         {result.best_observed_score:.3f}")
    print(f"  Best candidate:     {result.best_observed_candidate}")
    print(f"  Best recommendation:{result.best_recommendation}")
    print(f"  Total tokens:       {result.total_tokens_used}")
    print()

    for rec in result.iterations:
        status = f"score={rec.score:.3f} → {rec.recommendation}" if rec.score is not None else f"ERROR: {rec.error}"
        print(f"  [{rec.iteration}] {rec.action:8s} {rec.candidate_name:30s}  {status}")

    from pathlib import Path as _Path
    summary_path = _Path(config.output_dir) / "session_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "total_iterations": len(result.iterations),
        "best_observed_score": result.best_observed_score,
        "best_observed_candidate": result.best_observed_candidate,
        "best_recommendation": result.best_recommendation,
        "total_tokens_used": result.total_tokens_used,
        "iterations": [
            {
                "iteration": r.iteration,
                "action": r.action,
                "candidate_name": r.candidate_name,
                "score": r.score,
                "recommendation": r.recommendation,
                "report_path": r.report_path,
                "error": r.error,
            }
            for r in result.iterations
        ],
    }
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n  Session summary → {summary_path}")


if __name__ == "__main__":
    main()
