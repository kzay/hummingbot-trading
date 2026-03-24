"""Tests for the LLM exploration session and related utilities.

All tests are lightweight — they mock the LLM client and the experiment
orchestrator so no real API calls or backtests are executed.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from controllers.research import StrategyCandidate
from controllers.research.exploration_prompts import (
    GENERATE_PROMPT,
    REVISE_PROMPT,
    SYSTEM_PROMPT,
    YAML_SCHEMA_REFERENCE,
)
from controllers.research.exploration_session import (
    ExplorationSession,
    IterationRecord,
    SessionConfig,
    SessionResult,
    _extract_yaml_block,
    _parse_candidate_yaml,
)
from controllers.research.llm_client import (
    AnthropicClient,
    LlmClient,
    OpenAIClient,
    _resolve_env,
    build_client,
)
from controllers.research.robustness_scorer import ComponentScore, ScoreBreakdown


SAMPLE_YAML = """\
name: test-hypothesis-v1
hypothesis: >-
  BTC-USDT shows reversion after spikes.
adapter_mode: candle
parameter_space:
  atr_mult: [1.5, 2.0, 2.5]
  tp_atr: [0.3, 0.5]
entry_logic: Enter long on dip.
exit_logic: Exit on profit target.
base_config:
  strategy_class: candle
  strategy_config:
    atr_period: 14
  data_source:
    exchange: bitget
    pair: BTC-USDT
    resolution: 1m
    instrument_type: perp
  initial_equity: "500"
  leverage: 1
  seed: 42
metadata:
  author: test
lifecycle: candidate
"""


class FakeLlmClient:
    """Mock LLM client that returns a fixed YAML response."""

    def __init__(self, yaml_content: str = SAMPLE_YAML) -> None:
        self.tokens_used: int = 0
        self._yaml = yaml_content
        self.call_count: int = 0

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.7) -> str:
        self.call_count += 1
        self.tokens_used += 100
        return f"Here is a strategy:\n\n```yaml\n{self._yaml}\n```\n"

    def count_tokens(self, text: str) -> int:
        return len(text) // 4


class TestExtractYamlBlock:
    def test_extracts_yaml_fence(self) -> None:
        text = "Some text\n```yaml\nkey: value\n```\nMore text"
        assert _extract_yaml_block(text) == "key: value"

    def test_extracts_yml_fence(self) -> None:
        text = "```yml\nfoo: bar\n```"
        assert _extract_yaml_block(text) == "foo: bar"

    def test_raises_on_no_fence(self) -> None:
        with pytest.raises(ValueError, match="No YAML code block"):
            _extract_yaml_block("just some text without yaml")


class TestParseCandidateYaml:
    def test_valid_yaml(self) -> None:
        candidate = _parse_candidate_yaml(SAMPLE_YAML)
        assert candidate.name == "test-hypothesis-v1"
        assert candidate.adapter_mode == "candle"
        assert len(candidate.parameter_space) == 2

    def test_missing_required_field(self) -> None:
        bad = "name: test\nhypothesis: foo\n"
        with pytest.raises(ValueError, match="Missing required fields"):
            _parse_candidate_yaml(bad)

    def test_non_dict_yaml(self) -> None:
        with pytest.raises(ValueError, match="did not parse to a dict"):
            _parse_candidate_yaml("- item1\n- item2")


class TestResolveEnv:
    def test_first_match_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VAR_A", "alpha")
        monkeypatch.setenv("VAR_B", "beta")
        assert _resolve_env(("VAR_A", "VAR_B")) == "alpha"

    def test_skips_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VAR_A", "")
        monkeypatch.setenv("VAR_B", "beta")
        assert _resolve_env(("VAR_A", "VAR_B")) == "beta"

    def test_returns_default(self) -> None:
        assert _resolve_env(("NONEXISTENT_X",), default="fallback") == "fallback"


class TestBuildClient:
    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            build_client("unsupported_provider")

    def test_anthropic_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("RESEARCH_LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        with pytest.raises(EnvironmentError, match="No Anthropic API key"):
            build_client("anthropic")

    def test_openai_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("RESEARCH_LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        with pytest.raises(EnvironmentError, match="No OpenAI API key"):
            build_client("openai")


class TestPromptTemplates:
    def test_system_prompt_has_placeholder(self) -> None:
        rendered = SYSTEM_PROMPT.format(yaml_schema_reference=YAML_SCHEMA_REFERENCE)
        assert "StrategyCandidate YAML Schema" in rendered
        assert "{yaml_schema_reference}" not in rendered

    def test_generate_prompt_renders(self) -> None:
        rendered = GENERATE_PROMPT.format(
            market_context="BTC-USDT perp",
            available_adapters="atr_mm, simple",
            rejection_history="",
        )
        assert "BTC-USDT perp" in rendered
        assert "atr_mm" in rendered

    def test_revise_prompt_renders(self) -> None:
        rendered = REVISE_PROMPT.format(
            name="test",
            score=0.42,
            recommendation="revise",
            weakest_components="fee_stress (0.10)",
            score_breakdown="oos_sharpe: 0.5",
            report_excerpt="# Report",
        )
        assert "0.420" in rendered
        assert "fee_stress" in rendered


class TestExplorationSession:
    def _make_score_breakdown(
        self, total: float = 0.6, recommendation: str = "pass"
    ) -> ScoreBreakdown:
        return ScoreBreakdown(
            total_score=total,
            components={
                "oos_sharpe": ComponentScore(1.0, 0.33, 0.25, 0.08),
                "oos_degradation": ComponentScore(0.8, 0.80, 0.20, 0.16),
            },
            recommendation=recommendation,
        )

    def _make_eval_result(
        self, name: str = "test", score: float = 0.6, rec: str = "pass"
    ) -> MagicMock:
        mock = MagicMock()
        mock.score_breakdown = self._make_score_breakdown(score, rec)
        mock.report_path = ""
        mock.candidate_name = name
        mock.run_id = "abc123"
        return mock

    @patch("controllers.research.exploration_session.ExperimentOrchestrator")
    @patch("controllers.research.exploration_session.LifecycleManager")
    def test_session_runs_and_returns_result(
        self, mock_lm_cls: MagicMock, mock_orch_cls: MagicMock, tmp_path: Path
    ) -> None:
        mock_orch = mock_orch_cls.return_value
        mock_orch.evaluate.return_value = self._make_eval_result(
            "test-hypothesis-v1", 0.6, "pass"
        )

        mock_lm = mock_lm_cls.return_value

        client = FakeLlmClient()
        config = SessionConfig(
            max_iterations=2,
            output_dir=str(tmp_path / "explorations"),
            reports_dir=str(tmp_path / "reports"),
            experiments_dir=str(tmp_path / "experiments"),
            lifecycle_dir=str(tmp_path / "lifecycle"),
            auto_lifecycle=False,
        )
        session = ExplorationSession(client, config)
        result = session.run()

        assert isinstance(result, SessionResult)
        assert len(result.iterations) >= 1
        assert result.best_observed_score == 0.6
        assert result.best_observed_candidate == "test-hypothesis-v1"
        assert result.total_tokens_used > 0

    @patch("controllers.research.exploration_session.ExperimentOrchestrator")
    @patch("controllers.research.exploration_session.LifecycleManager")
    def test_session_stops_on_pass(
        self, mock_lm_cls: MagicMock, mock_orch_cls: MagicMock, tmp_path: Path
    ) -> None:
        mock_orch = mock_orch_cls.return_value
        mock_orch.evaluate.return_value = self._make_eval_result(
            "test-hypothesis-v1", 0.65, "pass"
        )

        client = FakeLlmClient()
        config = SessionConfig(
            max_iterations=10,
            output_dir=str(tmp_path / "explorations"),
            reports_dir=str(tmp_path / "reports"),
            experiments_dir=str(tmp_path / "experiments"),
            lifecycle_dir=str(tmp_path / "lifecycle"),
            auto_lifecycle=False,
        )
        session = ExplorationSession(client, config)
        result = session.run()

        assert len(result.iterations) == 1
        assert result.best_recommendation == "pass"

    @patch("controllers.research.exploration_session.ExperimentOrchestrator")
    @patch("controllers.research.exploration_session.LifecycleManager")
    def test_session_handles_parse_error(
        self, mock_lm_cls: MagicMock, mock_orch_cls: MagicMock, tmp_path: Path
    ) -> None:
        client = FakeLlmClient(yaml_content="not: valid: yaml: [")
        config = SessionConfig(
            max_iterations=1,
            output_dir=str(tmp_path / "explorations"),
            reports_dir=str(tmp_path / "reports"),
            experiments_dir=str(tmp_path / "experiments"),
            lifecycle_dir=str(tmp_path / "lifecycle"),
            auto_lifecycle=False,
        )
        session = ExplorationSession(client, config)
        result = session.run()

        assert len(result.iterations) == 1
        assert result.iterations[0].error is not None

    @patch("controllers.research.exploration_session.ExperimentOrchestrator")
    @patch("controllers.research.exploration_session.LifecycleManager")
    def test_session_handles_eval_crash(
        self, mock_lm_cls: MagicMock, mock_orch_cls: MagicMock, tmp_path: Path
    ) -> None:
        mock_orch = mock_orch_cls.return_value
        mock_orch.evaluate.side_effect = RuntimeError("backtest engine failure")

        client = FakeLlmClient()
        config = SessionConfig(
            max_iterations=1,
            output_dir=str(tmp_path / "explorations"),
            reports_dir=str(tmp_path / "reports"),
            experiments_dir=str(tmp_path / "experiments"),
            lifecycle_dir=str(tmp_path / "lifecycle"),
            auto_lifecycle=False,
        )
        session = ExplorationSession(client, config)
        result = session.run()

        assert len(result.iterations) == 1
        assert "backtest engine failure" in (result.iterations[0].error or "")

    @patch("controllers.research.exploration_session.ExperimentOrchestrator")
    @patch("controllers.research.exploration_session.LifecycleManager")
    def test_rejected_candidate_tracked_as_best_if_highest(
        self, mock_lm_cls: MagicMock, mock_orch_cls: MagicMock, tmp_path: Path
    ) -> None:
        mock_orch = mock_orch_cls.return_value
        mock_orch.evaluate.return_value = self._make_eval_result(
            "test-hypothesis-v1", 0.30, "reject"
        )

        client = FakeLlmClient()
        config = SessionConfig(
            max_iterations=1,
            output_dir=str(tmp_path / "explorations"),
            reports_dir=str(tmp_path / "reports"),
            experiments_dir=str(tmp_path / "experiments"),
            lifecycle_dir=str(tmp_path / "lifecycle"),
            auto_lifecycle=False,
        )
        session = ExplorationSession(client, config)
        result = session.run()

        assert result.best_observed_score == 0.30
        assert result.best_observed_candidate == "test-hypothesis-v1"
        assert result.best_recommendation == "reject"

    def test_yaml_saved_to_session_dir(self, tmp_path: Path) -> None:
        with patch("controllers.research.exploration_session.ExperimentOrchestrator") as mock_orch_cls, \
             patch("controllers.research.exploration_session.LifecycleManager"):
            mock_orch = mock_orch_cls.return_value
            eval_mock = MagicMock()
            eval_mock.score_breakdown = self._make_score_breakdown(0.6, "pass")
            eval_mock.report_path = ""
            eval_mock.candidate_name = "test-hypothesis-v1"
            eval_mock.run_id = "x"
            mock_orch.evaluate.return_value = eval_mock

            client = FakeLlmClient()
            config = SessionConfig(
                max_iterations=1,
                output_dir=str(tmp_path / "explorations"),
                reports_dir=str(tmp_path / "reports"),
                experiments_dir=str(tmp_path / "experiments"),
                lifecycle_dir=str(tmp_path / "lifecycle"),
                auto_lifecycle=False,
            )
            session = ExplorationSession(client, config)
            session.run()

            yamls = list((tmp_path / "explorations").glob("*.yml"))
            assert len(yamls) == 1
            assert "test-hypothesis-v1" in yamls[0].name
