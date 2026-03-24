## ADDED Requirements

### Requirement: System prompt with falsifiability rules

The system SHALL provide a `SYSTEM_PROMPT` string constant in `hbot/controllers/research/exploration_prompts.py` that instructs the LLM to:

1. Generate strategy hypotheses that are falsifiable — each must predict a specific market behavior that can be confirmed or rejected by backtesting.
2. Never use lookahead bias — entry/exit logic must reference only information available at decision time (open price and volume on the current bar; historical bars only).
3. Output exactly one valid YAML block per response conforming to the `StrategyCandidate` schema.
4. Select an `adapter_mode` from the provided list of available modes.
5. Define a `parameter_space` with at least 2 parameters, each with 3-4 discrete values for sweep.
6. Write `entry_logic` and `exit_logic` as plain-English descriptions referencing indicator names and parameter variables.
7. Set `base_config` fields appropriate for the specified market (pair, exchange, instrument type).

#### Scenario: System prompt is a string constant
- **WHEN** `exploration_prompts.SYSTEM_PROMPT` is accessed
- **THEN** it is a non-empty string with no Python imports or function calls

#### Scenario: Falsifiability rule present
- **WHEN** the system prompt is read
- **THEN** it contains the word "falsifiable" and instructions prohibiting unfalsifiable claims

#### Scenario: Lookahead prohibition present
- **WHEN** the system prompt is read
- **THEN** it contains explicit instructions against using future price data (close/high/low of current bar before bar completion)

### Requirement: YAML schema reference

The system SHALL provide a `YAML_SCHEMA_REFERENCE` string constant that documents every required field of the `StrategyCandidate` YAML format:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Kebab-case unique identifier |
| `hypothesis` | string | yes | Falsifiable market prediction |
| `adapter_mode` | string | yes | One of the available adapter modes |
| `parameter_space` | dict | yes | Maps parameter names to lists of values |
| `entry_logic` | string | yes | Plain-English entry conditions |
| `exit_logic` | string | yes | Plain-English exit conditions |
| `base_config` | dict | yes | Backtest configuration (strategy_class, strategy_config, data_source, initial_equity, leverage, seed, step_interval_s, warmup_bars) |
| `required_tests` | list | no | Test names for validation |
| `metadata` | dict | no | Author, version, notes |
| `lifecycle` | string | no | Always `"candidate"` for new entries |

The constant SHALL include a complete example YAML block.

#### Scenario: Schema covers all required fields
- **WHEN** `YAML_SCHEMA_REFERENCE` is read
- **THEN** it mentions all 7 required fields: `name`, `hypothesis`, `adapter_mode`, `parameter_space`, `entry_logic`, `exit_logic`, `base_config`

#### Scenario: Example YAML is valid
- **WHEN** the example YAML block in `YAML_SCHEMA_REFERENCE` is parsed with `yaml.safe_load()`
- **THEN** it produces a dict with all 7 required fields present

### Requirement: Generation prompt template

The system SHALL provide a `GENERATE_PROMPT` string constant with the following placeholders:

- `{available_adapters}` — comma-separated list of adapter mode strings from `ADAPTER_REGISTRY`
- `{market_context}` — formatted string with pair, exchange, instrument type
- `{rejection_history}` — summary of previously rejected hypotheses and their failure reasons (empty string on first iteration)

The prompt SHALL instruct the LLM to generate a new, diverse hypothesis that differs from any previously rejected ones.

#### Scenario: First iteration (no rejections)
- **WHEN** `GENERATE_PROMPT.format(available_adapters=..., market_context=..., rejection_history="")` is called
- **THEN** the result is a valid prompt string with no placeholder artifacts

#### Scenario: With rejection history
- **WHEN** `rejection_history` is a non-empty string describing 2 rejected candidates
- **THEN** the formatted prompt includes that history and instructs the LLM to explore different approaches

### Requirement: Revision prompt template

The system SHALL provide a `REVISE_PROMPT` string constant with the following placeholders:

- `{name}` — the candidate name
- `{score}` — the total robustness score (float)
- `{recommendation}` — the lifecycle recommendation string (`"rejected"`, `"revise"`, `"paper"`)
- `{score_breakdown}` — formatted per-component scores (OOS Sharpe, degradation ratio, parameter stability, fee stress, regime stability, DSR)
- `{report_excerpt}` — first ~100 lines of the Markdown evaluation report
- `{weakest_components}` — names of the two lowest-scoring components

The prompt SHALL instruct the LLM to revise the candidate YAML, specifically addressing the weakest components while preserving strengths.

#### Scenario: Revision prompt formatting
- **WHEN** `REVISE_PROMPT.format(name="test-strat", score=0.32, ...)` is called
- **THEN** the result mentions "test-strat", the score "0.32", and the weakest components

### Requirement: No codebase imports

`exploration_prompts.py` SHALL NOT import any module from the `controllers` or `services` packages. It SHALL contain only string constants and no executable logic.

#### Scenario: Module is import-free
- **WHEN** `exploration_prompts.py` is parsed
- **THEN** it contains no `import` or `from ... import` statements referencing `controllers.*` or `services.*`
