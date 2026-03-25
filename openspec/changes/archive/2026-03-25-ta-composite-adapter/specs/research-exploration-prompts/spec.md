## ADDED Requirements

### Requirement: Exploration prompts SHALL document ta_composite adapter
The exploration prompts in `controllers/research/exploration_prompts.py` SHALL include `ta_composite` in the adapter reference material shown to the LLM.

The `ta_composite` entry SHALL describe:
- Style: "Composable TA"
- Best for: "Arbitrary TA signal combinations via YAML rules"
- Key levers: "entry_rules, exit_rules, signal types, sl/tp/trail"

#### Scenario: LLM discovers ta_composite
- **WHEN** the LLM receives the system prompt
- **THEN** the adapter reference includes a `ta_composite` row with style, use case, and key levers

### Requirement: YAML schema reference SHALL show a valid `ta_composite` example
The prompt-side YAML schema reference SHALL include a complete `ta_composite`
example showing:
- `entry_rules` with `mode` and a multi-signal `signals` list
- `exit_rules`
- ATR-based position-management fields
- an explicit note that `min_warmup_bars` is an optional floor and does not
  replace the adapter's derived warmup requirement

#### Scenario: LLM generates valid ta_composite YAML
- **WHEN** the LLM proposes a strategy using `adapter_mode: ta_composite`
- **THEN** the YAML includes `entry_rules`, `exit_rules`, and position-management fields consistent with the documented schema

### Requirement: Available adapter list SHALL include `ta_composite`
The exploration-session configuration SHALL expose `"ta_composite"` in the
available adapter list used for candidate generation and validation.

#### Scenario: Session config includes ta_composite
- **WHEN** `SessionConfig.available_adapters` is initialized
- **THEN** the list includes `"ta_composite"` alongside the existing adapter modes
