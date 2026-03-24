## ADDED Requirements

### Requirement: Per-side signal cooldown prevents re-entry on the same BB touch

The system SHALL track the timestamp of the most recent entry signal activation per side (`"buy"` and `"sell"`) in `_bot7_last_signal_ts: dict[str, float]`. When `_update_bot7_state` would otherwise activate a signal, it MUST check whether `now - _bot7_last_signal_ts[side] < bot7_signal_cooldown_s`. If the cooldown is active, the signal MUST be suppressed: `side = "off"`, `reason = "signal_cooldown"`.

#### Scenario: Entry suppressed during cooldown window

- **WHEN** a valid entry signal fires (all gates pass) and the elapsed time since last activation on that side is less than `bot7_signal_cooldown_s`
- **THEN** `side` is set to `"off"`, `reason` is set to `"signal_cooldown"`, and `active` is `False`

#### Scenario: Entry permitted after cooldown expires

- **WHEN** a valid entry signal fires and the elapsed time since last activation on that side is greater than or equal to `bot7_signal_cooldown_s`
- **THEN** the signal proceeds normally, cooldown does not suppress it, and `_bot7_last_signal_ts[side]` is updated to the current timestamp

#### Scenario: Cooldown is side-specific

- **WHEN** a buy signal fires and is recorded in the cooldown tracker
- **THEN** the sell-side cooldown is unaffected; a sell signal within the same cooldown window is not suppressed by the buy-side cooldown

#### Scenario: First signal after startup is never suppressed by cooldown

- **WHEN** the bot starts up and no signal has been recorded yet (`_bot7_last_signal_ts` is empty or missing key)
- **THEN** the first signal on that side proceeds normally regardless of `bot7_signal_cooldown_s`

### Requirement: Cooldown timestamp is updated only on signal activation

The system SHALL update `_bot7_last_signal_ts[side]` only when a signal actually activates (`active = True`, `side != "off"`). Probe mode activations MUST also update the cooldown timestamp using the probe's side.

#### Scenario: Cooldown updated on full signal activation

- **WHEN** `_update_bot7_state` sets `side = "buy"` and `reason = "mean_reversion_long"`
- **THEN** `_bot7_last_signal_ts["buy"]` is set to the current wall-clock time

#### Scenario: Cooldown updated on probe activation

- **WHEN** `_update_bot7_state` sets `side = "sell"` and `reason = "probe_short"`
- **THEN** `_bot7_last_signal_ts["sell"]` is set to the current wall-clock time

#### Scenario: Cooldown not updated when signal is off

- **WHEN** `_update_bot7_state` resolves `side = "off"` for any reason
- **THEN** `_bot7_last_signal_ts` is not modified

### Requirement: Cooldown state is in-memory only

The cooldown tracker MUST be initialised in `__init__` and MUST NOT be persisted to disk or shared with other controller instances. A bot restart resets all cooldown timestamps.

#### Scenario: Fresh state on construction

- **WHEN** `Bot7AdaptiveGridV1Controller.__init__` is called
- **THEN** `_bot7_last_signal_ts` is initialised as an empty dict `{}`
