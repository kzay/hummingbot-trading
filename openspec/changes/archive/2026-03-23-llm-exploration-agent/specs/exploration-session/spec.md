## ADDED Requirements

### Requirement: Session configuration

The system SHALL provide a `SessionConfig` dataclass in `hbot/controllers/research/exploration_session.py` with the following fields and defaults:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_iterations` | int | 5 | Maximum generate-evaluate-revise cycles |
| `max_parse_retries` | int | 2 | Retries when LLM output fails YAML parsing |
| `pair` | str | `"BTC-USDT"` | Trading pair |
| `exchange` | str | `"bitget"` | Exchange name |
| `instrument_type` | str | `"perp"` | Instrument type |
| `llm_provider` | str | `"anthropic"` | LLM provider for `build_client()` |
| `temperature` | float | 0.7 | LLM sampling temperature |
| `skip_sweep` | bool | False | Skip parameter sweep in evaluation |
| `skip_walkforward` | bool | False | Skip walk-forward in evaluation |
| `fill_model` | str | `"latency_aware"` | Fill model for backtesting |
| `output_dir` | str | `"hbot/data/research/explorations"` | Base directory for session outputs |
| `reports_dir` | str | `"hbot/data/research/reports"` | Directory for evaluation reports (passed to `EvaluationConfig`) |
| `experiments_dir` | str | `"hbot/data/research/experiments"` | Directory for experiment manifests (passed to `EvaluationConfig`) |
| `lifecycle_dir` | str | `"hbot/data/research/lifecycle"` | Directory for lifecycle state files |

#### Scenario: Default configuration
- **WHEN** `SessionConfig()` is created with no arguments
- **THEN** all fields have the documented default values, including the three research directory paths

### Requirement: Session initialisation

`ExplorationSession.__init__(config: SessionConfig)` SHALL:

1. Build an `LlmClient` via `build_client(config.llm_provider)`.
2. Create the session output directory at `{config.output_dir}/session_{timestamp}` where `{timestamp}` is `YYYYMMDD_HHMMSS` in UTC.
3. Initialise an empty conversation history list.
4. Initialise an empty iterations result list.

#### Scenario: Directory creation
- **WHEN** `ExplorationSession(config)` is constructed
- **THEN** a new directory exists at the expected session path

### Requirement: Market context construction

`_build_market_context() -> str` SHALL read the keys of `ADAPTER_REGISTRY` from `controllers.backtesting.adapter_registry` and format a context string containing:
- The list of available adapter modes
- The configured pair, exchange, and instrument type from `SessionConfig`

#### Scenario: Context includes all adapter modes
- **WHEN** `_build_market_context()` is called
- **THEN** the returned string contains all 9 adapter modes from `ADAPTER_REGISTRY`

### Requirement: YAML parsing from LLM output

`_parse_candidate_yaml(raw_text: str) -> StrategyCandidate` SHALL perform **syntactic/schema validation only**:

1. Attempt to extract YAML content from between ` ```yaml ` and ` ``` ` code fences.
2. If no code fences are found, attempt to parse the entire text as YAML.
3. Call `yaml.safe_load()` on the extracted content.
4. Validate that all 7 required `StrategyCandidate` fields are present (structural check).
5. Construct and return a `StrategyCandidate` instance.
6. Raise `ValueError` with a descriptive message if any step fails.

This method SHALL NOT validate adapter mode correctness, parameter name validity against adapter config classes, or any other semantic/runtime constraints. Semantic validation is the responsibility of `ExperimentOrchestrator.evaluate()` at step 1 (verification backtest).

#### Scenario: Valid YAML with code fences
- **WHEN** `raw_text` contains ` ```yaml\nname: test\n...\n``` `
- **THEN** the YAML between fences is parsed and a `StrategyCandidate` is returned

#### Scenario: Valid YAML without code fences
- **WHEN** `raw_text` is raw YAML with all required fields
- **THEN** a `StrategyCandidate` is returned

#### Scenario: Malformed YAML
- **WHEN** `raw_text` contains invalid YAML syntax
- **THEN** `ValueError` is raised with the YAML parse error

#### Scenario: Missing required field
- **WHEN** the YAML is valid but `hypothesis` field is missing
- **THEN** `ValueError` is raised mentioning the missing field

### Requirement: Revision feedback construction

`_build_revision_feedback(result: EvaluationResult) -> str` SHALL:

1. Read `result.score_breakdown` to get per-component scores.
2. Identify the two components with the lowest scores.
3. Read up to the first 100 lines of the Markdown report at `result.report_path`.
4. Format the `REVISE_PROMPT` template with the candidate name, total score, recommendation, formatted score breakdown, report excerpt, and weakest component names.

#### Scenario: Feedback includes weakest components
- **WHEN** an `EvaluationResult` has `fee_stress_margin=0.1` and `regime_stability=0.2` as the two lowest
- **THEN** the feedback string names both components and suggests the LLM address them

#### Scenario: Report file missing
- **WHEN** `result.report_path` points to a non-existent file
- **THEN** the feedback is still generated with an empty report excerpt and a note that the report was unavailable

### Requirement: Main exploration loop

`ExplorationSession.run() -> SessionResult` SHALL execute the following loop for up to `max_iterations`:

1. **Generate**: Call `LlmClient.chat()` with the system prompt and either `GENERATE_PROMPT` (first iteration or after a pass) or `REVISE_PROMPT` (after reject/revise).
2. **Parse**: Call `_parse_candidate_yaml()` on the LLM response. On `ValueError`, retry up to `max_parse_retries` times, sending the error message back to the LLM for correction.
3. **Save**: Call `candidate.to_yaml()` to persist the candidate at `{session_dir}/iteration_{n}_candidate.yml`.
4. **Evaluate**: Create `EvaluationConfig` from `SessionConfig` fields, call `ExperimentOrchestrator(eval_config).evaluate(candidate)`.
5. **Record**: Append iteration outcome (name, score, recommendation) to the iterations list. Track the highest `score_breakdown.total_score` seen as `best_observed_score` regardless of recommendation.
6. **Lifecycle** (optional): If recommendation is `"rejected"`, transition lifecycle to `rejected`. If `"paper"`, transition to `paper`. Never auto-transition to `promoted`.
7. **Feedback**: If recommendation is `"rejected"` or `"revise"`, call `_build_revision_feedback()` and prepare the next LLM call with the revision prompt. If `"paper"`, add to rejection history as a success and generate a fresh hypothesis on the next iteration.
8. **Log**: Append all LLM messages to the conversation log.

After the loop, call `_generate_session_report()` and return `SessionResult`.

#### Scenario: Full loop with 3 iterations
- **WHEN** `max_iterations=3` and the LLM generates valid YAML on each iteration
- **THEN** `SessionResult.iterations` has exactly 3 entries

#### Scenario: Parse retry
- **WHEN** the LLM returns invalid YAML on the first attempt but valid YAML on the retry
- **THEN** evaluation proceeds with the valid candidate and the retry is logged

#### Scenario: All retries exhausted
- **WHEN** the LLM fails to produce valid YAML after `max_parse_retries` attempts
- **THEN** the iteration is recorded as `"parse_failed"` and the loop continues to the next iteration

#### Scenario: Evaluation error
- **WHEN** `ExperimentOrchestrator.evaluate()` raises an exception (e.g., adapter mode not found)
- **THEN** the iteration is recorded as `"eval_failed"` with the error message, and the loop continues

### Requirement: Session result

The system SHALL provide a `SessionResult` dataclass with:

| Field | Type | Description |
|-------|------|-------------|
| `best_observed_score` | float | Highest `total_score` seen across all iterations, regardless of recommendation (0.0 if no evaluation completed) |
| `best_observed_candidate` | str or None | Name of the candidate with the highest observed score |
| `best_recommendation` | str or None | Lifecycle recommendation of the highest-scoring candidate (`"rejected"`, `"revise"`, or `"paper"`) |
| `iterations` | list[dict] | Per-iteration outcomes with keys: `iteration`, `name`, `score`, `recommendation`, `report_path` |
| `total_tokens` | int | Cumulative tokens used across all LLM calls |
| `summary_path` | str | Path to the session summary Markdown file |

#### Scenario: No passing candidates
- **WHEN** all iterations result in rejection
- **THEN** `best_observed_score` is the highest score among rejected candidates, `best_observed_candidate` is the name of that candidate, and `best_recommendation` is `"rejected"`

#### Scenario: Mixed outcomes
- **WHEN** iteration 1 scores 0.6 (rejected) and iteration 2 scores 0.4 (paper)
- **THEN** `best_observed_score` is 0.6, `best_observed_candidate` is iteration 1's name, and `best_recommendation` is `"rejected"` — the highest score wins regardless of lifecycle outcome

### Requirement: Session summary report

`_generate_session_report() -> str` SHALL produce a Markdown file at `{session_dir}/session_summary.md` containing:

1. Session configuration (provider, pair, max iterations, temperature).
2. An iteration outcomes table with columns: Iteration, Name, Score, Recommendation.
3. The best candidate name and score.
4. Total tokens used.
5. References to per-iteration report paths.

#### Scenario: Summary file written
- **WHEN** `run()` completes
- **THEN** `{session_dir}/session_summary.md` exists and contains all documented sections

### Requirement: Conversation log

The system SHALL write a `conversation_log.jsonl` file in the session directory. Each line SHALL be a JSON object with:

| Field | Type | Description |
|-------|------|-------------|
| `iteration` | int | Iteration number (1-indexed) |
| `role` | str | `"user"` or `"assistant"` |
| `content` | str | Message content |
| `timestamp_utc` | str | ISO 8601 timestamp |
| `tokens` | int | Approximate token count of this message |

#### Scenario: Log completeness
- **WHEN** a session with 2 iterations completes
- **THEN** `conversation_log.jsonl` contains at least 4 lines (2 user prompts + 2 assistant responses)

### Requirement: No duplication of evaluation logic

`ExplorationSession` SHALL NOT:
- Import or call `BacktestHarness`, `SweepRunner`, `WalkForwardRunner`, `RobustnessScorer`, `HypothesisRegistry`, or `ReportGenerator` directly.
- Implement any backtest configuration building beyond passing `SessionConfig` fields to `EvaluationConfig`.
- Implement scoring, manifest recording, or report generation logic.

All evaluation logic SHALL be delegated to `ExperimentOrchestrator.evaluate()`.

#### Scenario: Import check
- **WHEN** `exploration_session.py` imports are inspected
- **THEN** it imports `ExperimentOrchestrator`, `EvaluationConfig`, `EvaluationResult` from `controllers.research.experiment_orchestrator` but does NOT import `BacktestHarness`, `SweepRunner`, `WalkForwardRunner`, `RobustnessScorer`, `HypothesisRegistry`, or `ReportGenerator`
