## Context

The strategy research lab (`hbot/controllers/research/`) provides a complete governance layer for strategy evaluation: `StrategyCandidate` YAML definitions, a 6-step `ExperimentOrchestrator` pipeline (backtest → sweep → walk-forward → robustness scoring → manifest → report), composite `RobustnessScorer` with configurable weights, `HypothesisRegistry` for immutable experiment manifests, `LifecycleManager` for promotion gates, and a `ReportGenerator` for Markdown evaluation reports. All of this is accessible via a CLI at `python -m controllers.research.evaluate`.

The bottleneck is hypothesis supply. Every candidate must be hand-authored as a YAML file with a falsifiable hypothesis, formal entry/exit logic, parameter space, and adapter mode reference. The user is not a quant — translating market intuitions into valid `StrategyCandidate` definitions is the hardest step. The research lab can evaluate candidates at volume, but there is no automated source of candidates to evaluate.

The backtesting stack provides 9 adapter modes via `ADAPTER_REGISTRY` (`atr_mm`, `atr_mm_v2`, `smc_mm`, `combo_mm`, `pullback`, `pullback_v2`, `momentum_scalper`, `directional_mm`, `simple`), each with its own config dataclass and parameter space. An LLM can be prompted with these modes, the YAML schema, and market context to generate valid candidates, then iteratively refine them based on rejection feedback from the robustness scorer.

## Goals / Non-Goals

**Goals:**

- Provide a thin LLM client abstraction that supports Anthropic and OpenAI APIs with runtime provider selection.
- Encode strategy research domain knowledge into prompt templates that enforce falsifiability, prohibit lookahead bias, and reference the exact `StrategyCandidate` YAML schema.
- Build an autonomous exploration loop that generates candidates via LLM, delegates evaluation to the existing `ExperimentOrchestrator`, and feeds rejection feedback back to the LLM for iterative revision.
- Deliver a CLI entry point (`explore_cli.py`) for launching exploration sessions with configurable iteration count, provider, market scope, and evaluation toggles.
- Produce reproducible session outputs: per-iteration candidate YAMLs, evaluation reports (via existing report pipeline), session summary, and JSONL conversation log.

**Non-Goals:**

- Modifying evaluation pipeline logic in existing research lab files (`__init__.py`, `experiment_orchestrator.py`, `robustness_scorer.py`, `hypothesis_registry.py`, `lifecycle_manager.py`, `report_generator.py`, `evaluate.py`). Minimal packaging/env integration edits to `pyproject.toml` and `.env.template` are allowed.
- Duplicating backtesting, scoring, report, or manifest logic — the exploration session delegates entirely to `ExperimentOrchestrator.evaluate()`.
- Adding adapter modes or changing `ADAPTER_REGISTRY`.
- Automatically promoting candidates to `promoted` — the exploration session captures recommendations and optionally transitions to `paper`, but never auto-promotes. Promotion requires manual gate review via `LifecycleManager`.
- Implementing fine-tuning, embeddings, RAG, or any ML pipeline — the LLM is used via standard chat completions only.
- Building a web UI or dashboard integration (future scope).
- Modifying production runtime code, `epp_v2_4.py`, or live connector code.

## Decisions

### D1: LLM client as `typing.Protocol` with factory pattern

**Choice**: Define `LlmClient` as a `typing.Protocol` with `chat(messages, temperature) -> str` and `count_tokens(text) -> int`. Concrete implementations `AnthropicClient` and `OpenAIClient` wrap their respective SDKs. A `build_client(provider: str) -> LlmClient` factory reads API keys from environment variables.

**Rationale**: The Protocol pattern avoids inheritance coupling and allows mock injection in tests. The factory centralises provider selection logic. Only `llm_client.py` imports LLM SDKs — all other modules depend on the `LlmClient` protocol, making provider swaps trivial. Adding a new provider (e.g., Google Gemini) requires only a new class and a factory entry.

### D2: Prompt templates as pure string constants, not Jinja or templated code

**Choice**: All prompts live in `exploration_prompts.py` as module-level string constants with `str.format()` placeholders (`{market_context}`, `{score_breakdown}`, etc.). No Jinja, no template engine, no codebase imports.

**Rationale**: String constants are greppable, testable, and have zero runtime dependencies. The placeholders are filled by `ExplorationSession` at call time. Jinja would add a dependency and indirection without benefit — the templates are short (< 200 lines total) and their structure is fixed. The `YAML_SCHEMA_REFERENCE` constant documents the exact `StrategyCandidate` fields so the LLM knows the required format without needing access to the Python dataclass.

### D3: Session loop delegates entirely to `ExperimentOrchestrator.evaluate()`

**Choice**: `ExplorationSession.run()` calls `ExperimentOrchestrator(eval_config).evaluate(candidate)` for each generated candidate. It does not call `BacktestHarness`, `SweepRunner`, `WalkForwardRunner`, `RobustnessScorer`, `HypothesisRegistry`, or `ReportGenerator` directly.

**Rationale**: The orchestrator already composes the full 6-step pipeline and returns `EvaluationResult` with `score_breakdown`, `report_path`, and `manifest`. Calling sub-components directly would duplicate orchestration logic and risk divergence. The exploration session is a consumer of `EvaluationResult`, not a parallel orchestrator.

### D4: LLM receives score breakdown + report excerpt as structured revision feedback

**Choice**: When a candidate is rejected or marked for revision, the session builds a feedback message containing: the candidate name, total robustness score, per-component scores (OOS Sharpe, degradation ratio, parameter stability, fee stress, regime stability, DSR), the recommendation, the two weakest components, and the first ~100 lines of the Markdown report.

**Rationale**: Raw Markdown reports can be 200+ lines — too long for efficient LLM context. The structured breakdown gives the LLM actionable information about what specifically failed. Highlighting the two weakest components focuses revision effort. Including a report excerpt provides additional context (e.g., specific Sharpe values, regime breakdowns) without overwhelming the context window.

### D5: YAML schema reference derived from `StrategyCandidate` fields, not duplicated code

**Choice**: `YAML_SCHEMA_REFERENCE` in `exploration_prompts.py` is a documentation string listing all required fields (`name`, `hypothesis`, `adapter_mode`, `parameter_space`, `entry_logic`, `exit_logic`, `base_config`) with descriptions and an example. It is derived from the `StrategyCandidate` dataclass and the `example_mean_reversion.yml` file, but does not import or reference them at runtime.

**Rationale**: The LLM needs a textual description of the YAML format, not Python code. Keeping the schema reference as a prompt constant makes it editable independently of the dataclass. If the dataclass evolves, the schema reference must be updated manually — this is acceptable because schema changes are rare and the research module has its own spec tests.

### D6: JSONL conversation log + Markdown session summary

**Choice**: Each exploration session produces two output files: a `conversation_log.jsonl` recording every LLM message exchange (role, content, timestamp, token count) and a `session_summary.md` with iteration outcomes, best score, and total token usage.

**Rationale**: JSONL for the conversation log mirrors the `HypothesisRegistry` format — append-only, diff-friendly, one JSON object per line. Markdown for the summary matches the report generator format and is human-readable. Together they provide full reproducibility: the JSONL can be replayed or analysed programmatically, while the summary gives a quick overview.

### D7: Environment variable strategy — compatibility-first with provider overrides

**Choice**: The LLM client reads API keys in this order: provider-specific (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) → research-scoped generic (`RESEARCH_LLM_API_KEY`) → generic fallback (`LLM_API_KEY`). Model name follows the same pattern: `ANTHROPIC_MODEL` / `OPENAI_MODEL` → `RESEARCH_LLM_MODEL` → hardcoded defaults (`claude-sonnet-4-20250514` / `gpt-4o`). The `.env.template` gains a `# ── Research LLM Exploration ──` section with `RESEARCH_LLM_API_KEY` and `RESEARCH_LLM_MODEL`. Existing `LLM_API_KEY` / `LLM_FALLBACK_API_KEY` entries used by the sentiment strategy are not modified.

**Rationale**: Compatibility-first avoids churn on the existing `.env.template`. Users with a single key can set `RESEARCH_LLM_API_KEY` and be done. Users with multi-provider setups can override per-provider. The three-tier lookup keeps the client self-sufficient without importing config from other modules.

### D8: Lifecycle mutation is optional and limited to `paper`

**Choice**: After evaluation, the exploration session may optionally transition a passing candidate from `candidate` → `paper` using `LifecycleManager`, matching the existing `evaluate.py` behavior. The session never transitions to `promoted`. The best observed candidate is identified by highest `score_breakdown.total_score` regardless of lifecycle outcome — a rejected candidate can still be the highest-scoring one.

**Rationale**: The existing `evaluate.py` only performs `reject → rejected` and `pass → paper` transitions. Auto-promoting would bypass the human gate review that `PromotionGates` is designed to enforce. Separating "best observed score" from "lifecycle recommendation" avoids confusion — the session report clearly distinguishes them.

### D9: Session config exposes research directory paths explicitly

**Choice**: `SessionConfig` includes `reports_dir`, `experiments_dir`, and `lifecycle_dir` fields alongside `output_dir`. These default to the same paths used by `ExperimentOrchestrator` and `LifecycleManager` (`hbot/data/research/reports`, `hbot/data/research/experiments`, `hbot/data/research/lifecycle`). The CLI exposes `--reports-dir`, `--experiments-dir`, and `--lifecycle-dir` flags.

**Rationale**: The existing research stack uses separate directory roots for reports, experiments, and lifecycle state. Hardcoding paths or relying on CWD would break when the CLI is invoked from different directories. Passing paths explicitly through `SessionConfig` → `EvaluationConfig` keeps the data layout consistent with `evaluate.py` usage.

## Risks / Trade-offs

- **[Risk] LLM generates syntactically valid YAML but semantically invalid candidates** (e.g., references a non-existent `adapter_mode`, uses parameter names that don't match the adapter config) → Mitigation: the system prompt lists available adapter modes from `ADAPTER_REGISTRY`. The `StrategyCandidate.from_yaml()` validation catches missing required fields. The `ExperimentOrchestrator` will fail fast at step 1 (verification backtest) if the adapter mode or config is wrong. Parse retry logic gives the LLM a second chance with the error message.

- **[Risk] LLM hallucinates strategy logic that looks plausible but contains lookahead bias** → Mitigation: the system prompt explicitly prohibits lookahead patterns. More importantly, the `VisibleCandleRow` guard in the backtest harness physically prevents reading future OHLCV values during tick processing. The walk-forward evaluation with OOS windows catches in-sample-only performance. The robustness scorer penalises IS/OOS degradation.

- **[Risk] API cost escalation from long sessions** → Mitigation: `max_iterations` caps the loop (default 5). Cumulative `tokens_used` is tracked per session and reported in the summary. The CLI exposes `--max-iterations` for explicit control. Conversation history is pruned to include only the system prompt, the current generation/revision request, and the most recent feedback — not the full history.

- **[Risk] LLM converges to the same hypothesis family across iterations** → Mitigation: the `GENERATE_PROMPT` includes `{rejection_history}` summarising previously rejected hypotheses and their failure reasons, explicitly instructing the LLM to explore different market hypotheses. Temperature is configurable (default 0.7) to balance diversity with coherence.

- **[Risk] Prompt templates become stale as the `StrategyCandidate` schema evolves** → Mitigation: the `YAML_SCHEMA_REFERENCE` is a single constant that mirrors the dataclass fields. Schema changes are rare (the research lab spec controls them). A comment in the constant points to `controllers.research.__init__.StrategyCandidate` as the source of truth.

- **[Risk] Test suite cannot run actual LLM calls** → Mitigation: all tests mock `LlmClient` with pre-scripted responses. The `Protocol` pattern makes mock injection trivial. Integration testing with a real LLM provider is left to manual runs with `--max-iterations 1`.
