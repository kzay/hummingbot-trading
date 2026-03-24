## ADDED Requirements

### Requirement: Rolling signal frequency counter
The controller SHALL maintain a rolling 24-hour counter of signal activations (times when `side != "off"` in `_update_pb_state()`). The counter SHALL use a deque of timestamps with a 24-hour TTL window.

#### Scenario: Signal counted on activation
- **WHEN** `_update_pb_state()` produces side "buy" or "sell" (not "off")
- **THEN** the current timestamp SHALL be appended to the signal counter deque

#### Scenario: Old entries pruned
- **WHEN** a new signal is counted and the deque contains entries older than 24 hours
- **THEN** entries older than 24 hours SHALL be removed from the deque before counting

#### Scenario: Counter exposed in telemetry
- **WHEN** `_extend_processed_data_before_log()` is called
- **THEN** `pb_signal_count_24h` SHALL be included in processed_data with the current count

### Requirement: Low signal frequency warning
The controller SHALL emit a warning log when the 24-hour signal count falls below `pb_min_signals_warn`.

#### Scenario: Signal count below threshold
- **WHEN** a tick fires and `len(signal_counter)` is 2 and `pb_min_signals_warn` is 3
- **THEN** the controller SHALL log a WARNING: "pullback signal frequency low: 2 signals in 24h (threshold: 3)"

#### Scenario: Warning rate limiting
- **WHEN** the signal count is below threshold on consecutive ticks
- **THEN** the warning SHALL be logged at most once per hour to avoid log spam

#### Scenario: Signal count above threshold
- **WHEN** `len(signal_counter)` is 5 and `pb_min_signals_warn` is 3
- **THEN** no warning SHALL be logged

### Requirement: Signal diagnostics in format status
The `to_format_status()` method SHALL include the 24h signal count in its output.

#### Scenario: Status line includes signal count
- **WHEN** `to_format_status()` is called
- **THEN** the output SHALL include a line like: "pullback signals_24h=5 (threshold=3)"

### Requirement: Signal diagnostics config parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `pb_min_signals_warn` | int | 3 | 24h signal count warning threshold |
| `pb_signal_diagnostics_enabled` | bool | True | Enable signal frequency tracking |

#### Scenario: Diagnostics disabled
- **WHEN** `pb_signal_diagnostics_enabled` is False
- **THEN** no signal counting, no warning logging, and `pb_signal_count_24h` SHALL be reported as -1 in telemetry
