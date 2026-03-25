"""Autonomous LLM-driven strategy exploration session.

Generates → evaluates → revises strategy candidates in a loop until
``max_iterations`` is reached or a candidate passes the robustness
scoring threshold.
"""
from __future__ import annotations

import json
import logging
import re
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from controllers.backtesting.adapter_registry import ADAPTER_REGISTRY
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

_KNOWN_ADAPTER_MODES = frozenset(ADAPTER_REGISTRY.keys())

logger = logging.getLogger(__name__)

_DEFAULT_OUTPUT_DIR = "hbot/data/research/explorations"
_DEFAULT_REPORTS_DIR = "hbot/data/research/reports"
_DEFAULT_EXPERIMENTS_DIR = "hbot/data/research/experiments"
_DEFAULT_LIFECYCLE_DIR = "hbot/data/research/lifecycle"

_MAX_PARSE_RETRIES = 1

PARSE_RETRY_PROMPT = """\
Your previous response could not be parsed as valid YAML.

**Error:** {error}

Please respond with exactly ONE valid YAML block wrapped in \
```yaml ... ``` code fences. Ensure all strings are properly quoted, \
lists use bracket syntax, and the block conforms to the \
StrategyCandidate schema. Do not include any text outside the fences.
"""


@dataclass
class SessionConfig:
    """Configuration for a single exploration session."""

    provider: str = "anthropic"
    max_iterations: int = 5
    temperature: float = 0.7
    temperature_decay: float = 0.05
    explore_ratio: float = 0.6
    target_instrument: str = "BTC-USDT"
    target_exchange: str = "bitget"
    resolution: str = "15m"
    step_interval_s: int = 900
    available_adapters: list[str] = field(default_factory=lambda: [
        "atr_mm", "atr_mm_v2", "smc_mm", "combo_mm",
        "pullback", "pullback_v2", "momentum_scalper",
        "directional_mm", "simple", "ta_composite",
    ])
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
    adapter_mode: str = ""
    duration_s: float = 0.0


@dataclass
class SessionResult:
    """Result of a complete exploration session."""

    iterations: list[IterationRecord] = field(default_factory=list)
    best_observed_score: float = 0.0
    best_observed_candidate: str = ""
    best_recommendation: str = ""
    total_tokens_used: int = 0
    session_dir: str = ""
    adapters_explored: list[str] = field(default_factory=list)
    unique_hypotheses: int = 0


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
        new_adapter_description=data.get("new_adapter_description", ""),
    )


def _build_market_context(config: SessionConfig) -> str:
    """Build market context summary, injecting real data when available."""
    lines = [
        f"- Instrument: {config.target_instrument} perpetual",
        f"- Exchange: {config.target_exchange}",
        f"- Resolution: {config.resolution} bars",
        f"- Simulation step interval: {config.step_interval_s}s",
    ]
    if config.extra_market_context:
        lines.append(f"- Extra: {config.extra_market_context}")

    try:
        from controllers.backtesting.data_catalog import DataCatalog
        catalog = DataCatalog()
        entry = catalog.find(config.target_exchange, config.target_instrument, config.resolution)
        if entry:
            from pathlib import Path as _Path
            from controllers.backtesting.data_store import load_candles_window

            file_path = entry.get("file_path", "")
            end_ms = entry.get("end_ms", 0)
            start_ms = entry.get("start_ms", 0)
            row_count = entry.get("row_count", 0)

            from datetime import datetime, UTC as _UTC
            start_dt = datetime.fromtimestamp(start_ms / 1000, tz=_UTC).strftime("%Y-%m-%d")
            end_dt = datetime.fromtimestamp(end_ms / 1000, tz=_UTC).strftime("%Y-%m-%d")
            lines.append(f"- Available data window: {start_dt} to {end_dt} ({row_count:,} bars)")

            tail_window_ms = 24 * 60 * 60 * 1000
            tail_start = max(start_ms, end_ms - tail_window_ms)
            candles = load_candles_window(_Path(file_path), start_ms=tail_start, end_ms=end_ms)

            if len(candles) >= 60:
                closes = [float(c.close) for c in candles]
                highs = [float(c.high) for c in candles]
                lows = [float(c.low) for c in candles]
                volumes = [float(c.volume) for c in candles]
                last_price = closes[-1]
                price_24h_ago = closes[0]
                change_pct = ((last_price - price_24h_ago) / price_24h_ago) * 100

                true_ranges = []
                for i in range(1, len(candles)):
                    hl = highs[i] - lows[i]
                    hc = abs(highs[i] - closes[i - 1])
                    lc = abs(lows[i] - closes[i - 1])
                    true_ranges.append(max(hl, hc, lc))
                atr_14 = sum(true_ranges[-14:]) / min(14, len(true_ranges[-14:]))

                ema_20 = closes[0]
                alpha = 2 / 21
                for c in closes[1:]:
                    ema_20 = alpha * c + (1 - alpha) * ema_20
                trend = "bullish" if last_price > ema_20 else "bearish"

                total_vol = sum(volumes)
                avg_vol = total_vol / len(volumes)

                high_24h = max(highs)
                low_24h = min(lows)
                range_pct = ((high_24h - low_24h) / low_24h) * 100

                lines.append(f"- Last price: {last_price:,.2f}")
                lines.append(f"- 24h change: {change_pct:+.2f}%")
                lines.append(f"- 24h range: {low_24h:,.2f} – {high_24h:,.2f} ({range_pct:.1f}%)")
                lines.append(
                    f"- ATR(14, {config.resolution}): {atr_14:,.2f} "
                    f"({atr_14/last_price*100:.3f}% of price)"
                )
                lines.append(f"- EMA(20) trend: {trend} (EMA={ema_20:,.2f})")
                lines.append(f"- Avg {config.resolution} volume: {avg_vol:,.0f}")
    except Exception as exc:
        logger.debug("Market context enrichment failed (non-fatal): %s", exc)

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
        pass  # Justification: report display is non-critical — return placeholder on any read error
    return "(report not available)"


def _format_backtest_metrics(result: EvaluationResult) -> str:
    """Format key backtest metrics into a concise summary for the LLM."""
    bt = result.backtest_result
    if not bt:
        return "(no backtest data)"
    lines = [
        f"  Total return: {bt.total_return_pct:+.2f}%",
        f"  Sharpe ratio: {bt.sharpe_ratio:.3f}",
        f"  Max drawdown: {bt.max_drawdown_pct:.2f}%",
        f"  Win rate: {bt.win_rate:.1%}",
        f"  Trades: {bt.closed_trade_count} (W:{bt.winning_trade_count} L:{bt.losing_trade_count})",
        f"  Profit factor: {bt.profit_factor:.2f}",
        f"  Expectancy/trade: {bt.expectancy_quote}",
        f"  Net PnL: {bt.realized_net_pnl_quote}",
        f"  Total fees: {bt.total_fees}",
    ]
    return "\n".join(lines)


def _format_top_candidates(top: list[tuple[str, float, str]]) -> str:
    """Format a ranked list of best candidates so far."""
    if not top:
        return "(no scored candidates yet)"
    lines = []
    for rank, (name, score, adapter) in enumerate(top, 1):
        lines.append(f"  {rank}. {name} (adapter={adapter}, score={score:.3f})")
    return "\n".join(lines)


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
        self._top_candidates: list[tuple[str, float, str]] = []
        self._adapters_used: list[str] = []

    def _effective_temperature(self, iteration: int, phase: str) -> float:
        """Decay temperature during exploit phase for more focused revisions."""
        base = self._config.temperature
        if phase == "exploit":
            decay_steps = iteration - self._explore_boundary
            return max(0.2, base - self._config.temperature_decay * decay_steps)
        return base

    def run(self) -> SessionResult:
        """Execute the full exploration session.

        Uses an explore-then-exploit strategy:
        - First ~60% of iterations: generate diverse candidates (explore)
        - Remaining ~40%: revise the best candidate found so far (exploit)
          with decaying temperature for increasingly focused revisions.
        """
        cfg = self._config
        session_dir = Path(cfg.output_dir)
        session_dir.mkdir(parents=True, exist_ok=True)
        session_start = time.monotonic()

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

        self._explore_boundary = max(1, int(cfg.max_iterations * cfg.explore_ratio))

        for i in range(1, cfg.max_iterations + 1):
            phase = "explore" if i <= self._explore_boundary else "exploit"
            temperature = self._effective_temperature(i, phase)
            logger.info(
                "=== Exploration iteration %d/%d [%s] (T=%.2f) ===",
                i, cfg.max_iterations, phase, temperature,
            )

            if phase == "explore":
                self._last_result = None
                self._last_candidate = None

            iter_start = time.monotonic()
            record = self._run_iteration(
                iteration=i,
                orchestrator=orchestrator,
                lifecycle_mgr=lifecycle_mgr,
                session_dir=session_dir,
                temperature=temperature,
            )
            record.duration_s = time.monotonic() - iter_start
            result.iterations.append(record)

            if record.adapter_mode and record.adapter_mode not in self._adapters_used:
                self._adapters_used.append(record.adapter_mode)

            if record.score is not None:
                self._top_candidates.append(
                    (record.candidate_name, record.score,
                     getattr(self._last_candidate, "adapter_mode", "?"))
                )
                self._top_candidates.sort(key=lambda t: t[1], reverse=True)
                self._top_candidates = self._top_candidates[:5]

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
        result.adapters_explored = list(self._adapters_used)
        result.unique_hypotheses = sum(
            1 for r in result.iterations
            if r.candidate_name not in ("<llm_error>", "<parse_error>")
        )

        elapsed = time.monotonic() - session_start
        logger.info(
            "Session complete: %d iterations (%.0fs), best=%.3f (%s), "
            "adapters=%s, tokens=%d",
            len(result.iterations),
            elapsed,
            result.best_observed_score,
            result.best_observed_candidate,
            result.adapters_explored,
            result.total_tokens_used,
        )

        self._save_session_summary(result, session_dir, elapsed)
        return result

    def _save_session_summary(
        self, result: SessionResult, session_dir: Path, elapsed_s: float,
    ) -> None:
        """Persist a machine-readable summary to the session directory."""
        summary = {
            "iterations": len(result.iterations),
            "elapsed_s": round(elapsed_s, 1),
            "best_score": result.best_observed_score,
            "best_candidate": result.best_observed_candidate,
            "best_recommendation": result.best_recommendation,
            "tokens_used": result.total_tokens_used,
            "adapters_explored": result.adapters_explored,
            "unique_hypotheses": result.unique_hypotheses,
            "top_candidates": [
                {"name": n, "score": round(s, 4), "adapter": a}
                for n, s, a in self._top_candidates
            ],
            "iteration_details": [
                {
                    "iter": r.iteration,
                    "name": r.candidate_name,
                    "action": r.action,
                    "adapter": r.adapter_mode,
                    "score": round(r.score, 4) if r.score is not None else None,
                    "recommendation": r.recommendation,
                    "duration_s": round(r.duration_s, 1),
                    "error": r.error,
                }
                for r in result.iterations
            ],
        }
        try:
            summary_path = session_dir / "session_summary.json"
            summary_path.write_text(json.dumps(summary, indent=2))
            logger.info("Session summary saved to %s", summary_path)
        except Exception as exc:
            logger.warning("Failed to save session summary: %s", exc)

    def _run_iteration(
        self,
        iteration: int,
        orchestrator: ExperimentOrchestrator,
        lifecycle_mgr: LifecycleManager,
        session_dir: Path,
        temperature: float | None = None,
    ) -> IterationRecord:
        action = "revise" if self._last_result and self._last_candidate else "generate"
        temp = temperature if temperature is not None else self._config.temperature

        raw_yaml, candidate, parse_error = self._call_and_parse(
            action, iteration, temp,
        )

        if raw_yaml is None:
            return IterationRecord(
                iteration=iteration,
                candidate_name="<llm_error>",
                candidate_yaml="",
                action=action,
                error=parse_error or "LLM call failed",
            )

        if candidate is None:
            self._rejection_history.append(
                f"[iter {iteration}] YAML parse error: {parse_error}"
            )
            return IterationRecord(
                iteration=iteration,
                candidate_name="<parse_error>",
                candidate_yaml=raw_yaml,
                action=action,
                error=f"YAML parse error: {parse_error}",
            )

        yaml_path = session_dir / f"iter_{iteration:02d}_{candidate.name}.yml"
        candidate.to_yaml(str(yaml_path))

        adapter = candidate.adapter_mode

        if adapter not in _KNOWN_ADAPTER_MODES:
            logger.info(
                "New adapter blueprint '%s' (adapter_mode=%s) — saved, skipping backtest.",
                candidate.name, adapter,
            )
            self._rejection_history.append(
                f"[iter {iteration}] '{candidate.name}' — blueprint saved "
                f"(new adapter_mode={adapter!r}, needs development)"
            )
            return IterationRecord(
                iteration=iteration,
                candidate_name=candidate.name,
                candidate_yaml=raw_yaml,
                action=action,
                score=None,
                recommendation="blueprint",
                adapter_mode=adapter,
            )

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
                adapter_mode=adapter,
            )

        score_bd = eval_result.score_breakdown
        score = score_bd.total_score if score_bd else 0.0
        recommendation = score_bd.recommendation if score_bd else "reject"

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

        self._last_result = eval_result
        self._last_candidate = candidate

        if recommendation in ("reject", "revise"):
            self._rejection_history.append(
                f"[iter {iteration}] '{candidate.name}' (adapter={adapter}) — "
                f"{recommendation} (score={score:.3f}, "
                f"weak={_weakest_components(eval_result)})"
            )

        return IterationRecord(
            iteration=iteration,
            candidate_name=candidate.name,
            candidate_yaml=raw_yaml,
            action=action,
            score=score,
            recommendation=recommendation,
            report_path=eval_result.report_path,
            adapter_mode=adapter,
        )

    def _call_and_parse(
        self,
        action: str,
        iteration: int,
        temperature: float,
    ) -> tuple[str | None, StrategyCandidate | None, str | None]:
        """Call the LLM, extract YAML, and parse; retry once on parse failure.

        Returns ``(raw_yaml, candidate, error_message)``.
        On LLM failure: ``(None, None, error_str)``.
        On parse failure after retries: ``(raw_yaml, None, error_str)``.
        """
        try:
            raw_yaml = self._call_llm(action, temperature)
        except Exception as e:
            logger.error("LLM call failed on iteration %d: %s", iteration, e)
            return None, None, str(e)

        for attempt in range(_MAX_PARSE_RETRIES + 1):
            try:
                candidate = _parse_candidate_yaml(raw_yaml)
                return raw_yaml, candidate, None
            except Exception as parse_err:
                if attempt < _MAX_PARSE_RETRIES:
                    logger.warning(
                        "Parse attempt %d failed (%s), retrying with correction prompt",
                        attempt + 1, parse_err,
                    )
                    try:
                        raw_yaml = self._retry_parse(raw_yaml, str(parse_err), temperature)
                    except Exception as retry_err:
                        logger.error("Retry LLM call failed: %s", retry_err)
                        return raw_yaml, None, f"Retry failed: {retry_err}"
                else:
                    logger.error(
                        "YAML parse failed on iteration %d after %d attempts: %s",
                        iteration, _MAX_PARSE_RETRIES + 1, parse_err,
                    )
                    return raw_yaml, None, str(parse_err)

        return raw_yaml, None, "Parse exhausted all retries"

    def _retry_parse(
        self, failed_yaml: str, error: str, temperature: float,
    ) -> str:
        """Send a corrective prompt to fix a YAML parse failure."""
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": f"```yaml\n{failed_yaml}\n```"},
            {"role": "assistant", "content": f"```yaml\n{failed_yaml}\n```"},
            {"role": "user", "content": PARSE_RETRY_PROMPT.format(error=error)},
        ]
        response = self._client.chat(messages, temperature=max(0.2, temperature - 0.2))
        return _extract_yaml_block(response)

    def _call_llm(self, action: str, temperature: float | None = None) -> str:
        cfg = self._config
        temp = temperature if temperature is not None else cfg.temperature
        market_context = _build_market_context(cfg)

        if action == "generate":
            rejection_block = ""
            if self._rejection_history:
                rejection_block = (
                    "**Previously rejected hypotheses** (do NOT repeat these):\n"
                    + "\n".join(f"- {r}" for r in self._rejection_history[-10:])
                    + "\n\n"
                )
            top_block = _format_top_candidates(self._top_candidates)
            if self._top_candidates:
                rejection_block += f"**Top candidates so far:**\n{top_block}\n\n"

            if self._adapters_used:
                untried = [
                    a for a in cfg.available_adapters
                    if a not in self._adapters_used
                ]
                if untried:
                    rejection_block += (
                        f"**Adapters not yet tried this session (prefer these):** "
                        f"{', '.join(untried)}\n\n"
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
                backtest_metrics=_format_backtest_metrics(self._last_result),
                top_candidates=_format_top_candidates(self._top_candidates),
                report_excerpt=_read_report_excerpt(self._last_result.report_path),
            )

        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_msg},
        ]

        response = self._client.chat(messages, temperature=temp)
        return _extract_yaml_block(response)
