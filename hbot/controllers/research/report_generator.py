"""Markdown report generator for strategy candidate evaluations.

Produces a structured report with candidate summary, backtest metrics,
sweep highlights, walk-forward OOS table, robustness score breakdown,
and lifecycle recommendation.
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

        lines.append(f"# Evaluation Report: {candidate.name}")
        lines.append(f"**Generated**: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append(f"**Run ID**: {evaluation_result.run_id}")
        lines.append("")

        # Candidate summary
        lines.append("## Candidate Summary")
        lines.append(f"- **Hypothesis**: {candidate.hypothesis}")
        lines.append(f"- **Adapter**: {candidate.adapter_mode}")
        lines.append(f"- **Entry**: {candidate.entry_logic}")
        lines.append(f"- **Exit**: {candidate.exit_logic}")
        lines.append(f"- **Parameters**: {len(candidate.parameter_space)} tunable")
        lines.append("")

        # Backtest metrics
        bt = evaluation_result.backtest_result
        if bt:
            lines.append("## Backtest Metrics")
            lines.append(f"| Metric | Value |")
            lines.append(f"|--------|-------|")
            lines.append(f"| Sharpe Ratio | {bt.sharpe_ratio:.3f} |")
            lines.append(f"| Total Trades | {bt.total_trades} |")
            lines.append(f"| Max Drawdown | {bt.max_drawdown_pct:.2f}% |")
            lines.append(f"| Net P&L | {bt.net_pnl:.2f} |")
            if hasattr(bt, "maker_fill_ratio"):
                lines.append(f"| Maker Ratio | {bt.maker_fill_ratio:.2f} |")
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
                lines.append(f"- ⚠ {w}")
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
            lines.append("")

        content = "\n".join(lines)

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content)
        logger.info("Report written to %s", output_path)

        return content
