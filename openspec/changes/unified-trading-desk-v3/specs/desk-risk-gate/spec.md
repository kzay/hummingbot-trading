## ADDED Requirements

### Requirement: DeskRiskGate enforces layered risk evaluation
The system SHALL evaluate risk in three sequential layers before any order execution:
1. `PortfolioRiskGate` — cross-bot portfolio-level risk (reads `PORTFOLIO_RISK_STREAM`)
2. `BotRiskGate` — per-bot risk limits (daily loss, drawdown, turnover, margin)
3. `SignalRiskGate` — per-signal quality checks (edge gate, adverse fill, selective quoting, cooldown)

Each layer SHALL implement the `RiskLayer` protocol: `evaluate(signal, snapshot) -> RiskDecision`. If any layer rejects, subsequent layers SHALL NOT execute.

#### Scenario: Portfolio risk gate triggers hard stop
- **WHEN** `PortfolioRiskGate` reads a breach event from `PORTFOLIO_RISK_STREAM`
- **THEN** it returns `RiskDecision(approved=False, reason="portfolio_breach", layer="portfolio")` and bot-level and signal-level gates are skipped

#### Scenario: All three layers approve
- **WHEN** portfolio risk is clear, bot daily loss is within limits, and signal edge is positive
- **THEN** all three layers return `approved=True` and the final `RiskDecision` reflects the most restrictive modification (e.g., reduced sizing from bot layer)

#### Scenario: Bot layer reduces sizing
- **WHEN** `BotRiskGate` detects daily turnover at 80% of the hard cap
- **THEN** it returns `RiskDecision(approved=True, modified_signal=signal_with_reduced_size)` and the signal layer evaluates the reduced signal

### Requirement: PortfolioRiskGate reads cross-bot risk from Redis
The system SHALL implement `PortfolioRiskGate` to consume `PORTFOLIO_RISK_STREAM` events. When a portfolio breach is detected, the gate SHALL hard-stop all signal processing for the affected instruments. The gate SHALL support configurable breach thresholds via the strategy's risk profile.

#### Scenario: Portfolio risk stream publishes breach
- **WHEN** `PORTFOLIO_RISK_STREAM` contains an event with `action="hard_stop"` for the current instrument
- **THEN** `PortfolioRiskGate.evaluate()` returns `approved=False` with `reason="portfolio_hard_stop"`

#### Scenario: No portfolio risk events
- **WHEN** `PORTFOLIO_RISK_STREAM` has no recent breach events
- **THEN** `PortfolioRiskGate.evaluate()` returns `approved=True` with no modifications

### Requirement: BotRiskGate enforces per-bot daily and drawdown limits
The system SHALL implement `BotRiskGate` with configurable thresholds:
- `max_daily_loss_pct_hard` — reject signals when daily loss exceeds this threshold
- `max_drawdown_pct_hard` — reject signals when drawdown from peak exceeds this threshold
- `max_daily_turnover_x_hard` — reject signals when daily turnover exceeds this multiple
- `margin_ratio_critical` — reject signals when margin ratio falls below this level (perp only)

#### Scenario: Daily loss hard stop
- **WHEN** `snapshot.equity.daily_loss_pct` exceeds `max_daily_loss_pct_hard`
- **THEN** `BotRiskGate.evaluate()` returns `approved=False` with `reason="daily_loss_hard_stop"`

#### Scenario: Turnover soft cap reduces sizing
- **WHEN** `snapshot.equity.daily_turnover_x` is between 80% and 100% of `max_daily_turnover_x_hard`
- **THEN** `BotRiskGate.evaluate()` returns `approved=True` with `modified_signal` having proportionally reduced `levels[].size_quote`

#### Scenario: Drawdown hard stop
- **WHEN** `snapshot.equity.max_drawdown_pct` exceeds `max_drawdown_pct_hard`
- **THEN** `BotRiskGate.evaluate()` returns `approved=False` with `reason="drawdown_hard_stop"`

### Requirement: SignalRiskGate enforces per-signal quality checks
The system SHALL implement `SignalRiskGate` with the following configurable checks:
- **Edge gate**: reject signals when EWMA net edge falls below `min_net_edge_bps`, resume when above `edge_resume_bps` (hysteresis)
- **Adverse fill ratio**: widen spreads or reduce participation when adverse fill ratio exceeds threshold
- **Selective quoting quality**: score [0,1] based on fill edge, adverse ratio, slippage — reduce/block quoting when quality is low
- **Signal cooldown**: per-side minimum interval between directional signals

#### Scenario: Edge gate blocks signal
- **WHEN** EWMA net edge is 3.0 bps and `min_net_edge_bps` is 5.5
- **THEN** `SignalRiskGate.evaluate()` returns `approved=False` with `reason="edge_gate_blocked"`

#### Scenario: Edge gate resumes with hysteresis
- **WHEN** edge was blocked and EWMA net edge rises to 6.5 bps with `edge_resume_bps` at 6.0
- **THEN** `SignalRiskGate.evaluate()` returns `approved=True` and clears the edge-blocked state

#### Scenario: Signal cooldown rejects rapid signals
- **WHEN** a directional buy signal was processed 60 seconds ago and cooldown is 180 seconds
- **THEN** `SignalRiskGate.evaluate()` returns `approved=False` with `reason="signal_cooldown_active"`

### Requirement: RiskDecision is a typed dataclass with audit trail
The system SHALL define `RiskDecision` with: `approved` (bool), `modified_signal` (TradingSignal | None), `reason` (str), `layer` (str), `metadata` (dict). Every risk decision SHALL be emitted to the `hb.risk_decision.v1` Redis stream for audit.

#### Scenario: Risk decision is published to Redis
- **WHEN** a risk decision is made (approved or rejected)
- **THEN** the desk publishes a `RiskDecisionEvent` to `hb.risk_decision.v1` containing the decision, layer, reason, and signal metadata
