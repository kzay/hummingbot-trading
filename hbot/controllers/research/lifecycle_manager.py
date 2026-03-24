"""Strategy lifecycle management with configurable promotion gates.

Tracks lifecycle state in JSON files under ``hbot/data/research/lifecycle/``
and enforces gates before promotion to paper or promoted status.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from controllers.research import StrategyLifecycle
from controllers.research.hypothesis_registry import HypothesisRegistry

logger = logging.getLogger(__name__)

_DEFAULT_LIFECYCLE_DIR = Path("hbot/data/research/lifecycle")


@dataclass
class PromotionGates:
    """Configurable gates that must pass before promotion."""

    min_robustness_score: float = 0.55
    min_oos_windows: int = 3
    require_fee_stress_positive: bool = True
    require_latency_aware_run: bool = True


@dataclass
class GateResult:
    """Result of a single promotion gate check."""

    gate_name: str
    passed: bool
    reason: str


class LifecycleManager:
    """Manage strategy lifecycle transitions with promotion gates."""

    def __init__(
        self,
        lifecycle_dir: str | Path | None = None,
        experiments_dir: str | Path | None = None,
        gates: PromotionGates | None = None,
    ) -> None:
        self._dir = Path(lifecycle_dir or _DEFAULT_LIFECYCLE_DIR)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._registry = HypothesisRegistry(experiments_dir)
        self._gates = gates or PromotionGates()

    def _state_path(self, candidate_name: str) -> Path:
        safe = candidate_name.replace("/", "_").replace("\\", "_")
        return self._dir / f"{safe}.json"

    def get_state(self, candidate_name: str) -> dict[str, Any]:
        """Get current lifecycle state for a candidate."""
        path = self._state_path(candidate_name)
        if path.exists():
            return json.loads(path.read_text())
        return {
            "candidate_name": candidate_name,
            "current_state": StrategyLifecycle.CANDIDATE.value,
            "history": [],
            "gate_results": {},
        }

    def transition(
        self,
        candidate_name: str,
        from_state: str,
        to_state: str,
        reason: str = "",
    ) -> dict[str, Any]:
        """Record a lifecycle transition."""
        state = self.get_state(candidate_name)

        current = StrategyLifecycle(state["current_state"])
        target = StrategyLifecycle(to_state)
        from_lifecycle = StrategyLifecycle(from_state)

        if current != from_lifecycle:
            raise ValueError(
                f"Cannot transition from '{from_state}': current state is '{current.value}'"
            )

        if not current.can_transition_to(target):
            raise ValueError(
                f"Invalid transition: {current.value} → {target.value}"
            )

        state["current_state"] = target.value
        state["history"].append({
            "from": current.value,
            "to": target.value,
            "timestamp": datetime.now(UTC).isoformat(),
            "reason": reason,
        })

        self._state_path(candidate_name).write_text(
            json.dumps(state, indent=2, default=str)
        )
        logger.info("Lifecycle transition: %s %s → %s (%s)", candidate_name, current.value, target.value, reason)
        return state

    def check_gates(self, candidate_name: str) -> list[GateResult]:
        """Check all promotion gates for a candidate."""
        experiments = self._registry.list_experiments(candidate_name)
        results: list[GateResult] = []

        # Gate 1: Minimum robustness score
        scores = [e.get("robustness_score", 0) for e in experiments if e.get("robustness_score") is not None]
        best_score = max(scores) if scores else 0
        results.append(GateResult(
            gate_name="min_robustness_score",
            passed=best_score >= self._gates.min_robustness_score,
            reason=f"best score {best_score:.3f} {'≥' if best_score >= self._gates.min_robustness_score else '<'} {self._gates.min_robustness_score}",
        ))

        # Gate 2: Minimum OOS windows (based on number of experiments)
        n_experiments = len(experiments)
        results.append(GateResult(
            gate_name="min_oos_windows",
            passed=n_experiments >= self._gates.min_oos_windows,
            reason=f"{n_experiments} experiments {'≥' if n_experiments >= self._gates.min_oos_windows else '<'} {self._gates.min_oos_windows} required",
        ))

        # Gate 3: Fee stress positive
        if self._gates.require_fee_stress_positive:
            has_positive = any(
                (e.get("robustness_score") or 0) > 0 for e in experiments
            )
            results.append(GateResult(
                gate_name="fee_stress_positive",
                passed=has_positive,
                reason="at least one experiment with positive robustness" if has_positive else "no experiments with positive score",
            ))

        # Gate 4: Latency-aware fill model run
        if self._gates.require_latency_aware_run:
            has_la = any(e.get("fill_model") == "latency_aware" for e in experiments)
            results.append(GateResult(
                gate_name="latency_aware_run",
                passed=has_la,
                reason="latency_aware run found" if has_la else "no latency_aware fill model run found",
            ))

        return results

    def can_promote(self, candidate_name: str) -> tuple[bool, list[GateResult]]:
        """Check if a candidate can be promoted. Returns (can_promote, gate_results)."""
        gate_results = self.check_gates(candidate_name)
        all_pass = all(g.passed for g in gate_results)

        state = self.get_state(candidate_name)
        current = StrategyLifecycle(state["current_state"])
        can_transition = current.can_transition_to(StrategyLifecycle.PROMOTED)

        if not can_transition:
            gate_results.append(GateResult(
                gate_name="lifecycle_state",
                passed=False,
                reason=f"current state '{current.value}' cannot transition to 'promoted'",
            ))
            return False, gate_results

        # Update gate results in state
        state["gate_results"] = {g.gate_name: {"passed": g.passed, "reason": g.reason} for g in gate_results}
        self._state_path(candidate_name).write_text(
            json.dumps(state, indent=2, default=str)
        )

        return all_pass, gate_results
