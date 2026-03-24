## 1. LLM Client Adapter

- [ ] 1.1 Create `hbot/controllers/research/llm_client.py` with `LlmClient` as a `typing.Protocol` defining `chat(messages: list[dict], temperature: float) -> str` and `count_tokens(text: str) -> int`
- [ ] 1.2 Implement `AnthropicClient` wrapping `anthropic.Anthropic().messages.create()`, reading API key with three-tier lookup (`ANTHROPIC_API_KEY` → `RESEARCH_LLM_API_KEY` → `LLM_API_KEY`) and model from `ANTHROPIC_MODEL` → `RESEARCH_LLM_MODEL` (default `claude-sonnet-4-20250514`); accumulate input/output tokens in `tokens_used` attribute
- [ ] 1.3 Implement `OpenAIClient` wrapping `openai.OpenAI().chat.completions.create()`, reading API key with three-tier lookup (`OPENAI_API_KEY` → `RESEARCH_LLM_API_KEY` → `LLM_API_KEY`) and model from `OPENAI_MODEL` → `RESEARCH_LLM_MODEL` (default `gpt-4o`); accumulate tokens in `tokens_used` attribute
- [ ] 1.4 Implement `build_client(provider: str) -> LlmClient` factory that validates the provider string is `"anthropic"` or `"openai"`, resolves the API key via three-tier lookup, raises `EnvironmentError` if no key is found, and returns the appropriate client instance

## 2. Exploration Prompt Templates

- [ ] 2.1 Create `hbot/controllers/research/exploration_prompts.py` with `SYSTEM_PROMPT` constant encoding rules: falsifiable hypothesis required, no lookahead bias, exact YAML output format, adapter mode selection guidance
- [ ] 2.2 Add `YAML_SCHEMA_REFERENCE` constant documenting all required `StrategyCandidate` fields (`name`, `hypothesis`, `adapter_mode`, `parameter_space`, `entry_logic`, `exit_logic`, `base_config`, `required_tests`, `metadata`) with types and a complete example
- [ ] 2.3 Add `GENERATE_PROMPT` template with `{available_adapters}`, `{market_context}`, and `{rejection_history}` placeholders for initial hypothesis generation
- [ ] 2.4 Add `REVISE_PROMPT` template with `{name}`, `{score}`, `{recommendation}`, `{score_breakdown}`, `{report_excerpt}`, and `{weakest_components}` placeholders for iterative revision feedback

## 3. Exploration Session

- [ ] 3.1 Create `hbot/controllers/research/exploration_session.py` with `SessionConfig` dataclass containing: `max_iterations` (default 5), `max_parse_retries` (default 2), `pair`, `exchange`, `instrument_type`, `llm_provider`, `temperature`, `skip_sweep`, `skip_walkforward`, `fill_model`, `output_dir`, `reports_dir` (default `hbot/data/research/reports`), `experiments_dir` (default `hbot/data/research/experiments`), `lifecycle_dir` (default `hbot/data/research/lifecycle`)
- [ ] 3.2 Implement `ExplorationSession.__init__(config: SessionConfig)` that builds the `LlmClient` via `build_client()`, creates the session output directory with timestamp, and initialises the conversation history list
- [ ] 3.3 Implement `_build_market_context() -> str` that reads `ADAPTER_REGISTRY` keys and formats the available adapter modes, pair, exchange, and instrument type into a context string for the LLM
- [ ] 3.4 Implement `_parse_candidate_yaml(raw_text: str) -> StrategyCandidate` that extracts a YAML block from the LLM response (between ` ```yaml ` and ` ``` ` fences or raw YAML), calls `yaml.safe_load()`, validates required fields, and constructs a `StrategyCandidate`; raises `ValueError` on parse failure
- [ ] 3.5 Implement `_build_revision_feedback(result: EvaluationResult) -> str` that formats the score breakdown, identifies the two weakest scoring components, reads the first ~100 lines of the report at `result.report_path`, and fills the `REVISE_PROMPT` template
- [ ] 3.6 Implement `ExplorationSession.run() -> SessionResult` main loop: for each iteration, call LLM with generate or revise prompt, parse response into candidate (with retry on failure), save candidate YAML, call `ExperimentOrchestrator(eval_config).evaluate(candidate)`, read result, optionally transition lifecycle (`reject → rejected`, `pass → paper` — never `promoted`), build feedback if rejected/revise, log conversation entry; after loop, generate session summary
- [ ] 3.7 Implement `_generate_session_report() -> str` that produces a Markdown summary with: session config, iteration outcomes table (name, score, recommendation), best candidate, total tokens used, and references to per-iteration report paths
- [ ] 3.8 Implement conversation logging: append each LLM request/response to `conversation_log.jsonl` with fields `iteration`, `role`, `content`, `timestamp_utc`, `tokens`
- [ ] 3.9 Define `SessionResult` dataclass with `best_observed_score: float`, `best_observed_candidate: str | None`, `best_recommendation: str | None`, `iterations: list[dict]`, `total_tokens: int`, `summary_path: str` — `best_observed_*` tracks the highest `score_breakdown.total_score` seen regardless of lifecycle recommendation

## 4. CLI Entry Point

- [ ] 4.1 Create `hbot/controllers/research/explore_cli.py` with `argparse` defining: `--max-iterations` (int, default 5), `--provider` (str, default `"anthropic"`), `--pair` (str, default `"BTC-USDT"`), `--exchange` (str, default `"bitget"`), `--instrument-type` (str, default `"perp"`), `--temperature` (float, default 0.7), `--skip-sweep` (flag), `--skip-walkforward` (flag), `--output-dir` (str), `--reports-dir` (str), `--experiments-dir` (str), `--lifecycle-dir` (str), `-v` / `--verbose` (flag for DEBUG logging)
- [ ] 4.2 Wire CLI to build `SessionConfig` from parsed args, create `ExplorationSession`, call `session.run()`, and print the session result summary to stdout
- [ ] 4.3 Set exit code 0 on success, 1 on unrecoverable error; log iteration progress at INFO level

## 5. Tests

- [ ] 5.1 Create `hbot/tests/controllers/test_research/test_exploration_session.py` with a mock `LlmClient` that returns pre-scripted YAML responses and a mock `ExperimentOrchestrator` that returns pre-built `EvaluationResult` objects
- [ ] 5.2 Test `_parse_candidate_yaml`: valid YAML (with and without code fences), malformed YAML, and YAML missing required fields
- [ ] 5.3 Test parse retry: LLM returns invalid YAML on first call, valid on second; verify retry count respects `max_parse_retries`
- [ ] 5.4 Test revision feedback: verify `_build_revision_feedback` includes score, weakest components, and report excerpt
- [ ] 5.5 Test session loop: mock 3 iterations, verify `SessionResult.iterations` has 3 entries, `best_observed_score` reflects the highest `total_score` seen (even if that candidate was rejected), `total_tokens` accumulates
- [ ] 5.6 Test conversation log: verify `conversation_log.jsonl` is written with correct structure after a session run
- [ ] 5.7 Test CLI smoke: call `explore_cli.main()` with mocked session execution, verify argparse wiring and exit codes

## 6. Packaging & Environment Alignment

- [ ] 6.1 Add optional dependency group `llm = ["anthropic", "openai"]` to `hbot/pyproject.toml` under `[project.optional-dependencies]`
- [ ] 6.2 Add `# ── Research LLM Exploration ──` section to `hbot/infra/env/.env.template` with `RESEARCH_LLM_API_KEY=` and `RESEARCH_LLM_MODEL=` entries (commented documentation only; existing `LLM_*` entries untouched)

## 7. Verification

- [ ] 7.1 Compile-check all new files: `python -m py_compile hbot/controllers/research/llm_client.py`, `exploration_prompts.py`, `exploration_session.py`, `explore_cli.py`
- [ ] 7.2 Create `hbot/data/research/explorations/.gitkeep` to ensure the output directory exists in version control
- [ ] 7.3 Run full test suite: `PYTHONPATH=hbot python -m pytest hbot/tests/controllers/test_research/test_exploration_session.py -x -q`
