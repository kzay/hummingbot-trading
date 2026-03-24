## ADDED Requirements

### Requirement: StrategyCandidate dataclass

The system SHALL define a `StrategyCandidate` dataclass in `hbot/controllers/research/__init__.py` with fields: `name` (str), `hypothesis` (str, the market hypothesis being tested), `adapter_mode` (str, key into the existing adapter registry), `parameter_space` (dict mapping param names to lists or ranges), `entry_logic` (str, human-readable description of entry rules), `exit_logic` (str, human-readable description of exit rules), `base_config` (dict, the base backtest config as YAML-compatible dict), `required_tests` (list of str, names of sanity/unit tests that must pass), and `metadata` (optional dict for tags, author, creation date).

#### Scenario: Parse candidate from YAML
- **WHEN** a YAML file with all required fields is loaded via `StrategyCandidate.from_yaml(path)`
- **THEN** a `StrategyCandidate` instance is returned with all fields populated

#### Scenario: Missing required field raises error
- **WHEN** a YAML file omits the `hypothesis` field
- **THEN** a `ValueError` is raised with a message naming the missing field

### Requirement: StrategyCandidate serialisation

The system SHALL support round-trip serialisation: `StrategyCandidate.to_yaml(path)` writes YAML that `StrategyCandidate.from_yaml(path)` can reload with identical field values.

#### Scenario: Round-trip YAML
- **WHEN** a candidate is saved via `to_yaml()` and reloaded via `from_yaml()`
- **THEN** all fields of the reloaded candidate equal the original

### Requirement: StrategyLifecycle enum

The system SHALL define a `StrategyLifecycle` enum with values: `candidate`, `rejected`, `revise`, `paper`, `promoted`.

#### Scenario: Valid lifecycle transitions
- **WHEN** a candidate's lifecycle is `candidate`
- **THEN** it can transition to `rejected`, `revise`, or `paper`

#### Scenario: Promoted is terminal
- **WHEN** a candidate's lifecycle is `promoted`
- **THEN** no further transitions are allowed (calling `transition()` raises `ValueError`)
