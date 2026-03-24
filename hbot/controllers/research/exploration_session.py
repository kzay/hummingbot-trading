"""Autonomous LLM-driven strategy exploration session.

Generates → evaluates → revises strategy candidates in a loop until
``max_iterations`` is reached or a candidate passes the robustness
scoring threshold.
"""
from __future__ import annotations

import logging
import re
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from controllers.research import StrategyCandidate, StrategyLifecycle
from controllers.research.experiment_orchestrator import (
    EvaluationConfig,
    EvaluationResult,
    ExperimentOrchestrator,
)
from controllers.research.exploration_prompts import (
    GENERATE_PROMPT,
    REVISE_PROMPT,
    SYSTEM_PROMPT,
    YAML_SCHEMA_REFERENCE,
)
from controllers.research.lifecycle_manager import LifecycleManager
from controllers.research.llm_client import LlmClient

logger = logging.getLogger(__name__)

_DEFAULT_OUTPUT_DIR = "hbot/data/research/explorations"
_DEFAULT_REPORTS_DIR = "hbot/data/research/reports"
_DEFAULT_EXPERIMENTS_DIR = "hbot/data/research/experiments"
_DEFAULT_LIFECYCLE_DIR = "hbot/data/research/lifecycle"


@dataclass
class SessionConfig:
    """Configuration for a single exploration session."""

    provider: str = "anthropic"
    max_iterations: int = 5
    temperature: float = 0.7
    target_instrument: str = "BTC-USDT"
    target_exchange: str = "bitget"
    available_adapters: list[str] = field(default_factory=lambda: ["atr_mm", "simple", "candle"])
    extra_market_context: str = ""
    output_dir: str = _DEFAULT_OUTPUT_DIR
    reports_dir: str = _DEFAULT_REPORTS_DIR
    experiments_dir: str = _DEFAULT_EXPERIMENTS_DIR
    lifecycle_dir: str = _DEFAULT_LIFECYCLE_DIR
    skip_sweep: bool = False
    skip_walkforward: bool = False
    auto_lifecycle: bool = True


@dataclass
class IterationRecord:
    """Record of a single exploration iteration."""

    iteration: int
    candidate_name: str
    candidate_yaml: str
    action: str  # "generate" | "revise"
    score: float | None = None
    recommendation: str | None = None
    report_path: str = ""
    error: str | None = None


@dataclass
class SessionResult:
    """Result of a complete exploration session."""

    iterations: list[IterationRecord] = field(default_factory=list)
    best_observed_score: float = 0.0
    best_observed_candidate: str = ""
    best_recommendation: str = ""
    total_tokens_used: int = 0
    session_dir: str = ""


def _extract_yaml_block(text: str) -> str:
    """Pull the first ```yaml ... ``` fence from LLM output."""
    match = re.search(r"```(?:ya?ml)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    raise ValueError("No YAML code block found in LLM response")


def _parse_candidate_yaml(raw_yaml: str) -> StrategyCandidate:
    """Parse and validate a YAML string into a StrategyCandidate.

    Performs syntactic/schema validation only — semantic correctness
    (adapter existence, parameter ranges) is delegated to the
    ExperimentOrchestrator.
    """
    data = yaml.safe_load(raw_yaml)
    if not isinstance(data, dict):
        raise ValueError("YAML did not parse to a dict")

    required_fields = [
        "name", "hypothesis", "adapter_mode", "parameter_space",
        "entry_logic", "exit_logic", "base_config",
    ]
    missing = [f for f in required_fields if f not in data]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    lifecycle_str = data.pop("lifecycle", "candidate")
    lifecycle = StrategyLifecycle(lifecycle_str)

    return StrategyCandidate(
        name=data["name"],
        hypothesis=data["hypothesis"],
        adapter_mode=data["adapter_mode"],
        parameter_space=data.get("parameter_space", {}),
        entry_logic=data["entry_logic"],
        exit_logic=data["exit_logic"],
        base_config=data["base_config"],
        required_tests=data.get("required_tests", []),
        metadata=data.get("metadata", {}),
        lifecycle=lifecycle,
    )


def _build_market_context(config: SessionConfig) -> str:
    lines = [
        f"- Instrument: {config.target_instrument} perpetual",
        f"- Exchange: {config.target_exchange}",
        f"- Resolution: 1m bars",
    ]
    if config.extra_market_context:
        lines.append(f"- Extra: {config.extra_market_context}")
    return "\n".join(lines)


def _format_score_breakdown(result: EvaluationResult) -> str:
    if not result.score_breakdown:
        return "No score available"
    bd = result.score_breakdown
    lines = []
    for name, cs in bd.components.items():
        lines.append(f"  {name}: raw={cs.raw_value:.3f} norm={cs.normalised:.3f} "
                      f"weight={cs.weight:.2f} contrib={cs.weighted_contribution:.3f}")
    return "\n".join(lines)


def _weakest_components(result: EvaluationResult, n: int = 3) -> str:
    if not result.score_breakdown:
        return "N/A"
    sorted_comps = sorted(
        result.score_breakdown.components.items(),
        key=lambda kv: kv[1].normalised,
    )
    return ", ".join(f"{name} ({cs.normalised:.2f})" for name, cs in sorted_comps[:n])


def _read_report_excerpt(report_path: str, max_lines: int = 100) -> str:
    try:
        p = Path(report_path)
        if p.exists():
            lines = p.read_text().splitlines()[:max_lines]
            return "\n".join(lines)
    except Exception:
        pass
    return "(report not available)"


class ExplorationSession:
    """Drive the generate→evaluate→revise exploration loop."""

    def __init__(self, client: LlmClient, config: SessionConfig | None = None) -> None:
        self._client = client
        self._config = config or SessionConfig()
        self._system_prompt = SYSTEM_PROMPT.format(
            yaml_schema_reference=YAML_SCHEMA_REFERENCE,
        )
        self._rejection_history: list[str] = []
        self._last_result: EvaluationResult | None = None
        self._last_candidate: StrategyCandidate | None = None

    def run(self) -> SessionResult:
        """Execute the full exploration session."""
        cfg = self._config
        session_dir = Path(cfg.output_dir)
        session_dir.mkdir(parents=True, exist_ok=True)

        result = SessionResult(session_dir=str(session_dir))

        eval_config = EvaluationConfig(
            skip_sweep=cfg.skip_sweep,
            skip_walkforward=cfg.skip_walkforward,
            output_dir=cfg.reports_dir,
            experiments_dir=cfg.experiments_dir,
        )
        orchestrator = ExperimentOrchestrator(eval_config)
        lifecycle_mgr = LifecycleManager(
            lifecycle_dir=cfg.lifecycle_dir,
            experiments_dir=cfg.experiments_dir,
        )

        for i in range(1, cfg.max_iterations + 1):
            logger.info("=== Exploration iteration %d/%d ===", i, cfg.max_iterations)

            record = self._run_iteration(
                iteration=i,
                orchestrator=orchestrator,
                lifecycle_mgr=lifecycle_mgr,
                session_dir=session_dir,
            )
            result.iterations.append(record)

            if record.score is not None and record.score > result.best_observed_score:
                result.best_observed_score = record.score
                result.best_observed_candidate = record.candidate_name
                result.best_recommendation = record.recommendation or ""

            if record.recommendation == "pass":
                logger.info(
                    "Candidate '%s' passed with score %.3f — stopping early.",
                    record.candidate_name, record.score or 0,
                )
                break

        result.total_tokens_used = self._client.tokens_used
        logger.info(
            "Session complete: %d iterations, best=%.3f (%s), tokens=%d",
            len(result.iterations),
            result.best_observed_score,
            result.best_observed_candidate,
            result.total_tokens_used,
        )
        return result

    def _run_iteration(
        self,
        iteration: int,
        orchestrator: ExperimentOrchestrator,
        lifecycle_mgr: LifecycleManager,
        session_dir: Path,
    ) -> IterationRecord:
        action = "revise" if self._last_result and self._last_candidate else "generate"

        # Step 1: LLM call
        try:
            raw_yaml = self._call_llm(action)
        except Exception as e:
            logger.error("LLM call failed on iteration %d: %s", iteration, e)
            return IterationRecord(
                iteration=iteration,
                candidate_name="<llm_error>",
                candidate_yaml="",
                action=action,
                error=str(e),
            )

        # Step 2: Parse
        try:
            candidate = _parse_candidate_yaml(raw_yaml)
        except Exception as e:
            logger.error("YAML parse failed on iteration %d: %s", iteration, e)
            self._rejection_history.append(f"[iter {iteration}] YAML parse error: {e}")
            return IterationRecord(
                iteration=iteration,
                candidate_name="<parse_error>",
                candidate_yaml=raw_yaml,
                action=action,
                error=f"YAML parse error: {e}",
            )

        # Step 3: Save YAML
        yaml_path = session_dir / f"iter_{iteration:02d}_{candidate.name}.yml"
        candidate.to_yaml(str(yaml_path))

        # Step 4: Evaluate
        try:
            eval_result = orchestrator.evaluate(candidate)
        except Exception as e:
            logger.error("Evaluation failed for '%s': %s", candidate.name, e)
            tb = traceback.format_exc()
            self._rejection_history.append(
                f"[iter {iteration}] '{candidate.name}' — evaluation crash: {e}"
            )
            return IterationRecord(
                iteration=iteration,
                candidate_name=candidate.name,
                candidate_yaml=raw_yaml,
                action=action,
                error=f"Evaluation error: {e}\n{tb}",
            )

        score_bd = eval_result.score_breakdown
        score = score_bd.total_score if score_bd else 0.0
        recommendation = score_bd.recommendation if score_bd else "reject"

        # Step 5: Lifecycle transition (optional)
        if self._config.auto_lifecycle and score_bd:
            try:
                if recommendation == "reject":
                    lifecycle_mgr.transition(
                        candidate.name, "candidate", "rejected",
                        reason=f"exploration score {score:.3f} < 0.35",
                    )
                elif recommendation == "pass":
                    lifecycle_mgr.transition(
                        candidate.name, "candidate", "paper",
                        reason=f"exploration score {score:.3f} >= 0.55",
                    )
            except ValueError as ve:
                logger.warning("Lifecycle transition skipped: %s", ve)

        # Step 6: Update state for next iteration
        self._last_result = eval_result
        self._last_candidate = candidate

        if recommendation in ("reject", "revise"):
            self._rejection_history.append(
                f"[iter {iteration}] '{candidate.name}' — {recommendation} "
                f"(score={score:.3f}, weak={_weakest_components(eval_result)})"
            )

        return IterationRecord(
            iteration=iteration,
            candidate_name=candidate.name,
            candidate_yaml=raw_yaml,
            action=action,
            score=score,
            recommendation=recommendation,
            report_path=eval_result.report_path,
        )

    def _call_llm(self, action: str) -> str:
        cfg = self._config
        market_context = _build_market_context(cfg)

        if action == "generate":
            rejection_block = ""
            if self._rejection_history:
                rejection_block = (
                    "**Previously rejected hypotheses** (do NOT repeat these):\n"
                    + "\n".join(f"- {r}" for r in self._rejection_history)
                    + "\n\n"
                )
            user_msg = GENERATE_PROMPT.format(
                market_context=market_context,
                available_adapters=", ".join(cfg.available_adapters),
                rejection_history=rejection_block,
            )
        else:
            assert self._last_result is not None
            assert self._last_candidate is not None
            user_msg = REVISE_PROMPT.format(
                name=self._last_candidate.name,
                score=self._last_result.score_breakdown.total_score if self._last_result.score_breakdown else 0,
                recommendation=self._last_result.score_breakdown.recommendation if self._last_result.score_breakdown else "reject",
                weakest_components=_weakest_components(self._last_result),
                score_breakdown=_format_score_breakdown(self._last_result),
                report_excerpt=_read_report_excerpt(self._last_result.report_path),
            )

        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_msg},
        ]

        response = self._client.chat(messages, temperature=cfg.temperature)
        return _extract_yaml_block(response)
