"""Markdown report generator for strategy candidate evaluations.

Produces a structured report with candidate summary, backtest metrics,
sweep highlights, walk-forward OOS table, robustness score breakdown,
gate results, overfitting flags, validation tier, replay eligibility,
paper status, and lifecycle recommendation.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from controllers.research import StrategyCandidate
    from controllers.research.experiment_orchestrator import EvaluationResult

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generate Markdown evaluation reports."""

    def generate(
        self,
        candidate: StrategyCandidate,
        evaluation_result: EvaluationResult,
        output_path: str | Path,
    ) -> str:
        """Generate a Markdown report and write it to output_path."""
        lines: list[str] = []
        score = evaluation_result.score_breakdown
        gate_report = getattr(evaluation_result, "gate_report", None)
        validation_tier = getattr(evaluation_result, "validation_tier", "candle_only")

        lines.append(f"# Evaluation Report: {candidate.name}")
        lines.append(f"**Generated**: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append(f"**Run ID**: {evaluation_result.run_id}")
        lines.append(f"**Validation Tier**: {validation_tier}")
        lines.append("")

        # Candidate summary
        lines.append("## Candidate Summary")
        lines.append(f"- **Hypothesis**: {candidate.hypothesis}")
        lines.append(f"- **Adapter**: {candidate.adapter_mode}")
        # Governed fields
        if getattr(candidate, "strategy_family", ""):
            lines.append(f"- **Strategy Family**: {candidate.strategy_family}")
        if getattr(candidate, "template_id", ""):
            lines.append(f"- **Template**: {candidate.template_id}")
        if getattr(candidate, "required_data", []):
            lines.append(f"- **Required Data**: {', '.join(candidate.required_data)}")
        if getattr(candidate, "market_conditions", ""):
            lines.append(f"- **Market Conditions**: {candidate.market_conditions}")
        lines.append(f"- **Expected Trade Frequency**: {getattr(candidate, 'expected_trade_frequency', 'medium')}")
        lines.append(f"- **Entry**: {candidate.entry_logic}")
        lines.append(f"- **Exit**: {candidate.exit_logic}")
        n_params = len(
            getattr(candidate, "effective_search_space", None) or
            getattr(candidate, "parameter_space", {})
        )
        lines.append(f"- **Parameters**: {n_params} tunable")
        lines.append("")

        # Replay eligibility
        lines.append("## Validation Tier")
        if validation_tier == "replay_validated":
            lines.append("**REPLAY VALIDATED** — Candidate has passed replay-grade validation.")
            lines.append("May be considered for automatic paper promotion subject to score threshold.")
        else:
            lines.append("**CANDLE ONLY** — Candidate has only candle-harness validation.")
            lines.append("Not eligible for automatic paper promotion. Replay data required.")
        lines.append("")

        # Quality gates
        if gate_report is not None:
            lines.append("## Quality Gates")
            gate_pass = gate_report.hard_gates_pass
            lines.append(f"**Hard Gates**: {'PASS' if gate_pass else 'FAIL'}")
            lines.append("")
            lines.append("| Gate | Result | Value | Threshold | Detail |")
            lines.append("|------|--------|-------|-----------|--------|")
            for g in gate_report.hard_gates:
                result_str = "PASS" if g.passed else "FAIL"
                lines.append(
                    f"| {g.name} | {result_str} | "
                    f"{g.value if g.value is not None else '-'} | "
                    f"{g.threshold if g.threshold is not None else '-'} | "
                    f"{g.reason} |"
                )
            lines.append("")

            if gate_report.overfit_flags:
                lines.append("## Overfitting Defenses")
                lines.append("| Defense | Flagged | Detail |")
                lines.append("|---------|---------|--------|")
                for f in gate_report.overfit_flags:
                    flagged_str = "YES" if f.flagged else "no"
                    lines.append(f"| {f.name} | {flagged_str} | {f.detail} |")
                if gate_report.complexity_penalty > 0:
                    lines.append(f"\n**Complexity penalty**: {gate_report.complexity_penalty:.2f} applied to composite score.")
                lines.append("")

        # Backtest metrics
        bt = evaluation_result.backtest_result
        if bt:
            lines.append("## Backtest Metrics")
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            lines.append(f"| Sharpe Ratio | {bt.sharpe_ratio:.3f} |")
            lines.append(f"| Closed Trades | {bt.closed_trade_count} |")
            lines.append(f"| Max Drawdown | {bt.max_drawdown_pct:.2f}% |")
            net = float(bt.realized_net_pnl_quote)
            lines.append(f"| Net P&L (realized) | {net:.2f} |")
            lines.append(f"| Maker Ratio | {bt.maker_fill_ratio:.2f} |")
            try:
                lines.append(f"| Profit Factor | {bt.profit_factor:.3f} |")
            except AttributeError:
                pass
            lines.append("")

        # Replay results
        if evaluation_result.replay_result:
            ry = evaluation_result.replay_result
            lines.append("## Replay-Grade Validation")
            try:
                lines.append(f"- **Replay Sharpe**: {ry.sharpe_ratio:.3f}")
                lines.append(f"- **Replay Net PnL**: {float(ry.realized_net_pnl_quote):.2f}")
                lines.append(f"- **Replay Trades**: {ry.closed_trade_count}")
            except AttributeError:
                lines.append("(replay metrics unavailable)")
            lines.append("")

        # Sweep results
        sweeps = evaluation_result.sweep_results
        if sweeps:
            lines.append("## Sweep Top-5")
            lines.append("| Rank | Sharpe | Params |")
            lines.append("|------|--------|--------|")
            for i, sr in enumerate(sweeps[:5]):
                if sr.result:
                    params_str = ", ".join(f"{k}={v}" for k, v in sr.params.items())
                    lines.append(f"| {i+1} | {sr.result.sharpe_ratio:.3f} | {params_str} |")
            lines.append("")

        # Walk-forward results
        wf = evaluation_result.walkforward_result
        if wf and wf.windows:
            lines.append("## Walk-Forward OOS")
            lines.append("| Window | Train | Test | IS Sharpe | OOS Sharpe |")
            lines.append("|--------|-------|------|-----------|------------|")
            for w in wf.windows:
                lines.append(
                    f"| {w.window_index} | {w.train_start}→{w.train_end} "
                    f"| {w.test_start}→{w.test_end} "
                    f"| {w.is_sharpe:.3f} | {w.oos_sharpe:.3f} |"
                )
            lines.append("")
            lines.append(f"- **Mean IS Sharpe**: {wf.mean_is_sharpe:.3f}")
            lines.append(f"- **Mean OOS Sharpe**: {wf.mean_oos_sharpe:.3f}")
            lines.append(f"- **OOS Degradation Ratio**: {wf.oos_degradation_ratio:.3f}")
            lines.append(f"- **DSR**: {wf.deflated_sharpe:.3f} (p={wf.dsr_pvalue:.3f})")
            lines.append(f"- **Holm-Bonferroni Pass**: {wf.holm_bonferroni_pass}")
            lines.append(f"- **BH FDR Pass**: {wf.bh_fdr_pass}")
            lines.append("")

        # Robustness score
        if score:
            lines.append("## Robustness Score")
            lines.append(f"**Total: {score.total_score:.3f}** → **{score.recommendation.upper()}**")
            lines.append("")
            lines.append("| Component | Raw | Normalised | Weight | Contribution |")
            lines.append("|-----------|-----|------------|--------|-------------|")
            for name, cs in score.components.items():
                lines.append(
                    f"| {name} | {cs.raw_value:.3f} | {cs.normalised:.3f} "
                    f"| {cs.weight:.2f} | {cs.weighted_contribution:.3f} |"
                )
            lines.append("")

        # Warnings
        if wf and wf.warnings:
            lines.append("## Warnings")
            for w in wf.warnings:
                lines.append(f"- {w}")
            lines.append("")

        # Recommendation
        if score:
            lines.append("## Recommendation")
            if score.recommendation == "reject":
                lines.append("**REJECT**: Strategy does not meet minimum robustness thresholds.")
            elif score.recommendation == "revise":
                lines.append("**REVISE**: Strategy shows promise but needs improvement in weak areas.")
            else:
                lines.append("**PASS**: Strategy meets robustness criteria for paper trading consideration.")

            # Paper eligibility note
            if validation_tier == "replay_validated" and score.total_score >= 0.65:
                lines.append("")
                lines.append(
                    "> **Paper eligible**: Candidate passed replay validation and composite "
                    f"score {score.total_score:.3f} >= 0.65. Run paper workflow to generate artifact."
                )
            elif validation_tier == "candle_only":
                lines.append("")
                lines.append(
                    "> **Not paper eligible**: Candle-only validation. "
                    "Run replay-grade validation before paper promotion."
                )
            lines.append("")

        content = "\n".join(lines)

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content)
        logger.info("Report written to %s", output_path)

        return content
