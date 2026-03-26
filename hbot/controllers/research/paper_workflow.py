"""Operational paper validation workflow.

Turns paper promotion from a lifecycle label into a governed workflow:

1. Paper artifact generation  — deployable artifact for paper-eligible candidates
2. Paper run records          — research-owned records keyed by candidate + run
3. Divergence monitoring      — compare paper behavior to backtest expectations
4. Downgrade / rejection      — action when divergence breaches configured bands

Paper eligibility requires:
- All hard gates pass
- Replay-grade validation exists (validation_tier == "replay_validated")
- Composite score >= 0.65

Usage::

    from controllers.research.paper_workflow import PaperWorkflow
    workflow = PaperWorkflow()

    artifact = workflow.generate_paper_artifact(candidate, evaluation_result)
    run_record = workflow.start_paper_run(candidate.name, artifact)
    action = workflow.check_divergence(candidate.name, run_record["run_id"], paper_metrics)
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from controllers.research import StrategyCandidate
    from controllers.research.experiment_orchestrator import EvaluationResult

logger = logging.getLogger(__name__)

_DEFAULT_PAPER_RUNS_DIR = Path("hbot/data/research/paper_runs")
_DEFAULT_PAPER_ARTIFACTS_DIR = Path("hbot/data/research/paper_artifacts")

# Paper eligibility thresholds
_MIN_PAPER_SCORE = 0.65
_REQUIRED_TIER = "replay_validated"

# Default divergence bands
_DEFAULT_DIVERGENCE_BANDS: dict[str, float] = {
    "timing_diff_bars": 5.0,        # entry timing difference in bars
    "fill_quality_pct": 0.25,       # fill quality degradation %
    "slippage_mult": 2.5,           # realized slippage vs. expected
    "trade_count_pct": 0.40,        # trade frequency divergence %
    "pnl_degradation_pct": 0.50,    # PnL degradation vs. expected
    "regime_mismatch_pct": 0.30,    # % of trades in unexpected regime
    "operational_failure_rate": 0.05,  # max acceptable operational failure rate
}


# ---------------------------------------------------------------------------
# Paper artifact
# ---------------------------------------------------------------------------

@dataclass
class PaperArtifact:
    """Deployable paper trading artifact for a validated candidate."""

    artifact_id: str
    candidate_name: str
    experiment_run_id: str
    strategy_family: str
    template_id: str
    adapter_mode: str
    pinned_parameters: dict[str, Any]
    risk_budget: dict[str, Any]
    expected_conditions: str
    expected_bands: dict[str, Any]
    validation_tier: str
    composite_score: float
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "candidate_name": self.candidate_name,
            "experiment_run_id": self.experiment_run_id,
            "strategy_family": self.strategy_family,
            "template_id": self.template_id,
            "adapter_mode": self.adapter_mode,
            "pinned_parameters": self.pinned_parameters,
            "risk_budget": self.risk_budget,
            "expected_conditions": self.expected_conditions,
            "expected_bands": self.expected_bands,
            "validation_tier": self.validation_tier,
            "composite_score": self.composite_score,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Paper run record
# ---------------------------------------------------------------------------

@dataclass
class PaperRunRecord:
    """Research-owned paper run record."""

    run_id: str
    artifact_id: str
    candidate_name: str
    experiment_run_id: str
    started_at: str
    status: str = "active"  # "active" | "downgraded" | "rejected" | "passed"
    divergence_checks: list[dict[str, Any]] = field(default_factory=list)
    downgrade_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "artifact_id": self.artifact_id,
            "candidate_name": self.candidate_name,
            "experiment_run_id": self.experiment_run_id,
            "started_at": self.started_at,
            "status": self.status,
            "divergence_checks": self.divergence_checks,
            "downgrade_reason": self.downgrade_reason,
        }


# ---------------------------------------------------------------------------
# Divergence check result
# ---------------------------------------------------------------------------

@dataclass
class DivergenceCheck:
    """Result of a single paper-vs-backtest divergence dimension."""

    dimension: str
    paper_value: float | None
    expected_value: float | None
    band: float
    breached: bool
    detail: str


@dataclass
class DivergenceReport:
    """Full divergence analysis for a paper run period."""

    candidate_name: str
    run_id: str
    checks: list[DivergenceCheck] = field(default_factory=list)
    any_breached: bool = False
    recommended_action: str = "continue"  # "continue" | "downgrade" | "reject"
    breach_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_name": self.candidate_name,
            "run_id": self.run_id,
            "any_breached": self.any_breached,
            "recommended_action": self.recommended_action,
            "breach_reasons": self.breach_reasons,
            "checks": [
                {
                    "dimension": c.dimension,
                    "paper_value": c.paper_value,
                    "expected_value": c.expected_value,
                    "band": c.band,
                    "breached": c.breached,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
        }


# ---------------------------------------------------------------------------
# PaperWorkflow
# ---------------------------------------------------------------------------

class PaperWorkflow:
    """Operational paper validation workflow."""

    def __init__(
        self,
        paper_runs_dir: str | Path | None = None,
        paper_artifacts_dir: str | Path | None = None,
        divergence_bands: dict[str, float] | None = None,
    ) -> None:
        self._runs_dir = Path(paper_runs_dir or _DEFAULT_PAPER_RUNS_DIR)
        self._artifacts_dir = Path(paper_artifacts_dir or _DEFAULT_PAPER_ARTIFACTS_DIR)
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._bands = dict(divergence_bands or _DEFAULT_DIVERGENCE_BANDS)

    # ------------------------------------------------------------------
    # Eligibility check
    # ------------------------------------------------------------------

    def is_paper_eligible(self, evaluation_result: EvaluationResult) -> tuple[bool, str]:
        """Check whether a candidate may be auto-promoted to paper.

        Returns (eligible, reason).
        """
        score = evaluation_result.score_breakdown
        if score is None:
            return False, "no score breakdown available"

        if score.total_score < _MIN_PAPER_SCORE:
            return False, (
                f"composite score {score.total_score:.3f} < "
                f"required {_MIN_PAPER_SCORE}"
            )

        gate_report = evaluation_result.gate_report
        if gate_report is not None and not gate_report.hard_gates_pass:
            failed = [g.name for g in gate_report.hard_gates if not g.passed]
            return False, f"hard gate failures: {failed}"

        if evaluation_result.validation_tier != _REQUIRED_TIER:
            return False, (
                f"validation_tier='{evaluation_result.validation_tier}' — "
                f"replay-grade validation required for auto-paper"
            )

        return True, "eligible"

    # ------------------------------------------------------------------
    # Paper artifact generation
    # ------------------------------------------------------------------

    def generate_paper_artifact(
        self,
        candidate: StrategyCandidate,
        evaluation_result: EvaluationResult,
    ) -> PaperArtifact | None:
        """Generate a deployable paper artifact for an eligible candidate.

        Returns None with a warning if the candidate is ineligible.
        """
        eligible, reason = self.is_paper_eligible(evaluation_result)
        if not eligible:
            logger.warning(
                "Candidate '%s' not paper-eligible: %s",
                candidate.name, reason,
            )
            return None

        artifact_id = str(uuid.uuid4())[:12]
        bt = evaluation_result.backtest_result
        score = evaluation_result.score_breakdown

        # Build expected performance bands from backtest
        expected_bands: dict[str, Any] = {}
        if bt:
            try:
                expected_bands = {
                    "sharpe_min": round(float(bt.sharpe_ratio) * 0.6, 3),
                    "sharpe_expected": round(float(bt.sharpe_ratio), 3),
                    "max_drawdown_pct": round(float(bt.max_drawdown_pct) * 1.5, 2),
                    "fill_slippage_max_bps": 20.0,
                    "trade_count_min_per_week": max(1, int(bt.closed_trade_count) // 52),
                    "net_pnl_min": round(float(bt.realized_net_pnl_quote) * 0.5, 4),
                }
            except (AttributeError, TypeError, ValueError):
                pass

        # Risk budget from candidate family
        risk_budget: dict[str, Any] = {
            "per_trade_risk_pct": 0.5,
            "max_open_positions": 1,
            "max_drawdown_abort_pct": 25.0,
        }
        if candidate.strategy_family:
            from controllers.research.family_registry import FAMILY_REGISTRY
            family = FAMILY_REGISTRY.get(candidate.strategy_family)
            if family:
                risk_budget["per_trade_risk_pct"] = (
                    family.per_trade_risk_min_pct + family.per_trade_risk_max_pct
                ) / 2

        artifact = PaperArtifact(
            artifact_id=artifact_id,
            candidate_name=candidate.name,
            experiment_run_id=evaluation_result.run_id,
            strategy_family=candidate.strategy_family,
            template_id=candidate.template_id,
            adapter_mode=candidate.adapter_mode,
            pinned_parameters=dict(candidate.base_config.get("strategy_config", {})),
            risk_budget=risk_budget,
            expected_conditions=candidate.market_conditions or "general market",
            expected_bands=expected_bands,
            validation_tier=evaluation_result.validation_tier,
            composite_score=score.total_score if score else 0.0,
            created_at=datetime.now(UTC).isoformat(),
        )

        # Persist artifact
        safe_name = candidate.name.replace("/", "_").replace("\\", "_")
        artifact_path = self._artifacts_dir / f"{safe_name}_{artifact_id}.json"
        artifact_path.write_text(
            json.dumps(artifact.to_dict(), indent=2, default=str)
        )
        logger.info("Paper artifact generated: %s", artifact_path)

        return artifact

    # ------------------------------------------------------------------
    # Paper run records
    # ------------------------------------------------------------------

    def start_paper_run(
        self,
        candidate_name: str,
        artifact: PaperArtifact,
    ) -> PaperRunRecord:
        """Create a research-owned paper run record.

        This record links the paper run to the exact validated candidate
        and experiment manifest.
        """
        run_id = str(uuid.uuid4())[:12]
        record = PaperRunRecord(
            run_id=run_id,
            artifact_id=artifact.artifact_id,
            candidate_name=candidate_name,
            experiment_run_id=artifact.experiment_run_id,
            started_at=datetime.now(UTC).isoformat(),
        )
        self._save_run_record(record)
        logger.info(
            "Paper run started: candidate=%s run_id=%s",
            candidate_name, run_id,
        )
        return record

    def get_run_record(self, candidate_name: str, run_id: str) -> PaperRunRecord | None:
        """Load a paper run record from disk."""
        path = self._run_record_path(candidate_name, run_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            record = PaperRunRecord(
                run_id=data["run_id"],
                artifact_id=data["artifact_id"],
                candidate_name=data["candidate_name"],
                experiment_run_id=data["experiment_run_id"],
                started_at=data["started_at"],
                status=data.get("status", "active"),
                divergence_checks=data.get("divergence_checks", []),
                downgrade_reason=data.get("downgrade_reason", ""),
            )
            return record
        except Exception as exc:
            logger.warning("Failed to load paper run record %s/%s: %s", candidate_name, run_id, exc)
            return None

    # ------------------------------------------------------------------
    # Divergence monitoring
    # ------------------------------------------------------------------

    def check_divergence(
        self,
        candidate_name: str,
        run_id: str,
        paper_metrics: dict[str, Any],
        custom_bands: dict[str, float] | None = None,
    ) -> DivergenceReport:
        """Compare paper behavior to backtest expectations.

        ``paper_metrics`` should contain actual paper performance data:
            - timing_diff_bars: float — average entry timing difference
            - fill_quality_pct: float — fill quality degradation %
            - slippage_mult: float — realized slippage multiplier
            - trade_count_pct: float — trade frequency divergence %
            - pnl_degradation_pct: float — PnL vs. expected %
            - regime_mismatch_pct: float — % trades in unexpected regime
            - operational_failure_rate: float — operational failure rate

        Returns a DivergenceReport with recommended action.
        """
        bands = dict(self._bands)
        if custom_bands:
            bands.update(custom_bands)

        # Load artifact for expected values
        record = self.get_run_record(candidate_name, run_id)
        artifact = self._load_artifact(candidate_name, record.artifact_id if record else None)

        checks: list[DivergenceCheck] = []
        breach_reasons: list[str] = []

        for dimension, band in bands.items():
            paper_val = paper_metrics.get(dimension)
            if paper_val is None:
                continue

            expected_val = None
            if artifact and artifact.expected_bands:
                # Map dimension to expected band key
                mapping = {
                    "pnl_degradation_pct": "net_pnl_min",
                    "fill_quality_pct": "fill_slippage_max_bps",
                }
                expected_key = mapping.get(dimension, dimension)
                expected_val = artifact.expected_bands.get(expected_key)

            breached = float(paper_val) > float(band)
            check = DivergenceCheck(
                dimension=dimension,
                paper_value=float(paper_val),
                expected_value=float(expected_val) if expected_val is not None else None,
                band=float(band),
                breached=breached,
                detail=(
                    f"{dimension}: paper={paper_val:.4f} "
                    f"band={band:.4f} "
                    f"{'BREACH' if breached else 'ok'}"
                ),
            )
            checks.append(check)
            if breached:
                breach_reasons.append(f"{dimension}={paper_val:.4f} > band {band:.4f}")

        any_breached = bool(breach_reasons)
        n_breaches = len(breach_reasons)

        if n_breaches >= 3:
            recommended_action = "reject"
        elif n_breaches >= 1:
            recommended_action = "downgrade"
        else:
            recommended_action = "continue"

        report = DivergenceReport(
            candidate_name=candidate_name,
            run_id=run_id,
            checks=checks,
            any_breached=any_breached,
            recommended_action=recommended_action,
            breach_reasons=breach_reasons,
        )

        # Persist divergence check and apply downgrade if needed
        if record:
            record.divergence_checks.append(report.to_dict())
            if recommended_action in ("downgrade", "reject"):
                record.status = recommended_action
                record.downgrade_reason = "; ".join(breach_reasons)
                logger.warning(
                    "Paper run %s for '%s': %s — %s",
                    run_id, candidate_name, recommended_action,
                    record.downgrade_reason,
                )
            self._save_run_record(record)

        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_record_path(self, candidate_name: str, run_id: str) -> Path:
        safe = candidate_name.replace("/", "_").replace("\\", "_")
        return self._runs_dir / safe / f"{run_id}.json"

    def _save_run_record(self, record: PaperRunRecord) -> None:
        path = self._run_record_path(record.candidate_name, record.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record.to_dict(), indent=2, default=str))

    def _load_artifact(
        self, candidate_name: str, artifact_id: str | None
    ) -> PaperArtifact | None:
        if not artifact_id:
            return None
        safe = candidate_name.replace("/", "_").replace("\\", "_")
        path = self._artifacts_dir / f"{safe}_{artifact_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return PaperArtifact(
                artifact_id=data["artifact_id"],
                candidate_name=data["candidate_name"],
                experiment_run_id=data["experiment_run_id"],
                strategy_family=data.get("strategy_family", ""),
                template_id=data.get("template_id", ""),
                adapter_mode=data.get("adapter_mode", ""),
                pinned_parameters=data.get("pinned_parameters", {}),
                risk_budget=data.get("risk_budget", {}),
                expected_conditions=data.get("expected_conditions", ""),
                expected_bands=data.get("expected_bands", {}),
                validation_tier=data.get("validation_tier", ""),
                composite_score=data.get("composite_score", 0.0),
                created_at=data.get("created_at", ""),
            )
        except Exception as exc:
            logger.warning("Failed to load artifact %s: %s", artifact_id, exc)
            return None

    def list_paper_runs(self, candidate_name: str) -> list[dict[str, Any]]:
        """List all paper run records for a candidate."""
        safe = candidate_name.replace("/", "_").replace("\\", "_")
        run_dir = self._runs_dir / safe
        if not run_dir.exists():
            return []
        results = []
        for f in sorted(run_dir.glob("*.json")):
            try:
                results.append(json.loads(f.read_text()))
            except Exception:
                pass
        return results
