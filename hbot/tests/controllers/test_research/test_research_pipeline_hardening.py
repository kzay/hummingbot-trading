"""Tests for research-pipeline-hardening changes.

Covers:
    7.1 Unit tests: legacy candidate loading, governed validation,
        invalid-combination rejection, complexity penalties, manifest serialization
    7.2 Orchestrator tests: staged validation, gate enforcement, replay eligibility,
        paper-artifact creation
    7.3 Lifecycle and paper-validation tests: promotion gating,
        divergence-based downgrade logic
    7.4 API regression tests: richer candidate detail, leaderboard response
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from controllers.research import StrategyCandidate, StrategyLifecycle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_legacy_yaml(tmp_path: Path, name: str = "legacy-strat-v1") -> Path:
    """Write a legacy (schema_version 1) candidate YAML."""
    data = {
        "name": name,
        "hypothesis": "Test hypothesis",
        "adapter_mode": "atr_mm",
        "parameter_space": {"atr_period": [10, 14, 20]},
        "entry_logic": "Enter when ATR expands",
        "exit_logic": "Exit after 5 bars",
        "base_config": {
            "strategy_class": "atr_mm",
            "strategy_config": {},
            "data_source": {
                "exchange": "bitget",
                "pair": "BTC-USDT",
                "resolution": "15m",
                "instrument_type": "perp",
            },
            "initial_equity": "500",
        },
        "lifecycle": "candidate",
    }
    path = tmp_path / f"{name}.yml"
    path.write_text(yaml.dump(data))
    return path


def _make_governed_yaml(tmp_path: Path, name: str = "governed-strat-v1") -> Path:
    """Write a governed (schema_version 2) candidate YAML."""
    data = {
        "name": name,
        "hypothesis": "Trend continuation on pullback",
        "adapter_mode": "pullback",
        "parameter_space": {"pullback_depth_atr": [0.3, 0.5, 0.8]},
        "search_space": {"pullback_depth_atr": [0.3, 0.5, 0.8], "stop_atr_mult": [1.0, 1.5]},
        "entry_logic": "Enter on pullback below trend",
        "exit_logic": "Exit at stop or target",
        "base_config": {
            "strategy_class": "pullback",
            "strategy_config": {},
            "data_source": {
                "exchange": "bitget",
                "pair": "BTC-USDT",
                "resolution": "15m",
                "instrument_type": "perp",
            },
            "initial_equity": "500",
        },
        "lifecycle": "candidate",
        "schema_version": 2,
        "strategy_family": "trend_continuation",
        "template_id": "trend_continuation_pullback",
        "required_data": [],
        "market_conditions": "trending market",
        "expected_trade_frequency": "medium",
        "complexity_budget": 5,
    }
    path = tmp_path / f"{name}.yml"
    path.write_text(yaml.dump(data))
    return path


# ---------------------------------------------------------------------------
# 7.1 Unit tests — candidate loading and governance
# ---------------------------------------------------------------------------

class TestLegacyCandidateLoading:
    """Legacy candidate YAML must load successfully with schema_version=1."""

    def test_legacy_loads_without_governed_fields(self, tmp_path):
        path = _make_legacy_yaml(tmp_path)
        c = StrategyCandidate.from_yaml(path)
        assert c.name == "legacy-strat-v1"
        assert c.schema_version == 1
        assert c.strategy_family == ""
        assert c.search_space == {}
        assert c.lifecycle == StrategyLifecycle.CANDIDATE

    def test_legacy_effective_search_space_falls_back_to_parameter_space(self, tmp_path):
        path = _make_legacy_yaml(tmp_path)
        c = StrategyCandidate.from_yaml(path)
        assert c.effective_search_space == c.parameter_space
        assert "atr_period" in c.effective_search_space

    def test_legacy_not_governed(self, tmp_path):
        path = _make_legacy_yaml(tmp_path)
        c = StrategyCandidate.from_yaml(path)
        assert not c.is_governed

    def test_legacy_roundtrip_preserves_schema_version(self, tmp_path):
        path = _make_legacy_yaml(tmp_path)
        c = StrategyCandidate.from_yaml(path)
        out = tmp_path / "out.yml"
        c.to_yaml(out)
        reloaded = StrategyCandidate.from_yaml(out)
        assert reloaded.schema_version == 1


class TestGovernedCandidateLoading:
    """Governed candidate YAML must preserve governed fields."""

    def test_governed_loads_with_family_and_template(self, tmp_path):
        path = _make_governed_yaml(tmp_path)
        c = StrategyCandidate.from_yaml(path)
        assert c.schema_version == 2
        assert c.strategy_family == "trend_continuation"
        assert c.template_id == "trend_continuation_pullback"

    def test_governed_effective_search_space_uses_search_space(self, tmp_path):
        path = _make_governed_yaml(tmp_path)
        c = StrategyCandidate.from_yaml(path)
        assert c.effective_search_space == c.search_space
        assert "stop_atr_mult" in c.effective_search_space

    def test_governed_is_governed_flag(self, tmp_path):
        path = _make_governed_yaml(tmp_path)
        c = StrategyCandidate.from_yaml(path)
        assert c.is_governed

    def test_governed_roundtrip_preserves_family(self, tmp_path):
        path = _make_governed_yaml(tmp_path)
        c = StrategyCandidate.from_yaml(path)
        out = tmp_path / "out.yml"
        c.to_yaml(out)
        reloaded = StrategyCandidate.from_yaml(out)
        assert reloaded.strategy_family == "trend_continuation"
        assert reloaded.template_id == "trend_continuation_pullback"


class TestCandidateValidation:
    """Pre-backtest validation rejects invalid candidates."""

    def test_adapter_mismatch_rejected(self, tmp_path):
        from controllers.research.candidate_validator import (
            CandidateValidationError,
            validate_candidate,
        )
        c = StrategyCandidate(
            name="mismatch",
            hypothesis="test",
            adapter_mode="atr_mm",
            parameter_space={},
            entry_logic="enter",
            exit_logic="exit",
            base_config={"strategy_class": "pullback"},  # mismatch
        )
        with pytest.raises(CandidateValidationError, match="Adapter mismatch"):
            validate_candidate(c)

    def test_unsupported_family_rejected(self, tmp_path):
        from controllers.research.candidate_validator import (
            CandidateValidationError,
            validate_candidate,
        )
        c = StrategyCandidate(
            name="bad-family",
            hypothesis="test",
            adapter_mode="atr_mm",
            parameter_space={},
            entry_logic="enter",
            exit_logic="exit",
            base_config={"strategy_class": "atr_mm"},
            schema_version=2,
            strategy_family="liquidation_cascade",  # phase-one unsupported
        )
        with pytest.raises(CandidateValidationError, match="not a supported phase-one family"):
            validate_candidate(c)

    def test_invalid_family_name_rejected(self):
        from controllers.research.candidate_validator import (
            CandidateValidationError,
            validate_candidate,
        )
        c = StrategyCandidate(
            name="unknown-family",
            hypothesis="test",
            adapter_mode="atr_mm",
            parameter_space={},
            entry_logic="enter",
            exit_logic="exit",
            base_config={"strategy_class": "atr_mm"},
            schema_version=2,
            strategy_family="unicorn_strategy",
        )
        with pytest.raises(CandidateValidationError, match="Unknown strategy family"):
            validate_candidate(c)

    def test_stop_above_target_rejected(self):
        from controllers.research.candidate_validator import (
            CandidateValidationError,
            validate_candidate,
        )
        c = StrategyCandidate(
            name="bad-params",
            hypothesis="test",
            adapter_mode="atr_mm",
            parameter_space={
                "stop_atr_mult": [2.0, 3.0],
                "tp_atr_mult": [0.5, 1.0],  # stop > target
            },
            entry_logic="enter",
            exit_logic="exit",
            base_config={"strategy_class": "atr_mm"},
        )
        with pytest.raises(CandidateValidationError, match="stop.*above or equal to target"):
            validate_candidate(c)

    def test_valid_legacy_candidate_passes(self):
        from controllers.research.candidate_validator import validate_candidate
        c = StrategyCandidate(
            name="valid-legacy",
            hypothesis="test",
            adapter_mode="atr_mm",
            parameter_space={"atr_period": [10, 14, 20]},
            entry_logic="enter",
            exit_logic="exit",
            base_config={"strategy_class": "atr_mm"},
        )
        validate_candidate(c)  # must not raise

    def test_valid_governed_candidate_passes(self):
        from controllers.research.candidate_validator import validate_candidate
        c = StrategyCandidate(
            name="valid-governed",
            hypothesis="test",
            adapter_mode="pullback",
            parameter_space={},
            search_space={
                "pullback_depth_atr": [0.3, 0.5],
                "trend_ema": [50, 100],
                "stop_atr_mult": [1.0, 1.5],
            },
            entry_logic="enter",
            exit_logic="exit",
            base_config={"strategy_class": "pullback"},
            schema_version=2,
            strategy_family="trend_continuation",
            template_id="trend_continuation_pullback",
        )
        validate_candidate(c)  # must not raise


class TestComplexityPenalty:
    """Candidates with > 6 tunable parameters incur a simplicity penalty."""

    def test_complexity_penalty_applied_above_threshold(self):
        from controllers.research.quality_gates import _compute_complexity_penalty
        assert _compute_complexity_penalty(7) > 0
        assert _compute_complexity_penalty(6) == 0.0

    def test_complexity_penalty_scales_with_excess(self):
        from controllers.research.quality_gates import _compute_complexity_penalty
        penalty_7 = _compute_complexity_penalty(7)
        penalty_10 = _compute_complexity_penalty(10)
        assert penalty_10 > penalty_7

    def test_complexity_penalty_capped_at_30_percent(self):
        from controllers.research.quality_gates import _compute_complexity_penalty
        # 100 parameters should not exceed 0.30
        assert _compute_complexity_penalty(100) <= 0.30


class TestManifestSerialization:
    """Richer manifest fields are persisted and readable."""

    def test_record_experiment_with_governed_fields(self, tmp_path):
        from controllers.research.hypothesis_registry import HypothesisRegistry
        registry = HypothesisRegistry(tmp_path)
        manifest = registry.record_experiment(
            candidate_name="test-cand",
            config={"strategy_class": "atr_mm"},
            data_window=("2024-01-01", "2024-12-31"),
            seed=42,
            fill_model="latency_aware",
            result_path="/tmp/result.json",
            robustness_score=0.72,
            recommendation="pass",
            gate_results={"hard_gates_pass": True, "hard_gates": []},
            validation_tier="candle_only",
            stress_results={"fee_stress_sharpes": [1.2, 0.9]},
            strategy_family="trend_continuation",
            template_id="trend_continuation_pullback",
            candidate_hash="abc123",
        )
        assert manifest["recommendation"] == "pass"
        assert manifest["validation_tier"] == "candle_only"
        assert manifest["gate_results"]["hard_gates_pass"] is True
        assert manifest["strategy_family"] == "trend_continuation"
        assert manifest["candidate_hash"] == "abc123"

    def test_manifest_appended_to_jsonl(self, tmp_path):
        from controllers.research.hypothesis_registry import HypothesisRegistry
        registry = HypothesisRegistry(tmp_path)
        registry.record_experiment(
            candidate_name="multi-run",
            config={},
            data_window=("2024-01-01", "2024-12-31"),
            seed=1,
            fill_model="latency_aware",
            result_path="/tmp/a.json",
        )
        registry.record_experiment(
            candidate_name="multi-run",
            config={},
            data_window=("2024-01-01", "2024-12-31"),
            seed=2,
            fill_model="latency_aware",
            result_path="/tmp/b.json",
        )
        experiments = registry.list_experiments("multi-run")
        assert len(experiments) == 2

    def test_legacy_manifest_fields_still_present(self, tmp_path):
        from controllers.research.hypothesis_registry import HypothesisRegistry
        registry = HypothesisRegistry(tmp_path)
        manifest = registry.record_experiment(
            candidate_name="legacy",
            config={"x": 1},
            data_window=("2024-01-01", "2024-06-30"),
            seed=42,
            fill_model="balanced",
            result_path="/tmp/r.json",
            robustness_score=0.55,
        )
        for field in ("run_id", "candidate_name", "config_hash", "git_sha",
                      "data_window", "seed", "fill_model", "result_path"):
            assert field in manifest


# ---------------------------------------------------------------------------
# 7.2 Orchestrator tests — staged validation, gates, paper eligibility
# ---------------------------------------------------------------------------

class TestStagedValidationTier:
    """Orchestrator correctly sets validation_tier."""

    def test_candle_only_when_no_replay_path(self):
        from controllers.research.experiment_orchestrator import (
            EvaluationConfig,
            TIER_CANDLE_ONLY,
        )
        cfg = EvaluationConfig(replay_data_path="")
        assert cfg.replay_data_path == ""
        # Tier constant exists
        assert TIER_CANDLE_ONLY == "candle_only"

    def test_replay_validated_constant_exists(self):
        from controllers.research.experiment_orchestrator import TIER_REPLAY_VALIDATED
        assert TIER_REPLAY_VALIDATED == "replay_validated"

    def test_evaluation_result_defaults_to_candle_only(self):
        from controllers.research.experiment_orchestrator import (
            EvaluationResult,
            TIER_CANDLE_ONLY,
        )
        r = EvaluationResult(candidate_name="x", run_id="abc")
        assert r.validation_tier == TIER_CANDLE_ONLY


class TestHardGates:
    """Hard gates correctly pass/fail based on metrics."""

    def _make_bt(self, net_pnl=100.0, dd=15.0, pf=1.5, sharpe=1.2, trades=50):
        bt = MagicMock()
        bt.realized_net_pnl_quote = net_pnl
        bt.max_drawdown_pct = dd
        bt.profit_factor = pf
        bt.sharpe_ratio = sharpe
        bt.closed_trade_count = trades
        return bt

    def test_all_gates_pass_for_good_candidate(self):
        from controllers.research.quality_gates import run_quality_gates
        candidate = MagicMock()
        candidate.name = "test"
        candidate.expected_trade_frequency = "medium"
        candidate.effective_search_space = {"a": [1, 2]}
        candidate.complexity_budget = 6
        candidate.evaluation_rules = {}
        bt = self._make_bt()
        metrics = {
            "mean_oos_sharpe": 0.8,
            "oos_degradation_ratio": 0.75,
            "deflated_sharpe": 0.1,
            "base_sharpe": 1.2,
        }
        report = run_quality_gates(candidate, metrics, bt)
        assert report.hard_gates_pass

    def test_negative_pnl_fails_gate(self):
        from controllers.research.quality_gates import run_quality_gates
        candidate = MagicMock()
        candidate.name = "test"
        candidate.expected_trade_frequency = "medium"
        candidate.effective_search_space = {}
        candidate.complexity_budget = 6
        candidate.evaluation_rules = {}
        bt = self._make_bt(net_pnl=-50.0)
        metrics = {
            "mean_oos_sharpe": 0.8,
            "oos_degradation_ratio": 0.75,
            "deflated_sharpe": 0.1,
        }
        report = run_quality_gates(candidate, metrics, bt)
        assert not report.hard_gates_pass
        gate_names = {g.name for g in report.hard_gates if not g.passed}
        assert "net_pnl" in gate_names

    def test_excessive_drawdown_fails_gate(self):
        from controllers.research.quality_gates import run_quality_gates
        candidate = MagicMock()
        candidate.name = "test"
        candidate.expected_trade_frequency = "medium"
        candidate.effective_search_space = {}
        candidate.complexity_budget = 6
        candidate.evaluation_rules = {}
        bt = self._make_bt(dd=35.0)  # > 20%
        metrics = {
            "mean_oos_sharpe": 0.8,
            "oos_degradation_ratio": 0.75,
            "deflated_sharpe": 0.1,
        }
        report = run_quality_gates(candidate, metrics, bt)
        assert not report.hard_gates_pass
        gate_names = {g.name for g in report.hard_gates if not g.passed}
        assert "max_drawdown" in gate_names

    def test_low_oos_sharpe_fails_gate(self):
        from controllers.research.quality_gates import run_quality_gates
        candidate = MagicMock()
        candidate.name = "test"
        candidate.expected_trade_frequency = "medium"
        candidate.effective_search_space = {}
        candidate.complexity_budget = 6
        candidate.evaluation_rules = {}
        bt = self._make_bt()
        metrics = {
            "mean_oos_sharpe": 0.3,  # < 0.5
            "oos_degradation_ratio": 0.75,
            "deflated_sharpe": 0.1,
        }
        report = run_quality_gates(candidate, metrics, bt)
        assert not report.hard_gates_pass
        gate_names = {g.name for g in report.hard_gates if not g.passed}
        assert "oos_sharpe" in gate_names

    def test_insufficient_trades_fails_gate(self):
        from controllers.research.quality_gates import run_quality_gates
        candidate = MagicMock()
        candidate.name = "test"
        candidate.expected_trade_frequency = "medium"
        candidate.effective_search_space = {}
        candidate.complexity_budget = 6
        candidate.evaluation_rules = {}
        bt = self._make_bt(trades=10)  # < 40 for medium
        metrics = {
            "mean_oos_sharpe": 0.8,
            "oos_degradation_ratio": 0.75,
            "deflated_sharpe": 0.1,
        }
        report = run_quality_gates(candidate, metrics, bt)
        assert not report.hard_gates_pass
        gate_names = {g.name for g in report.hard_gates if not g.passed}
        assert "trade_count" in gate_names


class TestOverfittingDefenses:
    """Overfitting defenses flag fragile candidates."""

    def test_period_concentration_flagged(self):
        from controllers.research.quality_gates import _check_period_concentration
        bt = MagicMock()
        bt.daily_pnl = {
            "2024-01-01": 1000.0,  # 91% of total
            "2024-01-02": 50.0,
            "2024-01-03": 40.0,
        }
        result = _check_period_concentration(bt)
        assert result.flagged

    def test_period_concentration_ok(self):
        from controllers.research.quality_gates import _check_period_concentration
        bt = MagicMock()
        bt.daily_pnl = {
            "2024-01-01": 100.0,
            "2024-02-01": 110.0,
            "2024-03-01": 90.0,
            "2024-04-01": 95.0,
        }
        result = _check_period_concentration(bt)
        assert not result.flagged

    def test_trade_concentration_flagged(self):
        from controllers.research.quality_gates import _check_trade_concentration
        bt = MagicMock()
        bt.trade_pnl_list = [500.0, 10.0, 10.0, 10.0]  # 96% from first trade
        result = _check_trade_concentration(bt)
        assert result.flagged

    def test_parameter_fragility_flagged(self):
        from controllers.research.quality_gates import _check_parameter_fragility
        sr = MagicMock()
        sr.result = MagicMock()
        sr.result.sharpe_ratio = 0.1  # Very low vs center score of 2.0
        sweep = [sr, sr, sr, sr, sr]
        result = _check_parameter_fragility(sweep, center_score=2.0)
        assert result.flagged


# ---------------------------------------------------------------------------
# 7.3 Lifecycle and paper-validation tests
# ---------------------------------------------------------------------------

class TestPaperEligibility:
    """Paper eligibility gating."""

    def test_candle_only_not_paper_eligible(self):
        from controllers.research.paper_workflow import PaperWorkflow
        from controllers.research.experiment_orchestrator import TIER_CANDLE_ONLY
        workflow = PaperWorkflow.__new__(PaperWorkflow)

        eval_result = MagicMock()
        eval_result.validation_tier = TIER_CANDLE_ONLY
        eval_result.score_breakdown = MagicMock(total_score=0.80)
        eval_result.gate_report = MagicMock(hard_gates_pass=True)

        eligible, reason = workflow.is_paper_eligible(eval_result)
        assert not eligible
        assert "candle" in reason.lower() or "replay" in reason.lower()

    def test_replay_validated_high_score_eligible(self):
        from controllers.research.paper_workflow import PaperWorkflow
        from controllers.research.experiment_orchestrator import TIER_REPLAY_VALIDATED
        workflow = PaperWorkflow.__new__(PaperWorkflow)

        eval_result = MagicMock()
        eval_result.validation_tier = TIER_REPLAY_VALIDATED
        eval_result.score_breakdown = MagicMock(total_score=0.70)
        eval_result.gate_report = MagicMock(hard_gates_pass=True)

        eligible, reason = workflow.is_paper_eligible(eval_result)
        assert eligible

    def test_replay_validated_low_score_not_eligible(self):
        from controllers.research.paper_workflow import PaperWorkflow
        from controllers.research.experiment_orchestrator import TIER_REPLAY_VALIDATED
        workflow = PaperWorkflow.__new__(PaperWorkflow)

        eval_result = MagicMock()
        eval_result.validation_tier = TIER_REPLAY_VALIDATED
        eval_result.score_breakdown = MagicMock(total_score=0.50)
        eval_result.gate_report = MagicMock(hard_gates_pass=True)

        eligible, reason = workflow.is_paper_eligible(eval_result)
        assert not eligible
        assert "score" in reason.lower()

    def test_gate_failure_not_paper_eligible(self):
        from controllers.research.paper_workflow import PaperWorkflow
        from controllers.research.experiment_orchestrator import TIER_REPLAY_VALIDATED
        workflow = PaperWorkflow.__new__(PaperWorkflow)

        eval_result = MagicMock()
        eval_result.validation_tier = TIER_REPLAY_VALIDATED
        eval_result.score_breakdown = MagicMock(total_score=0.80)
        gate_report = MagicMock()
        gate_report.hard_gates_pass = False
        gate_report.hard_gates = [MagicMock(name="net_pnl", passed=False)]
        eval_result.gate_report = gate_report

        eligible, reason = workflow.is_paper_eligible(eval_result)
        assert not eligible
        assert "gate" in reason.lower()


class TestPaperRunRecords:
    """Paper run records are created and persisted."""

    def test_start_paper_run_creates_record(self, tmp_path):
        from controllers.research.paper_workflow import PaperWorkflow, PaperArtifact
        workflow = PaperWorkflow(
            paper_runs_dir=tmp_path / "runs",
            paper_artifacts_dir=tmp_path / "artifacts",
        )
        artifact = PaperArtifact(
            artifact_id="art001",
            candidate_name="test-cand",
            experiment_run_id="run001",
            strategy_family="trend_continuation",
            template_id="trend_continuation_pullback",
            adapter_mode="pullback",
            pinned_parameters={"atr_period": 14},
            risk_budget={"per_trade_risk_pct": 0.5},
            expected_conditions="trending market",
            expected_bands={"sharpe_min": 0.6},
            validation_tier="replay_validated",
            composite_score=0.72,
            created_at="2026-03-26T00:00:00+00:00",
        )
        record = workflow.start_paper_run("test-cand", artifact)
        assert record.run_id
        assert record.status == "active"

        # Verify persisted
        loaded = workflow.get_run_record("test-cand", record.run_id)
        assert loaded is not None
        assert loaded.artifact_id == "art001"


class TestDivergenceDowngrade:
    """Divergence monitoring triggers downgrade or rejection."""

    def test_no_divergence_continues(self, tmp_path):
        from controllers.research.paper_workflow import PaperWorkflow, PaperRunRecord
        workflow = PaperWorkflow(
            paper_runs_dir=tmp_path / "runs",
            paper_artifacts_dir=tmp_path / "artifacts",
        )
        # Create a run record
        record = PaperRunRecord(
            run_id="run001",
            artifact_id="art001",
            candidate_name="test-cand",
            experiment_run_id="exp001",
            started_at="2026-03-26T00:00:00+00:00",
        )
        workflow._save_run_record(record)

        paper_metrics = {
            "timing_diff_bars": 1.0,
            "fill_quality_pct": 0.05,
            "slippage_mult": 1.2,
            "trade_count_pct": 0.1,
            "pnl_degradation_pct": 0.1,
        }
        report = workflow.check_divergence("test-cand", "run001", paper_metrics)
        assert report.recommended_action == "continue"
        assert not report.any_breached

    def test_multiple_breaches_trigger_reject(self, tmp_path):
        from controllers.research.paper_workflow import PaperWorkflow, PaperRunRecord
        workflow = PaperWorkflow(
            paper_runs_dir=tmp_path / "runs",
            paper_artifacts_dir=tmp_path / "artifacts",
        )
        record = PaperRunRecord(
            run_id="run002",
            artifact_id="art001",
            candidate_name="test-cand",
            experiment_run_id="exp001",
            started_at="2026-03-26T00:00:00+00:00",
        )
        workflow._save_run_record(record)

        # Breach 3 dimensions
        paper_metrics = {
            "timing_diff_bars": 20.0,  # band=5
            "fill_quality_pct": 0.80,  # band=0.25
            "slippage_mult": 10.0,     # band=2.5
            "pnl_degradation_pct": 0.1,
        }
        report = workflow.check_divergence("test-cand", "run002", paper_metrics)
        assert report.recommended_action == "reject"
        assert report.any_breached

        # Record should be updated
        updated = workflow.get_run_record("test-cand", "run002")
        assert updated.status == "reject"

    def test_single_breach_triggers_downgrade(self, tmp_path):
        from controllers.research.paper_workflow import PaperWorkflow, PaperRunRecord
        workflow = PaperWorkflow(
            paper_runs_dir=tmp_path / "runs",
            paper_artifacts_dir=tmp_path / "artifacts",
        )
        record = PaperRunRecord(
            run_id="run003",
            artifact_id="art001",
            candidate_name="test-cand",
            experiment_run_id="exp001",
            started_at="2026-03-26T00:00:00+00:00",
        )
        workflow._save_run_record(record)

        paper_metrics = {
            "timing_diff_bars": 2.0,   # ok
            "fill_quality_pct": 0.60,  # breached (band=0.25)
            "slippage_mult": 1.2,      # ok
        }
        report = workflow.check_divergence("test-cand", "run003", paper_metrics)
        assert report.recommended_action == "downgrade"
        assert len(report.breach_reasons) == 1


# ---------------------------------------------------------------------------
# 7.4 API regression tests — richer candidate detail, leaderboard
# ---------------------------------------------------------------------------

class TestResearchApiStructure:
    """API builder functions produce expected response shapes."""

    def test_scan_candidates_returns_governed_fields(self, tmp_path):
        """_scan_candidates includes strategy_family and validation_tier."""
        import services.common.research_api as api_mod
        original = api_mod._CANDIDATES_DIR

        # Write a governed candidate
        api_mod._CANDIDATES_DIR = tmp_path / "candidates"
        api_mod._CANDIDATES_DIR.mkdir()
        api_mod._LIFECYCLE_DIR = tmp_path / "lifecycle"
        api_mod._LIFECYCLE_DIR.mkdir()
        api_mod._EXPERIMENTS_DIR = tmp_path / "experiments"
        api_mod._EXPERIMENTS_DIR.mkdir()

        governed_path = api_mod._CANDIDATES_DIR / "governed.yml"
        governed_path.write_text(yaml.dump({
            "name": "governed",
            "hypothesis": "test",
            "adapter_mode": "pullback",
            "parameter_space": {},
            "entry_logic": "e",
            "exit_logic": "x",
            "base_config": {},
            "schema_version": 2,
            "strategy_family": "trend_continuation",
            "template_id": "trend_continuation_pullback",
        }))

        try:
            results = api_mod._scan_candidates()
            assert len(results) == 1
            r = results[0]
            assert r["strategy_family"] == "trend_continuation"
            assert r["schema_version"] == 2
            assert "validation_tier" in r
        finally:
            api_mod._CANDIDATES_DIR = original

    def test_leaderboard_sorts_replay_validated_first(self, tmp_path):
        """Leaderboard places replay_validated candidates before candle_only."""
        import services.common.research_api as api_mod

        original_candidates = api_mod._CANDIDATES_DIR
        original_lifecycle = api_mod._LIFECYCLE_DIR
        original_experiments = api_mod._EXPERIMENTS_DIR

        api_mod._CANDIDATES_DIR = tmp_path / "candidates"
        api_mod._CANDIDATES_DIR.mkdir()
        api_mod._LIFECYCLE_DIR = tmp_path / "lifecycle"
        api_mod._LIFECYCLE_DIR.mkdir()
        api_mod._EXPERIMENTS_DIR = tmp_path / "experiments"
        api_mod._EXPERIMENTS_DIR.mkdir()

        # Write two candidates
        for i, tier in enumerate([("candle-only-cand", "candle_only"), ("replay-cand", "replay_validated")]):
            name, validation_tier = tier
            (api_mod._CANDIDATES_DIR / f"{name}.yml").write_text(yaml.dump({
                "name": name,
                "hypothesis": "test",
                "adapter_mode": "atr_mm",
                "parameter_space": {},
                "entry_logic": "e",
                "exit_logic": "x",
                "base_config": {},
                "schema_version": 2,
                "strategy_family": "mean_reversion",
            }))
            # Write experiment with validation tier
            exp_path = api_mod._EXPERIMENTS_DIR / f"{name}.jsonl"
            exp_path.write_text(json.dumps({
                "run_id": f"run{i}",
                "candidate_name": name,
                "robustness_score": 0.70,
                "recommendation": "pass",
                "validation_tier": validation_tier,
            }) + "\n")

        try:
            leaderboard = api_mod._build_leaderboard()
            assert len(leaderboard) == 2
            # replay_validated must come first
            assert leaderboard[0]["name"] == "replay-cand"
            assert leaderboard[0]["category"] == "replay_validated"
            assert leaderboard[1]["category"] == "research_only"
        finally:
            api_mod._CANDIDATES_DIR = original_candidates
            api_mod._LIFECYCLE_DIR = original_lifecycle
            api_mod._EXPERIMENTS_DIR = original_experiments

    def test_get_candidate_detail_includes_gate_results(self, tmp_path):
        """Candidate detail response includes gate_results when available."""
        import services.common.research_api as api_mod

        original_candidates = api_mod._CANDIDATES_DIR
        original_lifecycle = api_mod._LIFECYCLE_DIR
        original_experiments = api_mod._EXPERIMENTS_DIR
        original_reports = api_mod._REPORTS_DIR
        original_paper_runs = api_mod._PAPER_RUNS_DIR

        api_mod._CANDIDATES_DIR = tmp_path / "candidates"
        api_mod._CANDIDATES_DIR.mkdir()
        api_mod._LIFECYCLE_DIR = tmp_path / "lifecycle"
        api_mod._LIFECYCLE_DIR.mkdir()
        api_mod._EXPERIMENTS_DIR = tmp_path / "experiments"
        api_mod._EXPERIMENTS_DIR.mkdir()
        api_mod._REPORTS_DIR = tmp_path / "reports"
        api_mod._REPORTS_DIR.mkdir()
        api_mod._PAPER_RUNS_DIR = tmp_path / "paper_runs"
        api_mod._PAPER_RUNS_DIR.mkdir()

        (api_mod._CANDIDATES_DIR / "test-cand.yml").write_text(yaml.dump({
            "name": "test-cand",
            "hypothesis": "test",
            "adapter_mode": "atr_mm",
            "parameter_space": {},
            "entry_logic": "e",
            "exit_logic": "x",
            "base_config": {},
            "schema_version": 2,
            "strategy_family": "mean_reversion",
        }))
        gate_results = {"hard_gates_pass": True, "hard_gates": []}
        (api_mod._EXPERIMENTS_DIR / "test-cand.jsonl").write_text(json.dumps({
            "run_id": "run001",
            "candidate_name": "test-cand",
            "robustness_score": 0.72,
            "gate_results": gate_results,
            "validation_tier": "candle_only",
        }) + "\n")

        try:
            detail = api_mod._get_candidate_detail("test-cand")
            assert detail is not None
            assert detail["gate_results"] is not None
            assert detail["gate_results"]["hard_gates_pass"] is True
            assert detail["validation_tier"] == "candle_only"
            assert detail["strategy_family"] == "mean_reversion"
        finally:
            api_mod._CANDIDATES_DIR = original_candidates
            api_mod._LIFECYCLE_DIR = original_lifecycle
            api_mod._EXPERIMENTS_DIR = original_experiments
            api_mod._REPORTS_DIR = original_reports
            api_mod._PAPER_RUNS_DIR = original_paper_runs


# ---------------------------------------------------------------------------
# Family registry tests
# ---------------------------------------------------------------------------

class TestFamilyRegistry:
    """Family registry provides correct bounds and templates."""

    def test_all_phase_one_families_registered(self):
        from controllers.research.family_registry import FAMILY_REGISTRY
        expected = {
            "trend_continuation", "trend_pullback", "compression_breakout",
            "mean_reversion", "regime_conditioned_momentum", "funding_dislocation",
        }
        assert set(FAMILY_REGISTRY.keys()) == expected

    def test_get_family_returns_correct_type(self):
        from controllers.research.family_registry import get_family, StrategyFamily
        family = get_family("trend_continuation")
        assert isinstance(family, StrategyFamily)
        assert family.name == "trend_continuation"

    def test_get_family_returns_none_for_unknown(self):
        from controllers.research.family_registry import get_family
        assert get_family("nonexistent") is None

    def test_is_supported_family(self):
        from controllers.research.family_registry import is_supported_family
        assert is_supported_family("mean_reversion")
        assert not is_supported_family("liquidation_cascade")

    def test_is_phase_one_unsupported(self):
        from controllers.research.family_registry import is_phase_one_unsupported
        assert is_phase_one_unsupported("liquidation_cascade")
        assert not is_phase_one_unsupported("trend_continuation")

    def test_funding_dislocation_requires_funding_data(self):
        from controllers.research.family_registry import get_family
        family = get_family("funding_dislocation")
        assert "funding" in family.required_data

    def test_family_has_templates(self):
        from controllers.research.family_registry import get_family
        family = get_family("mean_reversion")
        assert len(family.templates) >= 1
        # Templates were renamed to enforce regime gate requirement
        template = family.get_template("mean_reversion_zscore_regime_gated")
        assert template is not None
        assert template.template_id == "mean_reversion_zscore_regime_gated"

    def test_bounds_check_rejects_out_of_range_value(self):
        from controllers.research.family_registry import get_family
        family = get_family("trend_continuation")
        violations = family.check_bounds({"trend_window": [5, 10]})  # below 20
        assert violations

    def test_bounds_check_passes_in_range_values(self):
        from controllers.research.family_registry import get_family
        family = get_family("trend_continuation")
        violations = family.check_bounds({"trend_window": [50, 100, 150]})
        assert not violations

    def test_monotonicity_check_rejects_fast_ge_slow(self):
        from controllers.research.family_registry import get_family
        family = get_family("trend_continuation")
        violations = family.check_monotonicity({"fast_ema": [100], "slow_ema": [50]})
        assert violations


# ---------------------------------------------------------------------------
# Family registry phase 2 — basis_carry, relative_value, mean_reversion gate
# ---------------------------------------------------------------------------

class TestBasisCarryFamily:
    """basis_carry family definitions and constraint enforcement."""

    def test_basis_carry_registered(self):
        from controllers.research.family_registry import FAMILY_REGISTRY
        assert "basis_carry" in FAMILY_REGISTRY

    def test_basis_carry_requires_funding_and_spot(self):
        from controllers.research.family_registry import get_family
        family = get_family("basis_carry")
        assert "funding" in family.required_data
        assert "spot" in family.required_data

    def test_basis_carry_has_three_templates(self):
        from controllers.research.family_registry import get_family
        family = get_family("basis_carry")
        assert len(family.templates) == 3
        ids = {t.template_id for t in family.templates}
        assert "basis_carry_funding_yield" in ids
        assert "basis_carry_delta_neutral_grid" in ids
        assert "basis_carry_semi_directional" in ids

    def test_basis_carry_hedge_ratio_bounds(self):
        from controllers.research.family_registry import get_family
        family = get_family("basis_carry")
        # Hedge ratio must be in [0.80, 1.20]
        violations = family.check_bounds({"hedge_ratio": [0.5]})  # below 0.80
        assert violations
        violations_ok = family.check_bounds({"hedge_ratio": [0.95, 1.0, 1.05]})
        assert not violations_ok

    def test_basis_carry_lower_risk_budget_than_directional(self):
        from controllers.research.family_registry import get_family
        carry = get_family("basis_carry")
        directional = get_family("trend_continuation")
        # Carry strategies have lower max per-trade risk
        assert carry.per_trade_risk_max_pct < directional.per_trade_risk_max_pct

    def test_basis_carry_funding_threshold_bounds(self):
        from controllers.research.family_registry import get_family
        family = get_family("basis_carry")
        # funding_threshold must be within [0.0001, 0.01]
        violations = family.check_bounds({"funding_threshold": [0.05]})  # above 0.01
        assert violations
        violations_ok = family.check_bounds({"funding_threshold": [0.0005, 0.001]})
        assert not violations_ok

    def test_basis_carry_neutral_template_retrievable(self):
        from controllers.research.family_registry import get_family
        family = get_family("basis_carry")
        t = family.get_template("basis_carry_funding_yield")
        assert t is not None
        assert t.template_id == "basis_carry_funding_yield"

    def test_basis_carry_validator_rejects_missing_required_data(self, tmp_path):
        """Validator raises when basis_carry candidate omits funding or spot."""
        import yaml as _yaml
        from controllers.research.candidate_validator import (
            CandidateValidationError,
            validate_candidate,
        )
        data = {
            "name": "carry-no-data-v1",
            "hypothesis": "Carry test",
            "adapter_mode": "simple",
            "parameter_space": {},
            "search_space": {"funding_threshold": [0.0005], "hedge_ratio": [1.0], "holding_period": [16]},
            "entry_logic": "Carry entry",
            "exit_logic": "Carry exit",
            "base_config": {
                "strategy_class": "simple",
                "strategy_config": {},
                "data_source": {"exchange": "bitget", "pair": "BTC-USDT", "resolution": "15m", "instrument_type": "perp"},
                "initial_equity": "500",
            },
            "lifecycle": "candidate",
            "schema_version": 2,
            "strategy_family": "basis_carry",
            "template_id": "basis_carry_funding_yield",
            "required_data": ["spot"],  # missing "funding"
        }
        path = tmp_path / "carry.yml"
        path.write_text(_yaml.dump(data))
        c = StrategyCandidate.from_yaml(path)
        with pytest.raises(CandidateValidationError, match="funding"):
            validate_candidate(c)


class TestRelativeValueFamily:
    """relative_value family definitions and constraint enforcement."""

    def test_relative_value_registered(self):
        from controllers.research.family_registry import FAMILY_REGISTRY
        assert "relative_value" in FAMILY_REGISTRY

    def test_relative_value_requires_multi_asset(self):
        from controllers.research.family_registry import get_family
        family = get_family("relative_value")
        assert "multi_asset" in family.required_data

    def test_relative_value_has_three_templates(self):
        from controllers.research.family_registry import get_family
        family = get_family("relative_value")
        assert len(family.templates) == 3
        ids = {t.template_id for t in family.templates}
        assert "relative_value_btc_eth_ratio" in ids
        assert "relative_value_spot_perp_spread" in ids
        assert "relative_value_cross_venue_basis" in ids

    def test_relative_value_entry_zscore_bounds(self):
        from controllers.research.family_registry import get_family
        family = get_family("relative_value")
        violations = family.check_bounds({"entry_zscore": [0.5]})  # below 1.0
        assert violations
        violations_ok = family.check_bounds({"entry_zscore": [1.5, 2.0, 2.5]})
        assert not violations_ok

    def test_relative_value_hedge_ratio_wider_bounds(self):
        from controllers.research.family_registry import get_family
        family = get_family("relative_value")
        # RV allows hedge ratios up to 2.0 (wider than carry)
        violations = family.check_bounds({"hedge_ratio": [1.5, 2.0]})
        assert not violations
        violations_out = family.check_bounds({"hedge_ratio": [2.5]})
        assert violations_out

    def test_relative_value_ratio_template_retrievable(self):
        from controllers.research.family_registry import get_family
        family = get_family("relative_value")
        t = family.get_template("relative_value_btc_eth_ratio")
        assert t is not None

    def test_relative_value_validator_rejects_missing_multi_asset(self, tmp_path):
        """Validator raises when relative_value candidate omits multi_asset."""
        import yaml as _yaml
        from controllers.research.candidate_validator import (
            CandidateValidationError,
            validate_candidate,
        )
        data = {
            "name": "rv-no-data-v1",
            "hypothesis": "RV test",
            "adapter_mode": "simple",
            "parameter_space": {},
            "search_space": {"entry_zscore": [1.5, 2.0], "zscore_lookback": [50, 100], "hedge_ratio": [1.0]},
            "entry_logic": "RV entry",
            "exit_logic": "RV exit",
            "base_config": {
                "strategy_class": "simple",
                "strategy_config": {},
                "data_source": {"exchange": "bitget", "pair": "BTC-USDT", "resolution": "15m", "instrument_type": "perp"},
                "initial_equity": "500",
            },
            "lifecycle": "candidate",
            "schema_version": 2,
            "strategy_family": "relative_value",
            "template_id": "relative_value_btc_eth_ratio",
            "required_data": [],  # missing "multi_asset"
        }
        path = tmp_path / "rv.yml"
        path.write_text(_yaml.dump(data))
        c = StrategyCandidate.from_yaml(path)
        with pytest.raises(CandidateValidationError, match="multi_asset"):
            validate_candidate(c)


class TestMeanReversionRegimeGate:
    """mean_reversion family MUST have a regime gate — enforced at validation."""

    def _make_mr_candidate(self, tmp_path: Path, with_regime: bool) -> "StrategyCandidate":
        import yaml as _yaml
        search: dict = {"zscore_window": [15, 20, 30], "zscore_threshold": [1.5, 2.0]}
        if with_regime:
            search["regime_window"] = [50, 100, 150]
        data = {
            "name": "mr-test-v1",
            "hypothesis": "Mean reversion on BTC",
            "adapter_mode": "atr_mm",
            "parameter_space": {"atr_period": [14]},
            "search_space": search,
            "entry_logic": "Enter on z-score extreme",
            "exit_logic": "Exit on mean reversion",
            "base_config": {
                "strategy_class": "atr_mm",
                "strategy_config": {},
                "data_source": {
                    "exchange": "bitget",
                    "pair": "BTC-USDT",
                    "resolution": "15m",
                    "instrument_type": "perp",
                },
                "initial_equity": "500",
            },
            "lifecycle": "candidate",
            "schema_version": 2,
            "strategy_family": "mean_reversion",
            "template_id": "mean_reversion_zscore_regime_gated",
            "required_data": [],
        }
        path = tmp_path / "mr.yml"
        path.write_text(_yaml.dump(data))
        return StrategyCandidate.from_yaml(path)

    def test_mean_reversion_without_regime_gate_raises(self, tmp_path):
        from controllers.research.candidate_validator import (
            CandidateValidationError,
            validate_candidate,
        )
        c = self._make_mr_candidate(tmp_path, with_regime=False)
        with pytest.raises(CandidateValidationError, match="regime"):
            validate_candidate(c)

    def test_mean_reversion_with_regime_window_passes(self, tmp_path):
        from controllers.research.candidate_validator import validate_candidate
        c = self._make_mr_candidate(tmp_path, with_regime=True)
        # Should not raise
        validate_candidate(c)

    def test_mean_reversion_family_has_regime_gate_required_flag(self):
        from controllers.research.family_registry import get_family
        family = get_family("mean_reversion")
        assert family.regime_gate_required is True

    def test_trend_continuation_has_no_regime_gate_required(self):
        from controllers.research.family_registry import get_family
        family = get_family("trend_continuation")
        assert family.regime_gate_required is False

    def test_mean_reversion_regime_gated_templates_have_regime_window(self):
        from controllers.research.family_registry import get_family
        family = get_family("mean_reversion")
        for template in family.templates:
            assert "regime_window" in template.required_params, (
                f"Template '{template.template_id}' must require regime_window"
            )

    def _make_mr_candidate_with_param(self, tmp_path: Path, param_name: str) -> "StrategyCandidate":
        import yaml as _yaml
        data = {
            "name": "mr-param-test-v1",
            "hypothesis": "Mean reversion gated test",
            "adapter_mode": "atr_mm",
            "parameter_space": {},
            "search_space": {"zscore_threshold": [2.0], param_name: [50, 100]},
            "entry_logic": "Enter on z-score",
            "exit_logic": "Exit on mean",
            "base_config": {
                "strategy_class": "atr_mm",
                "strategy_config": {},
                "data_source": {"exchange": "bitget", "pair": "BTC-USDT", "resolution": "15m", "instrument_type": "perp"},
                "initial_equity": "500",
            },
            "lifecycle": "candidate",
            "schema_version": 2,
            "strategy_family": "mean_reversion",
            "template_id": "mean_reversion_zscore_regime_gated",
            "required_data": [],
        }
        path = tmp_path / f"mr_{param_name}.yml"
        path.write_text(_yaml.dump(data))
        return StrategyCandidate.from_yaml(path)

    def test_htf_ema_passes_regime_gate(self, tmp_path):
        from controllers.research.candidate_validator import validate_candidate
        c = self._make_mr_candidate_with_param(tmp_path, "htf_ema")
        validate_candidate(c)  # should not raise

    def test_trend_filter_passes_regime_gate(self, tmp_path):
        from controllers.research.candidate_validator import validate_candidate
        c = self._make_mr_candidate_with_param(tmp_path, "trend_filter_period")
        validate_candidate(c)  # should not raise

    def test_non_mr_family_unaffected_without_regime_param(self, tmp_path):
        """trend_continuation without any regime param must not raise CandidateValidationError."""
        import yaml as _yaml
        from controllers.research.candidate_validator import validate_candidate
        data = {
            "name": "tc-no-regime-v1",
            "hypothesis": "Trend continuation",
            "adapter_mode": "pullback",
            "parameter_space": {},
            "search_space": {"pullback_depth_atr": [0.5, 1.0], "trend_ema": [100], "stop_atr_mult": [1.5]},
            "entry_logic": "Pullback entry",
            "exit_logic": "Pullback exit",
            "base_config": {
                "strategy_class": "pullback",
                "strategy_config": {},
                "data_source": {"exchange": "bitget", "pair": "BTC-USDT", "resolution": "15m", "instrument_type": "perp"},
                "initial_equity": "500",
            },
            "lifecycle": "candidate",
            "schema_version": 2,
            "strategy_family": "trend_continuation",
            "template_id": "trend_continuation_pullback",
            "required_data": [],
        }
        path = tmp_path / "tc_no_regime.yml"
        path.write_text(_yaml.dump(data))
        c = StrategyCandidate.from_yaml(path)
        validate_candidate(c)  # must not raise


class TestMeanReversionTemplateRename:
    """Verify old template IDs are gone and new regime-gated IDs exist."""

    def test_gated_zscore_template_exists(self):
        from controllers.research.family_registry import get_family
        family = get_family("mean_reversion")
        assert family.get_template("mean_reversion_zscore_regime_gated") is not None

    def test_gated_mm_template_exists(self):
        from controllers.research.family_registry import get_family
        family = get_family("mean_reversion")
        assert family.get_template("mean_reversion_mm_regime_gated") is not None

    def test_old_zscore_template_id_returns_none(self):
        from controllers.research.family_registry import get_family
        family = get_family("mean_reversion")
        assert family.get_template("mean_reversion_zscore") is None

    def test_old_mm_template_id_returns_none(self):
        from controllers.research.family_registry import get_family
        family = get_family("mean_reversion")
        assert family.get_template("mean_reversion_mm") is None

    def test_regime_window_in_zscore_template_required_params(self):
        from controllers.research.family_registry import get_family
        family = get_family("mean_reversion")
        t = family.get_template("mean_reversion_zscore_regime_gated")
        assert "regime_window" in t.required_params
