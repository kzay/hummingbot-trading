"""Tests for HypothesisRegistry — immutable JSONL experiment tracking."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from controllers.research.hypothesis_registry import HypothesisRegistry


class TestHypothesisRegistry:
    def test_record_creates_manifest(self, tmp_path: Path):
        reg = HypothesisRegistry(tmp_path / "experiments")
        entry = reg.record_experiment(
            candidate_name="test_strat",
            config={"spread": 1.5},
            data_window=("2025-01-01", "2025-03-01"),
            seed=42,
            fill_model="latency_aware",
            result_path="results/test.json",
            robustness_score=0.67,
        )
        assert entry["candidate_name"] == "test_strat"
        assert entry["seed"] == 42
        assert "run_id" in entry
        assert "config_hash" in entry
        assert "git_sha" in entry

    def test_list_experiments_filters_by_name(self, tmp_path: Path):
        reg = HypothesisRegistry(tmp_path / "experiments")
        reg.record_experiment("strat_a", {}, ("2025-01-01", "2025-02-01"), 1, "simple", "a.json")
        reg.record_experiment("strat_b", {}, ("2025-01-01", "2025-02-01"), 2, "simple", "b.json")
        reg.record_experiment("strat_a", {}, ("2025-02-01", "2025-03-01"), 3, "simple", "c.json")

        all_a = reg.list_experiments("strat_a")
        assert len(all_a) == 2
        all_b = reg.list_experiments("strat_b")
        assert len(all_b) == 1

    def test_experiments_are_isolated_per_candidate_file(self, tmp_path: Path):
        reg = HypothesisRegistry(tmp_path / "experiments")
        reg.record_experiment("x", {}, ("2025-01-01", "2025-02-01"), 1, "simple", "x.json")
        reg.record_experiment("y", {}, ("2025-01-01", "2025-02-01"), 2, "simple", "y.json")

        x_exp = reg.list_experiments("x")
        y_exp = reg.list_experiments("y")
        assert len(x_exp) == 1
        assert len(y_exp) == 1
        assert x_exp[0]["candidate_name"] == "x"
        assert y_exp[0]["candidate_name"] == "y"

    def test_config_hash_deterministic(self, tmp_path: Path):
        reg = HypothesisRegistry(tmp_path / "experiments")
        e1 = reg.record_experiment("x", {"a": 1, "b": 2}, ("", ""), 1, "simple", "r1.json")
        e2 = reg.record_experiment("x", {"a": 1, "b": 2}, ("", ""), 1, "simple", "r2.json")
        assert e1["config_hash"] == e2["config_hash"]

    def test_manifest_file_is_append_only(self, tmp_path: Path):
        reg = HypothesisRegistry(tmp_path / "experiments")
        reg.record_experiment("x", {}, ("", ""), 1, "simple", "r.json")
        reg.record_experiment("x", {}, ("", ""), 2, "simple", "r2.json")

        manifest_path = tmp_path / "experiments" / "x.jsonl"
        lines = manifest_path.read_text().strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            json.loads(line)  # each line is valid JSON
