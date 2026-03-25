## ADDED Requirements

### Requirement: SessionConfig includes resolution and step_interval_s fields
The `SessionConfig` dataclass SHALL include `resolution: str` (default `"15m"`) and `step_interval_s: int` (default `900`) fields that propagate to all downstream research modules.

#### Scenario: Default resolution is 15m
- **WHEN** a `SessionConfig` is created without explicit resolution
- **THEN** `config.resolution` SHALL be `"15m"` and `config.step_interval_s` SHALL be `900`

#### Scenario: Custom resolution can be specified
- **WHEN** a `SessionConfig` is created with `resolution="1h"` and `step_interval_s=3600`
- **THEN** the config SHALL use those values throughout the exploration session

### Requirement: Market context uses configured resolution
The `ExplorationSession` SHALL use `config.resolution` and `config.step_interval_s` when building market context strings and loading historical data, instead of hardcoded `"1m"` / `60`.

#### Scenario: Market context string references configured resolution
- **WHEN** the exploration session builds market context with default config
- **THEN** the context string SHALL reference `"15m"` candles, not `"1m"`

#### Scenario: Data catalog lookup uses configured resolution
- **WHEN** the exploration session calls `catalog.find()` for market data
- **THEN** the resolution parameter SHALL be `config.resolution` (e.g., `"15m"`)

### Requirement: LLM prompts default to 15m with flexibility
The `SYSTEM_PROMPT`, `GENERATE_PROMPT`, and `REVISE_PROMPT` SHALL reference `"15m"` as the default resolution in examples and instructions, but SHALL explicitly state that the LLM may propose other resolutions when a hypothesis requires it.

#### Scenario: YAML examples in prompts use 15m
- **WHEN** the system prompt includes YAML examples
- **THEN** the `resolution` field SHALL show `"15m"` and `step_interval_s` SHALL show `900`

#### Scenario: Prompt allows alternative resolutions
- **WHEN** the LLM reads the system prompt
- **THEN** it SHALL find guidance that other resolutions (e.g., `"5m"`, `"1h"`) are allowed when the hypothesis justifies it

### Requirement: Orchestrator defaults to 15m resolution
The `ExperimentOrchestrator._build_backtest_config` method SHALL use `"15m"` as the default resolution and `900` as the default `step_interval_s` when no explicit value is provided by the candidate YAML.

#### Scenario: Backtest config uses 15m when candidate omits resolution
- **WHEN** a candidate YAML does not specify a `resolution` field
- **THEN** `_build_backtest_config` SHALL produce a config with `resolution="15m"` and `step_interval_s=900`

#### Scenario: Backtest config respects candidate-specified resolution
- **WHEN** a candidate YAML specifies `resolution: "5m"` and `step_interval_s: 300`
- **THEN** `_build_backtest_config` SHALL use those values instead of the defaults
