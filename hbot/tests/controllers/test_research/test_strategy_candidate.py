"""Tests for StrategyCandidate and StrategyLifecycle."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from controllers.research import StrategyCandidate, StrategyLifecycle


class TestStrategyLifecycle:
    def test_valid_transitions_from_candidate(self):
        lc = StrategyLifecycle.CANDIDATE
        assert lc.can_transition_to(StrategyLifecycle.REJECTED)
        assert lc.can_transition_to(StrategyLifecycle.REVISE)
        assert lc.can_transition_to(StrategyLifecycle.PAPER)
        assert not lc.can_transition_to(StrategyLifecycle.PROMOTED)

    def test_valid_transitions_from_paper(self):
        lc = StrategyLifecycle.PAPER
        assert lc.can_transition_to(StrategyLifecycle.PROMOTED)
        assert lc.can_transition_to(StrategyLifecycle.REJECTED)
        assert lc.can_transition_to(StrategyLifecycle.REVISE)
        assert not lc.can_transition_to(StrategyLifecycle.CANDIDATE)

    def test_rejected_is_terminal(self):
        lc = StrategyLifecycle.REJECTED
        for target in StrategyLifecycle:
            if target == lc:
                continue
            assert not lc.can_transition_to(target)

    def test_promoted_is_terminal(self):
        lc = StrategyLifecycle.PROMOTED
        for target in StrategyLifecycle:
            if target == lc:
                continue
            assert not lc.can_transition_to(target)

    def test_revise_can_return_to_candidate(self):
        assert StrategyLifecycle.REVISE.can_transition_to(StrategyLifecycle.CANDIDATE)


class TestStrategyCandidateYaml:
    def _make_candidate(self) -> StrategyCandidate:
        return StrategyCandidate(
            name="test_strat",
            hypothesis="Mean reversion after large spikes",
            adapter_mode="candle",
            parameter_space={"spread_mult": [1.0, 1.5, 2.0]},
            entry_logic="enter short if spike > 2ATR",
            exit_logic="close after 5 bars or take-profit at 0.5ATR",
            base_config={"data_source": {"pair": "BTC-USDT"}},
            required_tests=["test_adapter_compiles"],
            metadata={"author": "research_lab"},
        )

    def test_roundtrip_yaml(self, tmp_path: Path):
        c = self._make_candidate()
        path = tmp_path / "test.yml"
        c.to_yaml(path)

        loaded = StrategyCandidate.from_yaml(path)
        assert loaded.name == c.name
        assert loaded.hypothesis == c.hypothesis
        assert loaded.parameter_space == c.parameter_space
        assert loaded.lifecycle == StrategyLifecycle.CANDIDATE

    def test_missing_required_field_raises(self, tmp_path: Path):
        path = tmp_path / "bad.yml"
        path.write_text(yaml.dump({"name": "x"}))
        with pytest.raises(ValueError, match="Missing required field"):
            StrategyCandidate.from_yaml(path)

    def test_lifecycle_persists(self, tmp_path: Path):
        c = self._make_candidate()
        c.lifecycle = StrategyLifecycle.PAPER
        path = tmp_path / "paper.yml"
        c.to_yaml(path)

        loaded = StrategyCandidate.from_yaml(path)
        assert loaded.lifecycle == StrategyLifecycle.PAPER
