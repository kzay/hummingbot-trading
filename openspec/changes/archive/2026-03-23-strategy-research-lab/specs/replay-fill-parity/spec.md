## ADDED Requirements

### Requirement: Default fill model alignment

`ReplayHarness._create_desk()` SHALL set `DeskConfig.default_fill_model` to `"latency_aware"` by default, matching the `BacktestHarness` default. The replay config YAML MAY override this with a `fill_model` field.

#### Scenario: Replay uses latency_aware by default
- **WHEN** a replay config YAML does not specify `fill_model`
- **THEN** the replay desk uses `latency_aware` fill model

#### Scenario: Replay config override
- **WHEN** a replay config YAML sets `fill_model: "queue_position"`
- **THEN** the replay desk uses `queue_position`

#### Scenario: Comparable results
- **WHEN** the same strategy is run via `BacktestHarness` and `ReplayHarness` with matching configs and data
- **THEN** the fill model used is the same (`latency_aware`) ensuring results are comparable at the fill-simulation level
