## Why

The strategy research lab provides a robust 6-step evaluation pipeline (backtest → sweep → walk-forward → robustness scoring → manifest → report) and lifecycle governance, but every candidate strategy must be manually authored as a YAML file. This creates a bottleneck: the user is not a quant, so formulating falsifiable hypotheses with exact entry/exit logic and appropriate parameter spaces requires significant domain expertise. The evaluation pipeline is the automated "bullshit detector" — but it has no automated source of hypotheses to judge.

An LLM can generate dozens of strategy hypotheses per session, each formatted as a valid `StrategyCandidate` YAML. The research lab evaluates them, and the LLM reads the rejection reports to iteratively revise weak candidates. The lab remains the judge; the LLM is the prolific intern.

## What Changes

- **New LLM client abstraction** (`llm_client.py`): provider-agnostic adapter supporting Anthropic (Claude) and OpenAI APIs, selected at runtime via env var or CLI flag. This is the only file that imports LLM SDKs.
- **Exploration prompt templates** (`exploration_prompts.py`): system prompt with falsifiability rules and YAML schema reference, hypothesis generation template with market context, and revision template with score breakdown feedback. Pure string constants, no codebase imports.
- **Autonomous exploration session** (`exploration_session.py`): full-loop controller that generates hypotheses via LLM, parses them into `StrategyCandidate` instances, delegates evaluation to the existing `ExperimentOrchestrator`, reads `EvaluationResult` score breakdowns and reports, feeds rejection feedback back to the LLM, and iterates. Produces a session summary report and JSONL conversation log.
- **CLI entry point** (`explore_cli.py`): `python -m controllers.research.explore_cli` with flags for provider, max iterations, pair, exchange, sweep/walkforward toggles.

## Capabilities

### New Capabilities

- `llm-client-adapter`: Provider-agnostic LLM client protocol with concrete implementations for Anthropic (Claude) and OpenAI, runtime selection via environment variable or CLI flag, and cumulative token tracking.
- `exploration-prompts`: Prompt template library encoding falsifiability rules, the `StrategyCandidate` YAML schema, available adapter modes from the registry, and structured revision feedback from robustness score breakdowns.
- `exploration-session`: Autonomous generate-evaluate-revise loop that combines the LLM client with the existing `ExperimentOrchestrator`, producing per-iteration candidate YAMLs, evaluation reports, a session summary, and a conversation log.
- `exploration-cli`: Command-line interface for launching exploration sessions with configurable provider, iteration count, market scope, and evaluation toggles.

### Modified Capabilities

None. The evaluation pipeline, backtesting stack, and runtime code are untouched. Minimal integration changes are limited to dependency packaging and environment variable documentation (see Impact).

## Impact

- **Code**: New files in `hbot/controllers/research/` (4 production files + 1 test file). No modifications to evaluation pipeline logic, backtesting, or runtime code.
- **Data**: New `hbot/data/research/explorations/` directory for session outputs (candidate YAMLs, conversation logs, session summaries). Evaluation reports continue to be written to existing `hbot/data/research/reports/` by the orchestrator.
- **Dependencies**: `anthropic` and `openai` Python SDKs added as an optional extra (`llm`) in `hbot/pyproject.toml`. These are API client libraries only — no model weights, no GPU requirements. Default installs and minimal Docker images are unaffected.
- **Tests**: New test file with mocked LLM client and orchestrator. No changes to existing tests.
- **Config**: New `RESEARCH_LLM_API_KEY` and optional `RESEARCH_LLM_MODEL` environment variables added to `hbot/infra/env/.env.template` under a new section. The client reads `RESEARCH_LLM_API_KEY` as the primary key (compatible with any provider), with provider-specific overrides (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) checked as fallbacks. Existing `LLM_API_KEY` / `LLM_FALLBACK_API_KEY` for the sentiment strategy are not touched.
- **Packaging**: `hbot/pyproject.toml` gains one optional-dependency group: `llm = ["anthropic", "openai"]`.
