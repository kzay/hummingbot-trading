"""Tests for LifecycleManager — gates and state transitions."""
from __future__ import annotations

from pathlib import Path

import pytest

from controllers.research import StrategyLifecycle
from controllers.research.lifecycle_manager import (
    GateResult,
    LifecycleManager,
    PromotionGates,
)


class TestLifecycleManager:
    def _make_manager(self, tmp_path: Path) -> LifecycleManager:
        return LifecycleManager(
            lifecycle_dir=tmp_path / "lifecycle",
            experiments_dir=tmp_path / "experiments",
            gates=PromotionGates(min_robustness_score=0.5, min_oos_windows=2),
        )

    def test_initial_state_is_candidate(self, tmp_path: Path):
        lm = self._make_manager(tmp_path)
        state = lm.get_state("test_strat")
        assert state["current_state"] == "candidate"

    def test_valid_transition(self, tmp_path: Path):
        lm = self._make_manager(tmp_path)
        state = lm.transition("test_strat", "candidate", "paper", reason="passed gates")
        assert state["current_state"] == "paper"
        assert len(state["history"]) == 1

    def test_invalid_transition_raises(self, tmp_path: Path):
        lm = self._make_manager(tmp_path)
        with pytest.raises(ValueError, match="Invalid transition"):
            lm.transition("test_strat", "candidate", "promoted")

    def test_wrong_current_state_raises(self, tmp_path: Path):
        lm = self._make_manager(tmp_path)
        lm.transition("test_strat", "candidate", "paper")
        with pytest.raises(ValueError, match="Cannot transition from"):
            lm.transition("test_strat", "candidate", "rejected")

    def test_check_gates_no_experiments(self, tmp_path: Path):
        lm = self._make_manager(tmp_path)
        gates = lm.check_gates("empty_strat")
        assert any(not g.passed for g in gates)

    def test_can_promote_requires_all_gates(self, tmp_path: Path):
        from controllers.research.hypothesis_registry import HypothesisRegistry

        lm = self._make_manager(tmp_path)
        reg = HypothesisRegistry(tmp_path / "experiments")
        reg.record_experiment("test_strat", {}, ("", ""), 1, "latency_aware", "r1.json", robustness_score=0.6)
        reg.record_experiment("test_strat", {}, ("", ""), 2, "latency_aware", "r2.json", robustness_score=0.7)

        lm.transition("test_strat", "candidate", "paper")
        can, gates = lm.can_promote("test_strat")
        gate_map = {g.gate_name: g.passed for g in gates}
        assert gate_map["min_robustness_score"]
        assert gate_map["min_oos_windows"]

    def test_transition_history_persists(self, tmp_path: Path):
        lm = self._make_manager(tmp_path)
        lm.transition("x", "candidate", "revise", reason="needs work")
        lm.transition("x", "revise", "candidate", reason="revised params")

        state = lm.get_state("x")
        assert len(state["history"]) == 2
        assert state["current_state"] == "candidate"
